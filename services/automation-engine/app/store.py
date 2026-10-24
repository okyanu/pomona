"""Bounded SQLite suggestion history; recording decisions never runs hardware."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional

from app.config import settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SuggestionStore:
    def __init__(self, max_suggestions: Optional[int] = None, db_path: Optional[Path] = None, ttl_seconds: Optional[int] = None) -> None:
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.suggestion_ttl_seconds
        if self._ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._max_suggestions = max_suggestions if max_suggestions is not None else settings.max_suggestions
        if self._max_suggestions < 1:
            raise ValueError("max_suggestions must be positive")
        self._lock = Lock()
        if db_path is not None:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path) if db_path is not None else ":memory:",
                                   check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS suggestions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                rule_id TEXT NOT NULL, action TEXT NOT NULL, message TEXT NOT NULL,
                context TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, decided_at TEXT, reviewer TEXT)""")
            # Upgrade the previous local history schema without losing decisions.
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(suggestions)")}
            if "dedupe_key" not in columns:
                self._db.execute("ALTER TABLE suggestions ADD COLUMN dedupe_key TEXT")
            if "expires_at" not in columns:
                self._db.execute("ALTER TABLE suggestions ADD COLUMN expires_at TEXT")
                for row in self._db.execute("SELECT id, created_at, context FROM suggestions").fetchall():
                    self._db.execute("UPDATE suggestions SET expires_at=? WHERE id=?",
                                     (self._expiry(row["created_at"], json.loads(row["context"])), row["id"]))
            # Old rows keep NULL outcome columns: their outcome was never tracked.
            for column in ("outcome_status", "outcome_deadline", "outcome_evidence"):
                if column not in columns:
                    self._db.execute(f"ALTER TABLE suggestions ADD COLUMN {column} TEXT")
            self._db.execute("CREATE UNIQUE INDEX IF NOT EXISTS suggestions_dedupe ON suggestions(dedupe_key)")

    def _expiry(self, created_at: str, context: Dict[str, Any]) -> str:
        created = datetime.fromisoformat(created_at)
        expiry = created + timedelta(seconds=self._ttl_seconds)
        if "sensor_timestamp" in context:
            try:
                sampled = datetime.fromisoformat(context["sensor_timestamp"].replace("Z", "+00:00"))
                if sampled.tzinfo is None or sampled > created + timedelta(seconds=60):
                    raise ValueError("Invalid sample clock")
                expiry = min(expiry, sampled + timedelta(seconds=settings.suggestion_sample_max_age_seconds))
            except (ValueError, TypeError, AttributeError):
                expiry = created
        return expiry.isoformat()

    def _expire(self) -> None:
        now = utc_now_iso()
        self._db.execute("""UPDATE suggestions SET status='expired', decided_at=?
            WHERE status='pending' AND (expires_at IS NULL OR julianday(expires_at)<=julianday(?))""", (now, now))
        for row in self._db.execute("""SELECT id, outcome_evidence FROM suggestions
            WHERE outcome_status='awaiting' AND julianday(outcome_deadline)<=julianday(?)""", (now,)).fetchall():
            self._finalize_outcome(row["id"], json.loads(row["outcome_evidence"]))

    def _finalize_outcome(self, suggestion_id: str, evidence: Dict[str, Any]) -> None:
        # The window ended without N consecutive clean trusted readings.
        enough = evidence["readings_seen"] >= evidence["required_clean_readings"]
        self._db.execute("UPDATE suggestions SET outcome_status=?, outcome_evidence=? WHERE id=?",
                         ("not_recovered" if enough else "unconfirmed",
                          json.dumps({**evidence, "finalized_reason": "window_ended"}), suggestion_id))

    @staticmethod
    def _decode(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item.pop("seq")
        item.pop("dedupe_key", None)
        item["context"] = json.loads(item["context"])
        item["outcome_evidence"] = json.loads(item["outcome_evidence"]) if item.get("outcome_evidence") else None
        item["requires_approval"] = True
        return item

    def add(self, rule_id: str, action: str, message: str, context: Dict[str, Any], event_id: Optional[str] = None) -> Dict[str, Any]:
        suggestion_id = str(uuid.uuid4())
        # Stable event + rule content, never the randomly generated pipeline run ID.
        key = hashlib.sha256(json.dumps([event_id, rule_id, action, message]).encode()).hexdigest() if event_id else None
        created = utc_now_iso()
        with self._lock, self._db:
            self._expire()
            self._db.execute("""INSERT INTO suggestions
                (id, rule_id, action, message, context, status, created_at, dedupe_key, expires_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING""",
                (suggestion_id, rule_id, action, message, json.dumps(context), created, key, self._expiry(created, context)))
            self._expire()
            if key:
                row = self._db.execute("SELECT * FROM suggestions WHERE dedupe_key = ?", (key,)).fetchone()
            else:
                row = self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return self._decode(row)

    def get(self, suggestion_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._db:
            self._expire()
            row = self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return self._decode(row) if row else None

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self._db:
            self._expire()
            if status is None:
                rows = self._db.execute("SELECT * FROM suggestions ORDER BY seq DESC").fetchall()
            else:
                rows = self._db.execute("SELECT * FROM suggestions WHERE status = ? ORDER BY seq DESC", (status,)).fetchall()
        return [self._decode(row) for row in rows]

    def decide(self, suggestion_id: str, status: str, reviewer: Optional[str] = None,
               rules: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        """Record a decision. An approval with a known rule in `rules` starts outcome tracking: later
        readings, not the approval, show whether the problem went away."""
        if status not in {"approved", "rejected"}:
            raise ValueError("Decision must be approved or rejected")
        with self._lock, self._db:
            self._expire()
            decided = utc_now_iso()
            # First decision wins, atomically, even across multiple processes.
            changed = self._db.execute("""UPDATE suggestions SET status = ?, decided_at = ?, reviewer = ?
                WHERE id = ? AND status = 'pending'""", (status, decided, reviewer, suggestion_id)).rowcount
            rule_id = self._rule_id(suggestion_id) if changed and status == "approved" else None
            rule = next((r for r in rules or [] if r["id"] == rule_id), None)
            if rule:
                window = rule.get("response_window_seconds", settings.outcome_response_window_seconds)
                evidence = {"required_clean_readings": settings.outcome_confirm_readings,
                            "watched_labels": list(rule["match_any_labels"]), "readings_seen": 0, "clean_streak": 0,
                            "untrusted_readings": 0, "last_sample_time": None, "resolved_sample_time": None}
                self._db.execute("UPDATE suggestions SET outcome_status='awaiting', outcome_deadline=?, outcome_evidence=? WHERE id=?",
                                 ((datetime.fromisoformat(decided) + timedelta(seconds=window)).isoformat(),
                                  json.dumps(evidence), suggestion_id))
            row = self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
            # Pending work is never purged; only completed history is bounded.
            self._db.execute("""DELETE FROM suggestions WHERE status != 'pending' AND seq NOT IN
                (SELECT seq FROM suggestions WHERE status != 'pending'
                 ORDER BY decided_at DESC, seq DESC LIMIT ?)""", (self._max_suggestions,))
        return self._decode(row) if row else None

    def _rule_id(self, suggestion_id: str) -> Optional[str]:
        row = self._db.execute("SELECT rule_id FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return row["rule_id"] if row else None

    def observe_outcomes(self, farm_id: str, zone_id: str, device_id: Optional[str], sample_time: datetime,
                         risk_labels: Iterable[str], data_quality_labels: Iterable[str] = ()) -> None:
        """Judge one reading against approved suggestions awaiting an outcome. Uses sample time; readings
        from before the approval, repeats, future clocks and untrusted (data-quality-flagged) readings
        never count toward recovery."""
        t = sample_time.astimezone(timezone.utc)
        labels, untrusted = set(risk_labels), bool(list(data_quality_labels))
        with self._lock, self._db:
            self._expire()
            now = datetime.fromisoformat(utc_now_iso())
            for row in self._db.execute("SELECT * FROM suggestions WHERE outcome_status='awaiting'").fetchall():
                context = json.loads(row["context"])
                snapshot = context.get("sensor_snapshot")
                own_device = snapshot.get("device_id") if isinstance(snapshot, dict) else None
                if context.get("farm_id") != farm_id or context.get("zone_id") != zone_id or (own_device and own_device != device_id):
                    continue
                evidence = json.loads(row["outcome_evidence"])
                last = evidence["last_sample_time"]
                if (t <= datetime.fromisoformat(row["decided_at"]) or (last and t <= datetime.fromisoformat(last))
                        or t > now + timedelta(seconds=60)):
                    continue
                if t > datetime.fromisoformat(row["outcome_deadline"]):
                    self._finalize_outcome(row["id"], evidence)
                    continue
                evidence["last_sample_time"] = t.isoformat()
                if untrusted:
                    evidence["untrusted_readings"] += 1
                else:
                    evidence["readings_seen"] += 1
                    evidence["clean_streak"] = 0 if labels & set(evidence["watched_labels"]) else evidence["clean_streak"] + 1
                status = row["outcome_status"]
                if evidence["clean_streak"] >= evidence["required_clean_readings"]:
                    status, evidence["resolved_sample_time"] = "confirmed", t.isoformat()
                self._db.execute("UPDATE suggestions SET outcome_status=?, outcome_evidence=? WHERE id=?",
                                 (status, json.dumps(evidence), row["id"]))

    def clear(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM suggestions")

    def close(self) -> None:
        with self._lock:
            self._db.close()


suggestion_store = SuggestionStore(db_path=settings.automation_db_path)
