"""SQLite history for full sensor packets and separate modular observations."""
import json
import hashlib
import math
import sqlite3
import statistics
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock
from pathlib import Path
from typing import Optional

from app.config import settings
from app.schemas import READING_FIELDS, SensorEvent, SensorObservation, CalibrationEvent, CorrectedObservation, utc_now
from app.trusted_baseline import ALIASES


CLEANUP_INTERVAL = timedelta(minutes=1)  # the age-based deletes run at most this often per database and table
STORED = {"stored": True}  # validation context: rows already in the database skip the sample-time floor
PACKET_FIELD = "__packet__"  # device_fields pseudo-field: the device's live full packets (the multi-device test)
# The packet fields that are context, not readings (docs/design/multi-device-zones-slice2.md 2.1), and how many of a
# device's latest live packets give its reporting interval.
CONTEXT_FIELDS = ("crop", "growth_stage", "system_type", "weather", "zone_area_m2", "crop_kc", "npk_target")
INTERVAL_PACKETS = 6
ZONE_STALE_CAP_S = 3600  # router flags packets older than 60 min as stale_reading (global veto)


class IdConflict(ValueError):
    """A client-supplied record id is already stored with different content."""


def sample_epoch(value) -> Optional[float]:
    """Seconds since the epoch of a sample time (a datetime or ISO text; no zone means UTC): the indexed sort key."""
    try:
        if isinstance(value, str):
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp()
    except (ValueError, AttributeError, OverflowError):
        return None  # an unreadable stored time never matched a julianday() comparison either


def finite_reading_fields(packet) -> list:
    """The READING_FIELDS of a packet (event or payload dict) that hold a finite number: context numbers and nulls do not count."""
    get = packet.get if isinstance(packet, dict) else (lambda name: getattr(packet, name, None))
    return [name for name in READING_FIELDS
            if isinstance(get(name), (int, float)) and not isinstance(get(name), bool) and math.isfinite(get(name))]


_LATEST = datetime.max.replace(tzinfo=timezone.utc)  # sorts a missing first_seen last


