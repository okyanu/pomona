"""The store stays fast as a zone grows: sample-time index, bounded retention deletes, timed cleanup, write-ahead log."""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.store as store_module
from app.config import settings
from app.schemas import SensorEvent, SensorObservation
from app.store import CLEANUP_INTERVAL, SensorEventStore, event_store, sample_epoch

DAY = timedelta(days=1)
T0 = datetime.now(timezone.utc).replace(microsecond=0) - 20 * DAY


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(store_module, "utc_now", value)
    return value


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "test.db")
    SensorEventStore(db_path=event_store._db_path)


def packet(at, device="d1", zone="a", **updates):
    return SensorEvent.model_validate({"device_id": device, "farm_id": "farm", "zone_id": zone, "timestamp": at.isoformat(),
                                       "air_temperature_c": 24.0, "humidity_pct": 60.0, **updates})


def rows(table="sensor_events", where="1"):
    with event_store._connect() as db:
        return [tuple(r) for r in db.execute(f"SELECT id, device_id, zone_id, sample_epoch FROM {table} WHERE {where} ORDER BY id")]


def test_sample_epoch_is_filled_on_insert_and_the_database_is_in_wal_mode():
    event_store.add(packet(T0))
    event_store.add_observation(SensorObservation.model_validate(
        {"device_id": "o", "farm_id": "farm", "zone_id": "a", "sensor_id": "t", "measurement": "air_temperature_c",
         "unit": "C", "value": 20, "timestamp": T0.isoformat()}))
    assert rows()[0][3] == T0.timestamp() and rows("sensor_observations")[0][3] == T0.timestamp()
    with sqlite3.connect(event_store._db_path) as db:
        assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    with event_store._connect() as db:
        assert db.execute("PRAGMA busy_timeout").fetchone()[0] >= 10000


def test_latest_and_prior_queries_use_the_sample_time_indexes(monkeypatch):
    statements, connect = [], sqlite3.connect

    def traced(*args, **kwargs):
        db = connect(*args, **kwargs)
        db.set_trace_callback(statements.append)  # every statement the store runs, with its values filled in
        return db

    event = packet(T0)
    event_store.add(event)
    monkeypatch.setattr(store_module.sqlite3, "connect", traced)
    event_store.latest_event("farm", "a")
    event_store.latest_event("farm", "a", "d1")
    event_store.prior_events(event)
    monkeypatch.setattr(store_module.sqlite3, "connect", connect)
    selects = [s for s in statements if s.lstrip().startswith("SELECT payload FROM sensor_events")]
    assert len(selects) == 3
    with connect(event_store._db_path) as db:
        for sql in selects:
            plan = " ".join(row[3] for row in db.execute("EXPLAIN QUERY PLAN " + sql))
            assert "USING INDEX sensor_events_sample_" in plan and "SCAN" not in plan, (sql, plan)
            assert "TEMP B-TREE" not in plan, plan  # the index gives the order, nothing is sorted afterwards
    assert not any("julianday" in sql for sql in statements)


def test_latest_event_orders_by_instant_then_by_id():
    early, late = T0, T0 + timedelta(minutes=5)
    event_store.add(packet(late, air_temperature_c=20.0))
    event_store.add(packet(early, air_temperature_c=21.0))  # arrived later, sampled earlier
    assert event_store.latest_event("farm", "a").air_temperature_c == 20.0
    event_store.add(packet(late, air_temperature_c=22.0))  # same sample time, stored later: wins the tie
    assert event_store.latest_event("farm", "a", "d1").air_temperature_c == 22.0
    assert event_store.latest_event("farm", "other") is None
    prior = event_store.prior_events(packet(late, air_temperature_c=22.0), limit=11)
    assert [e.air_temperature_c for e in prior] == [21.0, 20.0]  # the earlier sample first, then the same-time one stored before it


def test_future_sample_time_is_not_current(monkeypatch):
    monkeypatch.setattr(settings, "max_future_sample_s", 0)
    now = datetime.now(timezone.utc)
    event_store.add(packet(now - timedelta(minutes=1), air_temperature_c=20.0))
    event_store.add(packet(now + timedelta(hours=1), air_temperature_c=30.0))  # a bad clock: stored, never current
    assert event_store.latest_event("farm", "a").air_temperature_c == 20.0


def test_a_database_without_sample_epoch_is_filled_once_whatever_the_time_spelling(tmp_path):
    path = tmp_path / "legacy.db"
    stamps = ["2026-09-01T10:00:00Z", "2026-09-01T12:00:00+04:00", "2026-09-01T09:00:00.500000+00:00"]
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sensor_events (id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,payload TEXT NOT NULL)")
        for stamp in stamps:
            payload = {"device_id": "legacy", "farm_id": "farm", "zone_id": "z", "air_temperature_c": 24, "timestamp": stamp}
            db.execute("INSERT INTO sensor_events(timestamp,payload) VALUES (?,?)", (stamp, json.dumps(payload)))
    migrated = SensorEventStore(db_path=path)
    with sqlite3.connect(path) as db:
        epochs = [r[0] for r in db.execute("SELECT sample_epoch FROM sensor_events ORDER BY id")]
        names = {r[1] for r in db.execute("PRAGMA index_list(sensor_events)")}
    utc = lambda text: datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()  # noqa: E731
    assert epochs == [utc("2026-09-01T10:00:00"), utc("2026-09-01T08:00:00"), utc("2026-09-01T09:00:00.500000")]
    assert {"sensor_events_sample_device", "sensor_events_sample_zone"} <= names
    assert migrated.latest_event("farm", "z").timestamp.hour == 10
    with sqlite3.connect(path) as db:  # a start-up that crashed after ALTER TABLE: the column exists, some values are NULL
        db.execute("UPDATE sensor_events SET sample_epoch=NULL WHERE id IN (1, 3)")
        db.execute("UPDATE sensor_events SET sample_epoch=123.0 WHERE id=2")
    SensorEventStore(db_path=path)
    with sqlite3.connect(path) as db:  # the next start fills the NULL rows and leaves filled ones alone
        assert [r[0] for r in db.execute("SELECT sample_epoch FROM sensor_events ORDER BY id")] == [
            utc("2026-09-01T10:00:00"), 123.0, utc("2026-09-01T09:00:00.500000")]


