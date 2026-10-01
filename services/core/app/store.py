"""SQLite history for full sensor packets and separate modular observations."""
import json
import hashlib
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from pathlib import Path
from typing import Optional

from app.config import settings
from app.schemas import SensorEvent, SensorObservation, CalibrationEvent, CorrectedObservation, utc_now


class SensorEventStore:
    def __init__(self, max_events: Optional[int] = None, db_path: Optional[Path] = None) -> None:
        self._max_events = max_events if max_events is not None else settings.max_events
        self._lock = Lock()
        self._db_path = Path(db_path or settings.db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            for table in ("sensor_events", "sensor_observations"):
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL, farm_id TEXT, zone_id TEXT, device_id TEXT, received_at TEXT)""")
                columns = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
                missing = {"farm_id", "zone_id", "device_id", "received_at"} - columns
                for column in sorted(missing):
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
                if missing:
                    for row in db.execute(f"SELECT id, payload FROM {table}").fetchall():
                        payload = json.loads(row["payload"])
                        db.execute(f"UPDATE {table} SET farm_id=?, zone_id=?, device_id=?, received_at=? WHERE id=?",
                                   (payload["farm_id"], payload["zone_id"], payload["device_id"], payload.get("received_at"), row["id"]))
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_zone ON {table}(farm_id, zone_id, id)")
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_receipt ON {table}(received_at)")
                for name, definition in (("dedupe_key", "TEXT"), ("current_eligible", "INTEGER NOT NULL DEFAULT 1")):
                    if name not in columns:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                db.execute(f"CREATE UNIQUE INDEX IF NOT EXISTS {table}_dedupe ON {table}(dedupe_key)")
            db.execute("""CREATE TABLE IF NOT EXISTS stream_cursors (
                stream TEXT PRIMARY KEY, sequence INTEGER NOT NULL)""")
            db.execute("""CREATE TABLE IF NOT EXISTS device_presence (
                farm_id TEXT, zone_id TEXT, device_id TEXT, payload TEXT NOT NULL,
                PRIMARY KEY(farm_id, zone_id, device_id))""")
            for table in ("calibration_events", "corrected_observations"):
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, payload TEXT NOT NULL,
                    farm_id TEXT, zone_id TEXT, device_id TEXT, sensor_id TEXT, received_at TEXT)""")
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_zone ON {table}(farm_id, zone_id, id)")

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self._db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _add(self, event, table):
        # Table names are internal constants, never API input.
        event.received_at = utc_now()
        payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
        cutoff = (utc_now() - timedelta(days=settings.retention_days)).isoformat()
        content = event.model_dump(mode="json", exclude={"received_at", "mqtt_retained", "source"})
        stream = [table, event.farm_id, event.zone_id, event.device_id,
                  getattr(event, "sensor_id", None), getattr(event, "measurement", None), event.boot_id]
        sequenced = event.boot_id is not None and event.sequence is not None
        identity = [stream, event.sequence] if sequenced else [table, content]
        dedupe_key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        with self._lock, self._connect() as db:
            # Serialize deduplication and cursor updates across processes as well as threads.
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("SELECT sequence FROM stream_cursors WHERE stream=?", (json.dumps(stream),)).fetchone() if sequenced else None
            clock_valid = event.timestamp <= utc_now() + timedelta(seconds=60)
            eligible = clock_valid and (not cursor or event.sequence > cursor["sequence"])
            duplicate = db.execute(f"SELECT id,payload FROM {table} WHERE dedupe_key=?", (dedupe_key,)).fetchone()
            promoted = bool(duplicate and not event.mqtt_retained and clock_valid
                            and json.loads(duplicate["payload"]).get("mqtt_retained")
                            and (not cursor or event.sequence == cursor["sequence"]))
            if promoted:
                db.execute(f"UPDATE {table} SET payload=?,received_at=? WHERE id=?", (payload, event.received_at.isoformat(), duplicate["id"]))
            if not duplicate:
                db.execute(f"INSERT INTO {table} (timestamp,payload,farm_id,zone_id,device_id,received_at,dedupe_key,current_eligible) VALUES (?,?,?,?,?,?,?,?)",
                           (event.timestamp.isoformat(), payload, event.farm_id, event.zone_id, event.device_id,
                            event.received_at.isoformat(), dedupe_key, int(eligible)))
                if sequenced and eligible:
                    db.execute("INSERT INTO stream_cursors VALUES (?,?) ON CONFLICT(stream) DO UPDATE SET sequence=excluded.sequence",
                               (json.dumps(stream), event.sequence))
            # Retained state may be displayed, but never proves live availability.
            if (eligible and not duplicate) or promoted:
                prior = db.execute("SELECT payload FROM device_presence WHERE farm_id=? AND zone_id=? AND device_id=?",
                                   (event.farm_id, event.zone_id, event.device_id)).fetchone()
                data = json.loads(payload)
                last_live = None
                if prior:
                    previous = json.loads(prior["payload"])
                    last_live = previous.get("last_live_received_at", previous.get("received_at") if not previous.get("mqtt_retained") else None)
                    prior_time = datetime.fromisoformat(previous["timestamp"].replace("Z", "+00:00"))
                    prior_time = prior_time.replace(tzinfo=prior_time.tzinfo or timezone.utc)
                    if prior_time > event.timestamp.astimezone(timezone.utc):
                        data = previous
                        data["received_at"] = event.received_at.isoformat()
                data["last_live_received_at"] = last_live if event.mqtt_retained else event.received_at.isoformat()
                db.execute("""INSERT INTO device_presence VALUES (?,?,?,?)
                    ON CONFLICT(farm_id,zone_id,device_id) DO UPDATE SET payload=excluded.payload""",
                           (event.farm_id, event.zone_id, event.device_id, json.dumps(data)))
            db.execute(f"DELETE FROM {table} WHERE received_at < ?", (cutoff,))
            # A busy zone cannot evict a different zone's data.
            db.execute(f"""DELETE FROM {table} WHERE farm_id=? AND zone_id=? AND id NOT IN
                (SELECT id FROM {table} WHERE farm_id=? AND zone_id=? ORDER BY id DESC LIMIT ?)""",
                       (event.farm_id, event.zone_id, event.farm_id, event.zone_id, self._max_events))

    def add(self, event: SensorEvent) -> None:
        self._add(event, "sensor_events")

    def add_observation(self, observation: SensorObservation) -> None:
        self._add(observation, "sensor_observations")

    def add_calibration(self, event: CalibrationEvent) -> CalibrationEvent:
        import uuid
        event.id = event.id or uuid.uuid4().hex
        event.received_at = utc_now()
        payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
        with self._lock, self._connect() as db:
            db.execute(
                """INSERT INTO calibration_events
                   (id, timestamp, payload, farm_id, zone_id, device_id, sensor_id, received_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    event.id,
                    event.performed_at.isoformat(),
                    payload,
                    event.farm_id,
                    event.zone_id,
                    event.device_id,
                    event.sensor_id,
                    event.received_at.isoformat(),
                ),
            )
        return event

    def add_corrected_observation(self, observation: CorrectedObservation) -> CorrectedObservation:
        import uuid
        with self._lock, self._connect() as db:
            exists = db.execute(
                "SELECT 1 FROM calibration_events WHERE id=?",
                (observation.calibration_event_id,),
            ).fetchone()
            if not exists:
                raise ValueError("calibration_event_id does not reference a stored calibration")
            observation.id = observation.id or uuid.uuid4().hex
            observation.received_at = utc_now()
            payload = json.dumps(observation.model_dump(mode="json"), separators=(",", ":"))
            db.execute(
                """INSERT INTO corrected_observations
                   (id, timestamp, payload, farm_id, zone_id, device_id, sensor_id, received_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    observation.id,
                    observation.timestamp.isoformat(),
                    payload,
                    observation.farm_id,
                    observation.zone_id,
                    observation.device_id,
                    observation.sensor_id,
                    observation.received_at.isoformat(),
                ),
            )
        return observation

    def list_calibrations(self, limit=50, farm_id=None, zone_id=None, offset=0):
        return self._list_named("calibration_events", CalibrationEvent, limit, farm_id, zone_id, offset)

    def list_corrected(self, limit=50, farm_id=None, zone_id=None, offset=0):
        return self._list_named("corrected_observations", CorrectedObservation, limit, farm_id, zone_id, offset)

    def recalibrate_ranking(self, farm_id=None, zone_id=None, budget: int = 3, quality_labels=None):
        """Deterministic Hurst-style budget hint: SQI severity, then age / never-calibrated."""
        quality_labels = quality_labels or {}
        boost_labels = {
            "baseline_drift_possible",
            "sensor_drift_possible",
            "stuck_value",
            "flatline_possible",
            "noisy_signal_possible",
            "impossible_ph",
            "impossible_ec",
            "conflicting_readings",
        }
        devices = self.devices(farm_id=farm_id, zone_id=zone_id)
        calibrations = self.list_calibrations(limit=500, farm_id=farm_id, zone_id=zone_id)
        latest_by_sensor = {}
        for item in calibrations:
            key = (item.farm_id, item.zone_id, item.device_id, item.sensor_id, item.measurement)
            latest_by_sensor[key] = item.performed_at
        ranked = []
        for device in devices:
            sensor_id = device.get("sensor_id") or device.get("device_id")
            measurement = "ph"
            key = (device["farm_id"], device["zone_id"], device["device_id"], sensor_id, measurement)
            last = latest_by_sensor.get(key)
            age_hours = (
                float("inf")
                if last is None
                else (utc_now() - last.astimezone(timezone.utc)).total_seconds() / 3600.0
            )
            labels = list(quality_labels.get(device["device_id"]) or quality_labels.get(sensor_id) or [])
            sqi_boost = sum(1 for label in labels if label in boost_labels)
            severity = (
                3 + sqi_boost
                if sqi_boost
                else 2 if device.get("sample_stale") else 1 if device.get("availability") == "silent" else 0
            )
            ranked.append(
                {
                    "device_id": device["device_id"],
                    "farm_id": device["farm_id"],
                    "zone_id": device["zone_id"],
                    "sensor_id": sensor_id,
                    "measurement": measurement,
                    "last_calibrated_at": last.isoformat() if last else None,
                    "age_hours": None if age_hours == float("inf") else round(age_hours, 2),
                    "severity": severity,
                    "quality_labels": labels,
                    "reason": (
                        "sqi_warn_fault"
                        if sqi_boost
                        else "never_calibrated"
                        if last is None
                        else "age_and_health"
                    ),
                }
            )
        ranked.sort(key=lambda row: (-row["severity"], -(row["age_hours"] or 1e12)))
        return {"budget": budget, "suggestions": ranked[: max(0, budget)], "total_candidates": len(ranked)}

    def _list_named(self, table, model, limit, farm_id, zone_id, offset=0):
        if limit <= 0:
            return []
        where, values = self._filters(farm_id, zone_id)
        with self._lock, self._connect() as db:
            rows = db.execute(
                f"SELECT payload FROM {table}{where} ORDER BY timestamp DESC, id DESC LIMIT ? OFFSET ?",
                (*values, limit, offset),
            ).fetchall()
        return [model.model_validate(json.loads(r["payload"])) for r in reversed(rows)]

    @staticmethod
    def _filters(farm_id=None, zone_id=None):
        clauses, values = [], []
        for name, value in (("farm_id", farm_id), ("zone_id", zone_id)):
            if value is not None:
                clauses.append(f"{name} = ?")
                values.append(value)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), values

    def _list(self, table, model, limit, farm_id, zone_id, offset=0):
        if limit <= 0:
            return []
        where, values = self._filters(farm_id, zone_id)
        with self._lock, self._connect() as db:
            rows = db.execute(f"SELECT payload FROM {table}{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                              (*values, limit, offset)).fetchall()
        return [model.model_validate(json.loads(r["payload"])) for r in reversed(rows)]

    def list_events(self, limit: int = 50, farm_id=None, zone_id=None, offset=0) -> list[SensorEvent]:
        return self._list("sensor_events", SensorEvent, limit, farm_id, zone_id, offset)

    def latest_event(self, farm_id=None, zone_id=None) -> Optional[SensorEvent]:
        where, values = self._filters(farm_id, zone_id)
        where += (" AND " if where else " WHERE ") + "current_eligible=1 AND julianday(timestamp) <= julianday(?)"
        with self._lock, self._connect() as db:
            row = db.execute(f"SELECT payload FROM sensor_events{where} ORDER BY julianday(timestamp) DESC, id DESC LIMIT 1",
                             (*values, (utc_now() + timedelta(seconds=60)).isoformat())).fetchone()
        return SensorEvent.model_validate(json.loads(row["payload"])) if row else None

    def list_observations(self, limit=50, farm_id=None, zone_id=None, offset=0):
        return self._list("sensor_observations", SensorObservation, limit, farm_id, zone_id, offset)

    def devices(self, farm_id=None, zone_id=None):
        where, values = self._filters(farm_id, zone_id)
        with self._lock, self._connect() as db:
            rows = db.execute(f"SELECT payload FROM device_presence{where} ORDER BY farm_id,zone_id,device_id", values).fetchall()
        results = []
        now = utc_now()
        for row in rows:
            data = json.loads(row["payload"])
            last_live = data.get("last_live_received_at", data["received_at"] if not data.get("mqtt_retained") else None)
            received = datetime.fromisoformat(last_live.replace("Z", "+00:00")) if last_live else None
            sampled = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
            if sampled.tzinfo is None:
                sampled = sampled.replace(tzinfo=timezone.utc)
            age = (now - received).total_seconds() if received else float("inf")
            sample_age = (now - sampled).total_seconds()
            results.append({key: data.get(key) for key in ("device_id", "farm_id", "zone_id", "firmware", "sensor_id", "quality", "calibration_timestamp")} |
                           {"last_seen": last_live, "sampled_at": data["timestamp"],
                            "availability": "unknown" if received is None else ("recent" if age <= settings.device_timeout_seconds else "silent"),
                            "sample_stale": sample_age > 3600 or sample_age < -60})
        return results

    def count(self) -> int:
        with self._lock, self._connect() as db:
            return int(db.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0])

    def clear(self) -> None:
        with self._lock, self._connect() as db:
            for table in (
                "sensor_events",
                "sensor_observations",
                "device_presence",
                "stream_cursors",
                "calibration_events",
                "corrected_observations",
            ):
                db.execute(f"DELETE FROM {table}")


event_store = SensorEventStore()