def _parse_time(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _canonical(value) -> str:
    """A context value as comparable text (weather and npk_target compare as JSON with sorted keys)."""
    return json.dumps(value, sort_keys=True)


class SensorEventStore:
    def __init__(self, max_events: Optional[int] = None, db_path: Optional[Path] = None) -> None:
        self._max_events = max_events if max_events is not None else settings.max_events
        self._lock = Lock()
        self._db_path = Path(db_path or settings.db_path)
        self._cleaned: dict = {}  # (database file, table) -> when the age-based deletes last ran
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._enable_wal()
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
                for name, definition in (("dedupe_key", "TEXT"), ("current_eligible", "INTEGER NOT NULL DEFAULT 1"),
                                         ("sample_epoch", "REAL")):
                    if name not in columns:
                        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
                # Fill the sample-time sort key of rows that lack it (an old database, or a start-up that crashed after
                # ALTER TABLE): keyed on the data, not on the column being new. The partial index makes "no rows left"
                # one cheap lookup; a stored time nobody can parse stays NULL and is looked at once per start.
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_epoch_missing ON {table}(id) WHERE sample_epoch IS NULL")
                self._backfill_sample_epoch(db, table)
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
                data_quality_labels TEXT, safe_next_checks TEXT,
                PRIMARY KEY (farm_id, zone_id, device_id, sample_time))""")
            # The sensor-check result the verdict came from (JSON lists), so the zone snapshot can carry it
            # (docs/design/multi-device-zones-slice2.md 2.2). A table from before keeps NULL in its old rows.
            trust_columns = {r[1] for r in db.execute("PRAGMA table_info(event_trust)")}
            # `pair_fields`: the fields the pair check flagged on that reading (JSON list, NULL when none)
            # (docs/design/slow-drift-pair-check.md 4b).
            for column in ("data_quality_labels", "safe_next_checks", "pair_fields"):
                if column not in trust_columns:
                    db.execute(f"ALTER TABLE event_trust ADD COLUMN {column} TEXT")
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
            # Latest / prior reading by sample time without scanning the zone.
            db.execute("CREATE INDEX IF NOT EXISTS sensor_events_sample_device ON sensor_events(farm_id, zone_id, device_id, sample_epoch, id)")
            db.execute("CREATE INDEX IF NOT EXISTS sensor_events_sample_zone ON sensor_events(farm_id, zone_id, sample_epoch, id)")
            for table in ("calibration_events", "corrected_observations"):
                db.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, payload TEXT NOT NULL,
                    farm_id TEXT, zone_id TEXT, device_id TEXT, sensor_id TEXT, received_at TEXT)""")
                db.execute(f"CREATE INDEX IF NOT EXISTS {table}_zone ON {table}(farm_id, zone_id, id)")

    @staticmethod
    def _backfill_sample_epoch(db, table: str, batch: int = 5000) -> None:
        """Set `sample_epoch` where it is NULL, `batch` rows per commit, one pass (a moving id cursor) per call."""
        cursor = 0
        while True:
            rows = db.execute(f"SELECT id, timestamp FROM {table} WHERE sample_epoch IS NULL AND id > ? ORDER BY id LIMIT ?",
                              (cursor, batch)).fetchall()
            if not rows:
                return
            cursor = rows[-1]["id"]
            db.executemany(f"UPDATE {table} SET sample_epoch=? WHERE id=?",
                           [(epoch, r["id"]) for r in rows if (epoch := sample_epoch(r["timestamp"])) is not None])
            db.commit()

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

    def _enable_wal(self) -> None:
        """Write-ahead log (kept in the database file): the dashboard's reads no longer wait for MQTT ingest writes."""
        db = sqlite3.connect(self._db_path, timeout=10)
        try:
            db.execute("PRAGMA journal_mode=WAL")
        finally:
            db.close()

    @contextmanager
    def _connect(self):
        db = sqlite3.connect(self._db_path, timeout=10)
        db.execute("PRAGMA busy_timeout=10000")
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
            clock_valid = event.timestamp <= utc_now() + timedelta(seconds=settings.future_slack_s)
            eligible = clock_valid and (not cursor or event.sequence > cursor["sequence"])
            duplicate = db.execute(f"SELECT id,payload FROM {table} WHERE dedupe_key=?", (dedupe_key,)).fetchone()
            promoted = bool(duplicate and not event.mqtt_retained and clock_valid
                            and json.loads(duplicate["payload"]).get("mqtt_retained")
                            and (not cursor or event.sequence == cursor["sequence"]))
            if promoted:
                db.execute(f"UPDATE {table} SET payload=?,received_at=? WHERE id=?", (payload, event.received_at.isoformat(), duplicate["id"]))
            if not duplicate:
                db.execute(f"INSERT INTO {table} (timestamp,payload,farm_id,zone_id,device_id,received_at,dedupe_key,current_eligible,sample_epoch) VALUES (?,?,?,?,?,?,?,?,?)",
                           (event.timestamp.isoformat(), payload, event.farm_id, event.zone_id, event.device_id,
                            event.received_at.isoformat(), dedupe_key, int(eligible), sample_epoch(event.timestamp)))
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
            self._cleanup(db, table, cutoff)
            # A busy zone cannot evict a different zone's data: drop the zone's rows beyond its newest `max_events`.
            db.execute(f"""DELETE FROM {table} WHERE farm_id=? AND zone_id=? AND id <=
                (SELECT id FROM {table} WHERE farm_id=? AND zone_id=? ORDER BY id DESC LIMIT 1 OFFSET ?)""",
                       (event.farm_id, event.zone_id, event.farm_id, event.zone_id, self._max_events))
            return bool(eligible and not duplicate and not event.mqtt_retained)

    def _cleanup(self, db, table: str, cutoff: str) -> None:
        """The age-based deletes, at most once a minute per database and table (the first insert after start-up runs them)."""
        now, key = utc_now(), (str(self._db_path), table)
        last = self._cleaned.get(key)
        if last is not None and timedelta(0) <= now - last < CLEANUP_INTERVAL:
            return
        self._cleaned[key] = now
        db.execute(f"DELETE FROM {table} WHERE received_at < ?", (cutoff,))
        db.execute("DELETE FROM device_fields WHERE last_seen < ?", (cutoff,))

    def add(self, event: SensorEvent) -> bool:
        return self._add(event, "sensor_events")

    def add_observation(self, observation: SensorObservation) -> None:
        self._add(observation, "sensor_observations")

    @staticmethod
    def _stored_repeat(db, table: str, model, record) -> Optional[object]:
        """The stored row when `record` repeats its client-supplied id with the same content (a safe retry), else None.

        Raises IdConflict when the id is stored with different content. Core's own fields (`received_at`) do not count."""
        row = db.execute(f"SELECT payload FROM {table} WHERE id=?", (record.id,)).fetchone()
        if row is None:
            return None
        stored = json.loads(row["payload"])
        if {k: v for k, v in stored.items() if k != "received_at"} != record.model_dump(mode="json", exclude={"received_at"}):
            raise IdConflict(f"id {record.id} is already stored with different content")
        return model.model_validate(stored, context=STORED)

    def add_calibration(self, event: CalibrationEvent) -> CalibrationEvent:
        import uuid
        supplied = event.id is not None
        event.id = event.id or uuid.uuid4().hex
        event.received_at = utc_now()
        payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
        with self._lock, self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            repeat = self._stored_repeat(db, "calibration_events", CalibrationEvent, event) if supplied else None
            if repeat is not None:
                return repeat
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
            db.execute("BEGIN IMMEDIATE")
            if observation.id is not None:
                repeat = self._stored_repeat(db, "corrected_observations", CorrectedObservation, observation)
                if repeat is not None:
                    return repeat
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
            at = sample_epoch(event.timestamp)
            own = db.execute("SELECT MAX(id) FROM sensor_events WHERE farm_id=? AND zone_id=? AND device_id=? AND sample_epoch=?",
                             (event.farm_id, event.zone_id, event.device_id, at)).fetchone()[0]
            rows = db.execute("""SELECT payload FROM sensor_events WHERE farm_id=? AND zone_id=? AND device_id=?
                AND (sample_epoch, id) < (?, ?) ORDER BY sample_epoch DESC, id DESC LIMIT ?""",
                              (event.farm_id, event.zone_id, event.device_id, at, own if own is not None else -1, limit)).fetchall()
        return [SensorEvent.model_validate(json.loads(r["payload"]), context=STORED) for r in reversed(rows)]

    def latest_event(self, farm_id=None, zone_id=None, device_id=None) -> Optional[SensorEvent]:
        where, values = self._filters(farm_id, zone_id, device_id)
        where += (" AND " if where else " WHERE ") + "current_eligible=1 AND sample_epoch <= ?"
        with self._lock, self._connect() as db:
            row = db.execute(f"SELECT payload FROM sensor_events{where} ORDER BY sample_epoch DESC, id DESC LIMIT 1",
                             (*values, (utc_now() + timedelta(seconds=settings.future_slack_s)).timestamp())).fetchone()
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
                            "sample_stale": sample_age > 3600 or sample_age < -settings.future_slack_s})
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

    def zone_pair_devices(self, event: SensorEvent, fields) -> list:
        """The other devices of the event's farm and zone that have carried any of `fields`, sorted: the pair check's
        partners. The same time rule as `device_fields_for` (first_seen <= the event's received_at, last_seen >= it
        minus the retention days). Empty when the multi-device switch is off."""
        fields = list(fields)
        if not settings.multi_device_zones or not fields:
            return []
        received = event.received_at or utc_now()
        until = received.isoformat()
        since = (received - timedelta(days=settings.retention_days)).isoformat()
        marks = ",".join("?" * len(fields))
        with self._lock, self._connect() as db:
            rows = db.execute(f"""SELECT DISTINCT device_id FROM device_fields WHERE farm_id=? AND zone_id=?
                AND device_id != ? AND field IN ({marks})
                AND julianday(first_seen) <= julianday(?) AND julianday(last_seen) >= julianday(?)""",
                              (event.farm_id, event.zone_id, event.device_id, *fields, until, since)).fetchall()
        return sorted(row["device_id"] for row in rows)

    def zone_partner_history(self, event: SensorEvent, devices, field_names, since: datetime) -> list[dict]:
        """Judged readings (an `event_trust` row exists) of the given partner devices of the event's zone with sample
        time in [`since`, the event's), as small dicts: `device_id`, `timestamp` (aware UTC), the `field_names` they
        carry and `vetoed_fields`. Oldest first per device; of one sample time the newest stored payload comes last.
        At most `trust_baseline_scan_limit` rows per device (the newest ones)."""
        start, end = sample_epoch(since), sample_epoch(event.timestamp)
        names = list(field_names)
        out: list[dict] = []
        if start is None or end is None:
            return out
        with self._lock, self._connect() as db:
            for device in devices:
                rows = db.execute("""SELECT e.payload, t.vetoed_fields FROM sensor_events e
                    JOIN event_trust t ON t.farm_id=e.farm_id AND t.zone_id=e.zone_id AND t.device_id=e.device_id
                        AND t.sample_time=e.timestamp
                    WHERE e.farm_id=? AND e.zone_id=? AND e.device_id=? AND e.sample_epoch >= ? AND e.sample_epoch < ?
                    ORDER BY e.sample_epoch DESC, e.id DESC LIMIT ?""",
                                  (event.farm_id, event.zone_id, device, start, end,
                                   settings.trust_baseline_scan_limit)).fetchall()
                for row in reversed(rows):
                    packet = json.loads(row["payload"])
                    if not any(isinstance(packet.get(name), (int, float)) and not isinstance(packet.get(name), bool)
                               for name in names):
                        continue  # carries none of the fields
                    item = {name: packet[name] for name in names if name in packet}
                    item["device_id"] = device
                    item["timestamp"] = _parse_time(packet["timestamp"])
                    item["vetoed_fields"] = json.loads(row["vetoed_fields"]) if row["vetoed_fields"] else []
                    out.append(item)
        return out

    def zone_calibrations(self, farm_id: str, zone_id: str, limit: int = 200) -> list[dict]:
        """The zone's newest `limit` calibrations on any device: `measurement` and `performed_at` (the measurement is only
        inside the JSON payload, so the caller picks by it and compares the parsed times)."""
        with self._lock, self._connect() as db:
            rows = db.execute("SELECT payload FROM calibration_events WHERE farm_id=? AND zone_id=? "
                              "ORDER BY timestamp DESC LIMIT ?", (farm_id, zone_id, limit)).fetchall()
        items = [json.loads(row["payload"]) for row in rows]
        return [{"measurement": item["measurement"], "performed_at": item["performed_at"]} for item in items]

    def add_trust(self, event: SensorEvent, trust_verdict: str, vetoed_fields: list,
                  labels: Optional[list] = None, checks: Optional[list] = None,
                  pair_fields: Optional[list] = None) -> None:
        """Record the pipeline's trust verdict, and the data-quality labels and safe next checks behind it, for a stored
        reading (replaces an earlier verdict for it). `labels` / `checks` None store NULL: not recorded.
        `pair_fields` are the fields the pair check flagged on this reading (docs/design/slow-drift-pair-check.md 4b);
        None or empty store NULL."""
        created = utc_now()
        cutoff = (created - timedelta(days=settings.retention_days)).isoformat()
        with self._lock, self._connect() as db:
            db.execute("""INSERT INTO event_trust (farm_id, zone_id, device_id, sample_time, trust_verdict, vetoed_fields,
                created_at, data_quality_labels, safe_next_checks, pair_fields) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(farm_id, zone_id, device_id, sample_time) DO UPDATE SET
                trust_verdict=excluded.trust_verdict, vetoed_fields=excluded.vetoed_fields,
                data_quality_labels=excluded.data_quality_labels, safe_next_checks=excluded.safe_next_checks,
                pair_fields=excluded.pair_fields""",
                       (event.farm_id, event.zone_id, event.device_id, event.timestamp.isoformat(), trust_verdict,
                        json.dumps(sorted(vetoed_fields)), created.isoformat(),
                        None if labels is None else json.dumps(list(labels)),
                        None if checks is None else json.dumps(list(checks)),
                        json.dumps(sorted(pair_fields)) if pair_fields else None))
            db.execute("DELETE FROM event_trust WHERE created_at < ?", (cutoff,))

    def zone_snapshot(self, farm_id: str, zone_id: str, stale_after_s: int = 0) -> dict:
        """One view of a multi-device zone (docs/design/multi-device-zones-slice2.md 2.1): each reading field from one
        device, each device's own sensor-check result, and the zone's context. `{"multi_device": False}` when the zone
        is not multi-device for its latest event (the slice-1 test), or has no event."""
        latest_in_zone = self.latest_event(farm_id, zone_id)
        if latest_in_zone is None or self.device_fields_for(latest_in_zone) is None:
            return {"multi_device": False}
        now = utc_now()
        retention = timedelta(days=settings.retention_days)
        with self._lock, self._connect() as db:
            field_rows = db.execute("SELECT device_id, field, first_seen, last_seen FROM device_fields WHERE farm_id=? AND zone_id=?",
                                    (farm_id, zone_id)).fetchall()
        first_seen = {(r["device_id"], r["field"]): _parse_time(r["first_seen"]) for r in field_rows}
        last_seen = {(r["device_id"], r["field"]): _parse_time(r["last_seen"]) for r in field_rows}
        device_ids = sorted({r["device_id"] for r in field_rows
                             if r["field"] == PACKET_FIELD and last_seen[(r["device_id"], PACKET_FIELD)] >= now - retention})
        latest = {}
        for device_id in device_ids:
            event = self.latest_event(farm_id, zone_id, device_id)
            if event is not None:
                latest[device_id] = event
        devices = []
        for device_id, event in latest.items():
            dump = event.model_dump(mode="json", exclude={"source"})
            sampled = event.timestamp
            age_s = max(0.0, (now - sampled).total_seconds())
            interval_s = self._interval_s(farm_id, zone_id, device_id)
            if not stale_after_s:
                limit_s = 0
            else:
                limit_s = min(ZONE_STALE_CAP_S, max(stale_after_s, 3 * interval_s)) if interval_s is not None else min(ZONE_STALE_CAP_S, stale_after_s)
            received = event.received_at or now
            expected = sorted(f for (d, f), seen in first_seen.items()
                              if d == device_id and f != PACKET_FIELD and seen <= received
                              and last_seen[(d, f)] >= received - retention)
            devices.append({
                "device_id": device_id, "event": dump, "sample_time": dump["timestamp"], "received_at": dump["received_at"],
                "age_s": age_s, "interval_s": interval_s, "stale_limit_s": limit_s,
                "stale": limit_s > 0 and age_s > limit_s, "device_fields": expected, "supplied": [],
                "trust": self._device_trust(farm_id, zone_id, device_id, event),
                "_sampled": sampled, "_present": finite_reading_fields(event)})

        fields = {}
        live = [d for d in devices if not d["stale"]]
        for name in READING_FIELDS:
            candidates = sorted((d for d in live if name in d["_present"]),
                                key=lambda d: (first_seen.get((d["device_id"], name), _LATEST), d["device_id"]))
            if not candidates:
                continue

            def vetoes(device):
                trust = device["trust"]
                return trust["status"] == "judged" and name in trust["vetoed_fields"]

            # Probes disagree (docs/design/slow-drift-pair-check.md 4b): a non-stale device carrying the field (or its
            # moisture alias) whose latest judged row lists it in `pair_fields` marks the field. The value stays the
            # first candidate's even if that probe took the flag (no switching to the other one); the dashboard hands
            # the field to the router as vetoed, so no advice uses either value.
            names = {name, ALIASES.get(name)}
            disagree = any(d["trust"]["status"] == "judged" and names & set(d["trust"].get("pair_fields") or ())
                           and names & set(d["_present"]) for d in live)
            chosen = candidates[0] if disagree else next((d for d in candidates if not vetoes(d)), candidates[0])
            fields[name] = {
                "value": getattr(latest[chosen["device_id"]], name), "device_id": chosen["device_id"],
                "sample_time": chosen["sample_time"], "age_s": chosen["age_s"],
                "others": [{"device_id": d["device_id"], "value": getattr(latest[d["device_id"]], name),
                            "sample_time": d["sample_time"], "vetoed": vetoes(d)}
                           for d in candidates if d is not chosen]}
            if disagree:
                fields[name]["disagree"] = True
        for device in devices:
            device["supplied"] = [name for name, field in fields.items() if field["device_id"] == device["device_id"]]

        context, context_source, conflicts = self._zone_context(devices, latest)
        supplying = [d for d in devices if d["supplied"]]
        sensor = None
        if fields:
            newest = max(supplying, key=lambda d: d["_sampled"])
            sensor = {"farm_id": farm_id, "zone_id": zone_id, **context, **{n: f["value"] for n, f in fields.items()},
                      "timestamp": newest["sample_time"]}
        sources = {}
        for name in READING_FIELDS:
            if name in fields:
                sources[name] = [fields[name]["device_id"]]
            elif any(name in d["device_fields"] for d in devices):
                sources[name] = [d["device_id"] for d in devices if name in d["device_fields"]]
        for device in devices:
            device.pop("_sampled"), device.pop("_present")
        return {"multi_device": True, "farm_id": farm_id, "zone_id": zone_id, "stale_after_s": stale_after_s,
                "devices": devices, "fields": fields, "sensor": sensor, "sources": sources,
                "zone_device_fields": sorted({f for d in devices for f in d["device_fields"]}),
                "context": context, "context_source": context_source, "context_conflicts": conflicts,
                "newest_age_s": min((d["age_s"] for d in devices), default=None)}

    def _interval_s(self, farm_id, zone_id, device_id) -> Optional[float]:
        """The median gap between the sample times of the device's last `INTERVAL_PACKETS` live packets; None below 2."""
        with self._lock, self._connect() as db:
            rows = db.execute("""SELECT payload FROM sensor_events WHERE farm_id=? AND zone_id=? AND device_id=? AND current_eligible=1
                ORDER BY julianday(timestamp) DESC, id DESC LIMIT ?""", (farm_id, zone_id, device_id, INTERVAL_PACKETS * 2)).fetchall()
        times = []
        for row in rows:
            payload = json.loads(row["payload"])
            if not payload.get("mqtt_retained"):
                times.append(_parse_time(payload["timestamp"]))
        times = sorted(set(times[:INTERVAL_PACKETS]))
        if len(times) < 2:
            return None
        return statistics.median((b - a).total_seconds() for a, b in zip(times, times[1:]))

    def _device_trust(self, farm_id, zone_id, device_id, event: SensorEvent) -> dict:
        """The event_trust row of the device's latest packet as `judged`, or `pending` when Core has recorded none."""
        with self._lock, self._connect() as db:
            row = db.execute("""SELECT trust_verdict, vetoed_fields, data_quality_labels, safe_next_checks, pair_fields FROM event_trust
                WHERE farm_id=? AND zone_id=? AND device_id=? AND sample_time=?""",
                             (farm_id, zone_id, device_id, event.timestamp.isoformat())).fetchone()
        if row is None:
            return {"status": "pending"}
        def listed(text):
            return json.loads(text) if text is not None else None
        judged = {"status": "judged", "trust_verdict": row["trust_verdict"], "vetoed_fields": listed(row["vetoed_fields"]) or [],
                  "data_quality_labels": listed(row["data_quality_labels"]), "safe_next_checks": listed(row["safe_next_checks"])}
        if row["pair_fields"]:  # only when the pair check flagged a field (4b), so every other output is unchanged
            judged["pair_fields"] = listed(row["pair_fields"])
        return judged

    @staticmethod
    def _zone_context(devices: list, latest: dict):
        """The zone's context fields by one rule (2.1): from the non-stale devices (every device when none is non-stale),
        null dropped, the schema default dropped when any candidate differs, then the newest sample time wins."""
        pool = [d for d in devices if not d["stale"]] or devices
        context, source, conflicts = {}, {}, []
        for name in CONTEXT_FIELDS:
            default = SensorEvent.model_fields[name].default
            found = []
            for device in pool:
                value = device["event"].get(name)
                if value is not None:
                    found.append((device, value))
            if any(_canonical(value) != _canonical(default) for _, value in found):
                found = [(d, v) for d, v in found if _canonical(v) != _canonical(default)]
            if not found:
                continue
            winner = min(found, key=lambda item: (-item[0]["_sampled"].timestamp(), item[0]["device_id"]))
            context[name], source[name] = winner[1], winner[0]["device_id"]
            if len({_canonical(v) for _, v in found}) > 1:
                conflicts.append(name)
        return context, source, sorted(conflicts)

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
        self._cleaned.clear()


event_store = SensorEventStore()
