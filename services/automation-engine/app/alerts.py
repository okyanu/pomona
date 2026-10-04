"""Alert monitor: a risk label must persist before an alert is raised, and stay away before it recovers.

Suggestions (main.py) are created when a person asks for them. Alerts follow every observed reading
of a sensor stream instead:

  normal --label--> pending --label still there after raise_after--> active  ("raised" event)
  pending --label gone--> normal (cancelled, no event)
  active --label gone--> recovering --still gone after clear_after--> normal ("recovered" event)
  recovering --label back--> active (same incident, no new event)

Time is the sensor's sample time, so a retry or a replay gives the same states, and an old or
repeated sample never moves an alert. One incident therefore produces at most one "raised" and one
"recovered" event, however often the label flickers in between. Alerts never act on hardware.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class AlertMonitor:
    def __init__(self, rules: List[Dict[str, Any]], raise_after_seconds: int, clear_after_seconds: int,
                 db_path: Optional[Path] = None, max_events: int = 500) -> None:
        self._rules = rules
        self._raise_after = raise_after_seconds
        self._clear_after = clear_after_seconds
        self._max_events = max_events
        self._lock = threading.Lock()
        if db_path is not None:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path) if db_path is not None else ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS alert_states (
                stream TEXT NOT NULL, rule_id TEXT NOT NULL, state TEXT NOT NULL,
                since TEXT NOT NULL, raised_at TEXT, recovering_since TEXT,
                PRIMARY KEY (stream, rule_id))""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS alert_stream_samples (
                stream TEXT PRIMARY KEY, last_sample TEXT NOT NULL)""")
            self._db.execute("""CREATE TABLE IF NOT EXISTS alert_events (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL, rule_id TEXT NOT NULL,
                event TEXT NOT NULL, sample_time TEXT NOT NULL)""")

    def _windows(self, rule: Dict[str, Any]) -> tuple[timedelta, timedelta]:
        raise_after = rule.get("raise_after_seconds", self._raise_after)
        clear_after = rule.get("clear_after_seconds", self._clear_after)
        return timedelta(seconds=raise_after), timedelta(seconds=clear_after)

    @staticmethod
    def stream_key(farm_id: str, zone_id: str, device_id: Optional[str]) -> str:
        return json.dumps([farm_id, zone_id, device_id])

    def observe(self, farm_id: str, zone_id: str, device_id: Optional[str], sample_time: datetime,
                risk_labels: Iterable[str]) -> Dict[str, Any]:
        """Advance every rule's alert for one reading. Returns {"ignored", "events"}."""
        if sample_time.tzinfo is None:
            raise ValueError("sample_time must include a timezone")
        t = sample_time.astimezone(timezone.utc)
        stream = self.stream_key(farm_id, zone_id, device_id)
        labels = set(risk_labels)
        events: List[Dict[str, Any]] = []
        with self._lock, self._db:
            last = self._db.execute("SELECT last_sample FROM alert_stream_samples WHERE stream=?", (stream,)).fetchone()
            if last and datetime.fromisoformat(last["last_sample"]) >= t:
                return {"ignored": True, "events": []}
            self._db.execute("INSERT INTO alert_stream_samples (stream, last_sample) VALUES (?, ?) "
                             "ON CONFLICT(stream) DO UPDATE SET last_sample=excluded.last_sample", (stream, t.isoformat()))
            for rule in self._rules:
                raise_after, clear_after = self._windows(rule)
                matched = bool(labels & set(rule["match_any_labels"]))
                row = self._db.execute("SELECT * FROM alert_states WHERE stream=? AND rule_id=?",
                                       (stream, rule["id"])).fetchone()
                state = row["state"] if row else "normal"
                if matched:
                    if state == "normal":
                        self._set(stream, rule["id"], "pending", since=t)
                        state, row = "pending", {"since": t.isoformat()}
                    if state == "pending" and t - datetime.fromisoformat(row["since"]) >= raise_after:
                        self._set(stream, rule["id"], "active", since=datetime.fromisoformat(row["since"]), raised_at=t)
                        events.append(self._event(stream, rule["id"], "raised", t))
                    elif state == "recovering":
                        self._set(stream, rule["id"], "active", since=datetime.fromisoformat(row["since"]),
                                  raised_at=datetime.fromisoformat(row["raised_at"]))
                else:
                    if state == "pending":
                        self._db.execute("DELETE FROM alert_states WHERE stream=? AND rule_id=?", (stream, rule["id"]))
                        continue
                    if state == "active":
                        self._set(stream, rule["id"], "recovering", since=datetime.fromisoformat(row["since"]),
                                  raised_at=datetime.fromisoformat(row["raised_at"]), recovering_since=t)
                        state, recovering_since = "recovering", t
                    elif state == "recovering":
                        recovering_since = datetime.fromisoformat(row["recovering_since"])
                    if state == "recovering" and t - recovering_since >= clear_after:
                        self._db.execute("DELETE FROM alert_states WHERE stream=? AND rule_id=?", (stream, rule["id"]))
                        events.append(self._event(stream, rule["id"], "recovered", t))
            self._db.execute("DELETE FROM alert_events WHERE seq NOT IN "
                             "(SELECT seq FROM alert_events ORDER BY seq DESC LIMIT ?)", (self._max_events,))
        return {"ignored": False, "events": events}

    def _set(self, stream: str, rule_id: str, state: str, since: datetime, raised_at: Optional[datetime] = None,
             recovering_since: Optional[datetime] = None) -> None:
        self._db.execute("""INSERT INTO alert_states (stream, rule_id, state, since, raised_at, recovering_since)
            VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(stream, rule_id) DO UPDATE SET state=excluded.state,
            since=excluded.since, raised_at=excluded.raised_at, recovering_since=excluded.recovering_since""",
            (stream, rule_id, state, since.isoformat(), raised_at.isoformat() if raised_at else None,
             recovering_since.isoformat() if recovering_since else None))

    def _event(self, stream: str, rule_id: str, event: str, t: datetime) -> Dict[str, Any]:
        self._db.execute("INSERT INTO alert_events (stream, rule_id, event, sample_time) VALUES (?, ?, ?, ?)",
                         (stream, rule_id, event, t.isoformat()))
        return self._decorate({"stream": stream, "rule_id": rule_id, "event": event, "sample_time": t.isoformat()})

    def _decorate(self, item: Dict[str, Any]) -> Dict[str, Any]:
        farm_id, zone_id, device_id = json.loads(item.pop("stream"))
        rule = next((r for r in self._rules if r["id"] == item["rule_id"]), None)
        return {"farm_id": farm_id, "zone_id": zone_id, "device_id": device_id, **item,
                "action": rule["action"] if rule else None, "message": rule["message"] if rule else None}

    def _in_scope(self, item: Dict[str, Any], farm_id: Optional[str], zone_id: Optional[str]) -> bool:
        return (farm_id is None or item["farm_id"] == farm_id) and (zone_id is None or item["zone_id"] == zone_id)

    def states(self, farm_id: Optional[str] = None, zone_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM alert_states ORDER BY since DESC").fetchall()
        items = [self._decorate(dict(row)) for row in rows]
        return [item for item in items if self._in_scope(item, farm_id, zone_id)]

    def events(self, farm_id: Optional[str] = None, zone_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._db.execute("SELECT stream, rule_id, event, sample_time FROM alert_events ORDER BY seq DESC").fetchall()
        items = [self._decorate(dict(row)) for row in rows]
        return [item for item in items if self._in_scope(item, farm_id, zone_id)][:limit]

    def close(self) -> None:
        self._db.close()