def test_the_sample_epoch_backfill_runs_in_batches_and_one_pass_per_start(tmp_path):
    path = tmp_path / "batches.db"
    SensorEventStore(db_path=path)
    with sqlite3.connect(path) as db:
        for number in range(12):
            stamp = "not a time" if number == 5 else f"2026-09-01T10:{number:02d}:00Z"
            payload = {"device_id": "d", "farm_id": "farm", "zone_id": "z", "air_temperature_c": 24, "timestamp": stamp}
            db.execute("INSERT INTO sensor_events(timestamp,payload,farm_id,zone_id,device_id) VALUES (?,?,?,?,?)",
                       (stamp, json.dumps(payload), "farm", "z", "d"))
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        SensorEventStore._backfill_sample_epoch(db, "sensor_events", batch=5)  # three batches of at most 5
        filled = [r["sample_epoch"] for r in db.execute("SELECT sample_epoch FROM sensor_events ORDER BY id")]
    assert [e is None for e in filled] == [n == 5 for n in range(12)]  # the unparsable time stays NULL, the pass still ended


def test_sample_epoch_of_unreadable_or_naive_times():
    assert sample_epoch("not a time") is None
    assert sample_epoch("2026-09-01T00:00:00") == sample_epoch("2026-09-01T00:00:00Z")


def test_the_zone_cap_keeps_the_newest_rows_of_that_zone_only(monkeypatch):
    monkeypatch.setattr(event_store, "_max_events", 3)
    for i in range(5):
        event_store.add(packet(T0 + timedelta(seconds=i), zone="busy", air_temperature_c=20.0 + i))
        if i < 2:
            event_store.add(packet(T0 + timedelta(seconds=i), zone="quiet", air_temperature_c=30.0 + i))
    assert [(z, e.air_temperature_c) for z, e in [("busy", e) for e in event_store.list_events(zone_id="busy", farm_id="farm")]] == [
        ("busy", 22.0), ("busy", 23.0), ("busy", 24.0)]
    assert len(event_store.list_events(zone_id="quiet", farm_id="farm")) == 2
    assert len(rows(where="zone_id='busy'")) == 3


def test_the_zone_cap_of_one_keeps_only_the_newest(monkeypatch):
    monkeypatch.setattr(event_store, "_max_events", 1)
    for i in range(3):
        event_store.add(packet(T0 + timedelta(seconds=i), air_temperature_c=20.0 + i))
    assert [e.air_temperature_c for e in event_store.list_events()] == [22.0]


def test_age_cleanup_runs_at_most_once_a_minute_per_table(clock):
    event_store.add(packet(clock.now, device="old"))  # the first insert after start-up cleans (nothing to remove yet)
    clock.now += 8 * DAY
    event_store.add(packet(clock.now, device="new"))  # a long jump: cleans, so "old" goes
    assert {r[1] for r in rows()} == {"new"}
    with event_store._connect() as db:  # a row that is already past retention, as if it aged out between cleanups
        db.execute("INSERT INTO sensor_events(timestamp,payload,farm_id,zone_id,device_id,received_at,dedupe_key,sample_epoch) "
                   "VALUES (?,?,?,?,?,?,?,?)", ("t", "{}", "farm", "a", "stale", (clock.now - 9 * DAY).isoformat(), "k1", 0.0))
        db.execute("INSERT INTO device_fields VALUES ('farm','a','stale','ph',?,?)", ((clock.now - 9 * DAY).isoformat(),) * 2)
    clock.now += CLEANUP_INTERVAL - timedelta(seconds=1)
    event_store.add(packet(clock.now, device="new", air_temperature_c=25.0))
    assert "stale" in {r[1] for r in rows()}  # under a minute since the last cleanup: not run
    clock.now += timedelta(seconds=1)
    event_store.add(packet(clock.now, device="new", air_temperature_c=26.0))
    assert "stale" not in {r[1] for r in rows()}
    with event_store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM device_fields WHERE device_id='stale'").fetchone()[0] == 0


def test_a_clock_that_moves_back_cleans_again(clock):
    event_store.add(packet(clock.now, device="x"))
    clock.now -= DAY
    event_store.add(packet(clock.now, device="y"))
    assert event_store._cleaned[(str(event_store._db_path), "sensor_events")] == clock.now


def test_cleanup_is_tracked_per_database_and_table(clock, tmp_path, monkeypatch):
    event_store.add(packet(clock.now))
    keys = set(event_store._cleaned)
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "other.db")
    SensorEventStore(db_path=event_store._db_path)
    event_store.add(packet(clock.now))
    assert len(event_store._cleaned) == len(keys) + 1  # a different database file cleans on its own first insert
