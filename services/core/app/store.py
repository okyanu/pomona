"""SQLite history for full sensor packets and separate modular observations."""
import json
import hashlib
import math
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from pathlib import Path
from typing import Optional

from app.config import settings
from app.schemas import READING_FIELDS, SensorEvent, SensorObservation, CalibrationEvent, CorrectedObservation, utc_now


STORED = {"stored": True}  # validation context: rows already in the database skip the sample-time floor
PACKET_FIELD = "__packet__"  # device_fields pseudo-field: the device's live full packets (the multi-device test)


def finite_reading_fields(packet) -> list:
    """The READING_FIELDS of a packet (event or payload dict) that hold a finite number: context numbers and nulls do not count."""
    get = packet.get if isinstance(packet, dict) else (lambda name: getattr(packet, name, None))
    return [name for name in READING_FIELDS
            if isinstance(get(name), (int, float)) and not isinstance(get(name), bool) and math.isfinite(get(name))]


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
            # What the pipeline made of each stored reading (its trust verdict and vetoed fields), written by the
            # outcome feed; the sticky trusted reference is built from the readings it did not veto.
            db.execute("""CREATE TABLE IF NOT EXISTS event_trust (
                farm_id TEXT NOT NULL, zone_id TEXT NOT NULL, device_id TEXT NOT NULL, sample_time TEXT NOT NULL,
                trust_verdict TEXT NOT NULL, vetoed_fields TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY (farm_id, zone_id, device_id, sample_time))""")
            # Which fields each device has sent in a live full packet, and when (first and last `received_at`): the
            # multi-device test and each device's expected fields (docs/design/multi-device-zones.md 1.3).
            created = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='device_fields'").fetchone() is None
            db.execute("""CREATE TABLE IF NOT EXISTS device_fields (
                farm_id TEXT NOT NULL, zone_id TEXT NOT NULL, device_id TEXT NOT NULL, field TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
                PRIMARY KEY (farm_id, zone_id, device_id, field))""")
            if created:  # an existing database: fill it once from the live packets still stored
                self._backfill_device_fields(db)
            db.execute("CREATE INDEX IF NOT EXISTS sensor_events_device ON sensor_events(farm_id, zone_id, device_id, id)")
            for table in ("calibration_events", "corrected_observations"):
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, payload TEXT NOT NULL,
                    farm_id TEXT, zone_id TEXT, device_id TEXT, sensor_id TEXT, received_at TEXT)""")
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_zone ON {table}(farm_id, zone_id, id)")

    @staticmethod
    def _backfill_device_fields(db) -> None:
        """One-time scan of the stored live full packets (current-eligible, not retained) within `retention_days`."""
        cutoff = (utc_now() - timedelta(days=settings.retention_days)).isoformat()
        for row in db.execute("SELECT payload, farm_id, zone_id, device_id, received_at FROM sensor_events "
                              "WHERE current_eligible=1 AND received_at >= ? ORDER BY id", (cutoff,)).fetchall():
            payload = json.loads(row["payload"])
            if payload.get("mqtt_retained"):
                continue
            SensorEventStore._record_fields(db, row["farm_id"], row["zone_id"], row["device_id"],
                                            [*finite_reading_fields(payload), PACKET_FIELD], row["received_at"])

    @staticmethod
    def _record_fields(db, farm_id, zone_id, device_id, fields, received_at: str) -> None:
        for field in fields:
            db.execute("""INSERT INTO device_fields VALUES (?,?,?,?,?,?)
                ON CONFLICT(farm_id, zone_id, device_id, field) DO UPDATE SET
                first_seen=MIN(first_seen, excluded.first_seen), last_seen=MAX(last_seen, excluded.last_seen)""",
                       (farm_id, zone_id, device_id, field, received_at, received_at))

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self._db_path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def _add(self, event, table) -> bool:
        """Store one record; True when it is new, current-eligible and not a retained MQTT message."""
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
                if table == "sensor_events" and not event.mqtt_retained:  # a live full packet: remember what it carried
                    self._record_fields(db, event.farm_id, event.zone_id, event.device_id,
                                        [*finite_reading_fields(event), PACKET_FIELD], event.received_at.isoformat())
            db.execute(f"DELETE FROM {table} WHERE received_at < ?", (cutoff,))
            db.execute("DELETE FROM device_fields WHERE last_seen < ?", (cutoff,))
            # A busy zone cannot evict a different zone's data.
            db.execute(f"""DELETE FROM {table} WHERE farm_id=? AND zone_id=? AND id NOT IN
                (SELECT id FROM {table} WHERE farm_id=? AND zone_id=? ORDER BY id DESC LIMIT ?)""",
                       (event.farm_id, event.zone_id, event.farm_id, event.zone_id, self._max_events))
            return bool(eligible and not duplicate and not event.mqtt_retained)

    def add(self, event: SensorEvent) -> bool:
        return self._add(event, "sensor_events")

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
        return [model.model_validate(json.loads(r["payload"]), context=STORED) for r in reversed(rows)]

    @staticmethod
    def _filters(farm_id=None, zone_id=None, device_id=None):
        clauses, values = [], []
        for name, value in (("farm_id", farm_id), ("zone_id", zone_id), ("device_id", device_id)):
            if value is not None:
                clauses.append(f"{name} = ?")
                values.append(value)
        return (" WHERE " + " AND ".join(clauses) if clauses else ""), values

    def _list(self, table, model, limit, farm_id, zone_id, offset=0, device_id=None):
        if limit <= 0:
            return []
        where, values = self._filters(farm_id, zone_id, device_id)
        with self._lock, self._connect() as db:
            rows = db.execute(f"SELECT payload FROM {table}{where} ORDER BY id DESC LIMIT ? OFFSET ?",
                              (*values, limit, offset)).fetchall()
        return [model.model_validate(json.loads(r["payload"]), context=STORED) for r in reversed(rows)]

    def list_events(self, limit: int = 50, farm_id=None, zone_id=None, offset=0, device_id=None) -> list[SensorEvent]:
        return self._list("sensor_events", SensorEvent, limit, farm_id, zone_id, offset, device_id)

    def prior_events(self, event: SensorEvent, limit: int = 11) -> list[SensorEvent]:
        """Up to `limit` packets of the same stream (farm, zone, device) sampled before `event`, oldest first.

        Strictly earlier sample time; a packet with the same sample time counts only if it was stored
        before `event` (lower id). Independent of how many newer packets arrived since.
        """
        if limit <= 0:
            return []
        with self._lock, self._connect() as db:
            own = db.execute("SELECT MAX(id) FROM sensor_events WHERE farm_id=? AND zone_id=? AND device_id=? AND timestamp=?",
                             (event.farm_id, event.zone_id, event.device_id, event.timestamp.isoformat())).fetchone()[0]
            rows = db.execute("""SELECT payload FROM sensor_events WHERE farm_id=? AND zone_id=? AND device_id=?
                AND (julianday(timestamp) < julianday(?) OR (julianday(timestamp) = julianday(?) AND id < ?))
                ORDER BY julianday(timestamp) DESC, id DESC LIMIT ?""",
                              (event.farm_id, event.zone_id, event.device_id, event.timestamp.isoformat(), event.timestamp.isoformat(),
                               own if own is not None else -1, limit)).fetchall()
        return [SensorEvent.model_validate(json.loads(r["payload"]), context=STORED) for r in reversed(rows)]

    def latest_event(self, farm_id=None, zone_id=None, device_id=None) -> Optional[SensorEvent]:
        where, values = self._filters(farm_id, zone_id, device_id)
        where += (" AND " if where else " WHERE ") + "current_eligible=1 AND julianday(timestamp) <= julianday(?)"
        with self._lock, self._connect() as db:
            row = db.execute(f"SELECT payload FROM sensor_events{where} ORDER BY julianday(timestamp) DESC, id DESC LIMIT 1",
                             (*values, (utc_now() + timedelta(seconds=60)).isoformat())).fetchone()
        return SensorEvent.model_validate(json.loads(row["payload"]), context=STORED) if row else None

    def list_observations(self, limit=50, farm_id=None, zone_id=None, offset=0, device_id=None):
        return self._list("sensor_observations", SensorObservation, limit, farm_id, zone_id, offset, device_id)

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

    def device_fields_for(self, event: SensorEvent) -> Optional[list]:
        """The fields `event`'s device is expected to report, or None when its zone is single-device for this reading.

        Multi-device (docs/design/multi-device-zones.md 1.1): besides the event's own device, another device of the same
        farm and zone has sent a live full packet within `retention_days` before the event's `received_at`. A row counts
        when first_seen <= received_at and last_seen >= received_at - retention_days. The value is then the sorted list of
        the event's device fields whose rows count by the same rule (1.3).
        """
        if not settings.multi_device_zones:
            return None
        received = event.received_at or utc_now()
        until = received.isoformat()
        since = (received - timedelta(days=settings.retention_days)).isoformat()
        with self._lock, self._connect() as db:
            counting = db.execute("""SELECT device_id, field FROM device_fields WHERE farm_id=? AND zone_id=?
                AND julianday(first_seen) <= julianday(?) AND julianday(last_seen) >= julianday(?)""",
                                  (event.farm_id, event.zone_id, until, since)).fetchall()
        if not any(row["field"] == PACKET_FIELD and row["device_id"] != event.device_id for row in counting):
            return None
        return sorted(row["field"] for row in counting if row["device_id"] == event.device_id and row["field"] != PACKET_FIELD)

    def add_trust(self, event: SensorEvent, trust_verdict: str, vetoed_fields: list) -> None:
        """Record the pipeline's trust verdict for a stored reading (replaces an earlier verdict for it)."""
        created = utc_now()
        cutoff = (created - timedelta(days=settings.retention_days)).isoformat()
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO event_trust VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(farm_id, zone_id, device_id, sample_time) DO UPDATE SET
                trust_verdict=excluded.trust_verdict, vetoed_fields=excluded.vetoed_fields""",
                       (event.farm_id, event.zone_id, event.device_id, event.timestamp.isoformat(), trust_verdict,
                        json.dumps(sorted(vetoed_fields)), created.isoformat()))
            db.execute("DELETE FROM event_trust WHERE created_at < ?", (cutoff,))

    def stream_history(self, event: SensorEvent, limit: int) -> list[dict]:
        """Up to `limit` stored readings of the event's own stream (farm, zone, device) sampled before it, oldest
        first, as payload dicts plus `vetoed_fields`. A reading with no trust record counts as not vetoed."""
        with self._lock, self._connect() as db:
            rows = db.execute("""SELECT e.payload, t.vetoed_fields FROM sensor_events e
                LEFT JOIN event_trust t ON t.farm_id=e.farm_id AND t.zone_id=e.zone_id AND t.device_id=e.device_id
                    AND t.sample_time=e.timestamp
                WHERE e.farm_id=? AND e.zone_id=? AND e.device_id=? ORDER BY e.id DESC LIMIT ?""",
                              (event.farm_id, event.zone_id, event.device_id, limit)).fetchall()
        history = []
        for row in reversed(rows):
            packet = json.loads(row["payload"])
            stamp = datetime.fromisoformat(packet["timestamp"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            if stamp >= event.timestamp:
                continue
            packet["timestamp"] = stamp.astimezone(timezone.utc)  # parsed once here, not per field downstream
            packet["vetoed_fields"] = json.loads(row["vetoed_fields"]) if row["vetoed_fields"] else []
            history.append(packet)
        history.sort(key=lambda packet: packet["timestamp"])  # sample-time order, whatever order they arrived in
        return history

    def stream_calibrations(self, event: SensorEvent, limit: int = 200) -> list[dict]:
        """Calibrations recorded for the event's stream (farm, zone, device): `measurement` and `performed_at`."""
        with self._lock, self._connect() as db:
            rows = db.execute("""SELECT payload FROM calibration_events WHERE farm_id=? AND zone_id=? AND device_id=?
                ORDER BY timestamp DESC LIMIT ?""", (event.farm_id, event.zone_id, event.device_id, limit)).fetchall()
        items = [json.loads(row["payload"]) for row in rows]
        return [{"measurement": item["measurement"], "performed_at": item["performed_at"]} for item in items]

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
                "event_trust",
                "device_fields",
            ):
                db.execute(f"DELETE FROM {table}")


event_store = SensorEventStore()
