"""Multi-device zones, slice 2 (docs/design/multi-device-zones-slice2.md 2.1 and 2.2): Core's zone snapshot, the
`event_trust` columns that carry each device's own sensor-check result, and the feed writing them."""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.outcome_feed as feed_module
import app.store as store_module
from app.config import settings
from app.main import app
from app.outcome_feed import OutcomeFeed
from app.schemas import SensorEvent
from app.store import SensorEventStore, event_store

DAY = timedelta(days=1)
T0 = datetime.now(timezone.utc).replace(microsecond=0) - 20 * DAY  # far enough back that every sample time is valid
CLIMATE = {"air_temperature_c": 24.0, "humidity_pct": 60.0}
SUBSTRATE = {"ph": 6.0, "ec_ms_cm": 2.0, "substrate_moisture_pct": 40.0}


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


def packet(clock, device="climate-1", fields=None, at=None, **updates):
    stamp = (at or clock.now).isoformat()
    return SensorEvent.model_validate({"device_id": device, "farm_id": "farm", "zone_id": "a", "timestamp": stamp,
                                       **(CLIMATE if fields is None else fields), **updates})


def add(event):
    assert event_store.add(event)
    return event


def snapshot(stale_after_s=0, farm="farm", zone="a"):
    return event_store.zone_snapshot(farm, zone, stale_after_s)


def by_device(result):
    return {d["device_id"]: d for d in result["devices"]}


def two_devices(clock):
    """climate-1 (air, humidity) then substrate-1 (pH, EC, moisture), 30 s apart; the clock is left at the second packet."""
    first = add(packet(clock))
    clock.now += timedelta(seconds=30)
    second = add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    return first, second


# --- not multi-device ------------------------------------------------------------------------------

def test_no_event_single_device_and_the_switch_answer_multi_device_false(clock, monkeypatch):
    assert snapshot() == {"multi_device": False}
    add(packet(clock))
    assert snapshot() == {"multi_device": False}
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    assert snapshot()["multi_device"] is True
    assert snapshot(farm="other") == {"multi_device": False} and snapshot(zone="b") == {"multi_device": False}
    monkeypatch.setattr(settings, "multi_device_zones", False)
    assert snapshot() == {"multi_device": False}


def test_the_endpoint_needs_farm_and_zone_and_answers_nothing_else_when_single_device():
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get("/v1/sensors/zone-snapshot").status_code == 422
        assert client.get("/v1/sensors/zone-snapshot", params={"farm_id": "farm"}).status_code == 422
        assert client.get("/v1/sensors/zone-snapshot", params={"zone_id": "a"}).status_code == 422
        assert client.get("/v1/sensors/zone-snapshot", params={"farm_id": "farm", "zone_id": "a", "stale_after_s": -1}).status_code == 422
        assert client.get("/v1/sensors/zone-snapshot", params={"farm_id": "farm", "zone_id": "a", "stale_after_s": "x"}).status_code == 422
        response = client.get("/v1/sensors/zone-snapshot", params={"farm_id": "farm", "zone_id": "a"})
        assert response.status_code == 200 and response.json() == {"multi_device": False}


def test_the_endpoint_returns_the_multi_device_snapshot_with_nulls_kept():
    now = datetime.now(timezone.utc)
    with TestClient(app, raise_server_exceptions=False) as client:
        for device, fields, ago in (("climate-1", CLIMATE, 40), ("substrate-1", SUBSTRATE, 20)):
            body = {"device_id": device, "farm_id": "farm", "zone_id": "a",
                    "timestamp": (now - timedelta(seconds=ago)).isoformat(), **fields}
            assert client.post("/v1/sensors/events", json=body).status_code == 201
        data = client.get("/v1/sensors/zone-snapshot", params={"farm_id": "farm", "zone_id": "a", "stale_after_s": 600}).json()
        assert data["multi_device"] is True and data["stale_after_s"] == 600
        assert [d["device_id"] for d in data["devices"]] == ["climate-1", "substrate-1"]
        assert set(data["fields"]) == {"air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"}
        assert data["devices"][0]["interval_s"] is None and data["devices"][0]["trust"] == {"status": "pending"}
        assert "source" not in data["devices"][0]["event"] and "device_id" not in data["sensor"]
        # all stale: nulls are present, not left out
        stale = client.get("/v1/sensors/zone-snapshot", params={"farm_id": "farm", "zone_id": "a", "stale_after_s": 1}).json()
        assert stale["sensor"] is None and stale["fields"] == {} and stale["newest_age_s"] is not None


# --- devices -------------------------------------------------------------------------------------

def test_devices_are_the_ones_with_a_live_packet_row_in_the_window_in_id_order(clock):
    add(packet(clock, device="zeta-9"))
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="alpha-1", fields=SUBSTRATE))
    with event_store._connect() as db:  # a row with no stored packet behind it: left out
        db.execute("INSERT INTO device_fields VALUES ('farm','a','ghost','__packet__',?,?)", (clock.now.isoformat(), clock.now.isoformat()))
        db.execute("INSERT INTO device_fields VALUES ('farm','a','old','__packet__',?,?)",
                   ((clock.now - 9 * DAY).isoformat(), (clock.now - 8 * DAY).isoformat()))
    result = snapshot()
    assert [d["device_id"] for d in result["devices"]] == ["alpha-1", "zeta-9"]
    device = by_device(result)["zeta-9"]
    assert device["event"]["air_temperature_c"] == 24.0 and "source" not in device["event"]
    assert device["sample_time"] == device["event"]["timestamp"] and device["received_at"] == device["event"]["received_at"]
    assert device["device_fields"] == ["air_temperature_c", "humidity_pct"]
    assert by_device(result)["alpha-1"]["device_fields"] == ["ec_ms_cm", "ph", "substrate_moisture_pct"]


def test_age_is_never_negative_and_follows_the_clock(clock):
    two_devices(clock)
    clock.now += timedelta(seconds=100)
    result = snapshot()
    assert by_device(result)["climate-1"]["age_s"] == 130 and by_device(result)["substrate-1"]["age_s"] == 100
    assert result["newest_age_s"] == 100
    with event_store._connect() as db:  # climate-1 sampled 30 s ahead of Core's clock (inside the 60 s allowance)
        db.execute("UPDATE sensor_events SET timestamp=?, payload=json_set(payload,'$.timestamp',?) WHERE device_id='climate-1'",
                   ((clock.now + timedelta(seconds=30)).isoformat(),) * 2)
        db.execute("UPDATE sensor_events SET timestamp=?, payload=json_set(payload,'$.timestamp',?) WHERE device_id='substrate-1'",
                   ((clock.now + timedelta(seconds=40)).isoformat(),) * 2)
    assert by_device(snapshot())["climate-1"]["age_s"] == 0 and by_device(snapshot())["substrate-1"]["age_s"] == 0


def test_an_empty_device_list_gives_a_null_sensor_and_null_newest_age(clock):
    two_devices(clock)
    clock.now += 8 * DAY  # nothing has arrived since: the device rows are older than the retention window
    result = snapshot()
    assert result["multi_device"] is True and result["devices"] == [] and result["fields"] == {}
    assert result["sensor"] is None and result["newest_age_s"] is None and result["sources"] == {}
    assert result["zone_device_fields"] == [] and result["context"] == {} and result["context_conflicts"] == []


# --- one device per field --------------------------------------------------------------------------

def test_a_pair_uses_the_device_that_sent_the_field_first_and_lists_the_other(clock):
    add(packet(clock, device="climate-2", air_temperature_c=23.0, humidity_pct=61.0))
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="climate-1", air_temperature_c=24.0, humidity_pct=60.0))  # sorts first by id, came second
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="climate-1", air_temperature_c=24.5, humidity_pct=60.5))
    result = snapshot()
    air = result["fields"]["air_temperature_c"]
    assert air["device_id"] == "climate-2" and air["value"] == 23.0
    assert air["others"] == [{"device_id": "climate-1", "value": 24.5, "sample_time": by_device(result)["climate-1"]["sample_time"],
                              "vetoed": False}]
    assert result["sources"]["air_temperature_c"] == ["climate-2"]
    assert by_device(result)["climate-2"]["supplied"] == ["air_temperature_c", "humidity_pct"]
    assert by_device(result)["climate-1"]["supplied"] == []
    # the order is stable: a newer packet from the other device does not flip it
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="climate-2", air_temperature_c=23.1, humidity_pct=61.1))
    add(packet(clock, device="climate-1", air_temperature_c=24.6, humidity_pct=60.6))
    assert snapshot()["fields"]["air_temperature_c"]["device_id"] == "climate-2"


def test_a_first_device_whose_own_check_vetoed_the_field_is_skipped_and_flagged_in_others(clock):
    add(packet(clock, device="climate-2", air_temperature_c=23.0, humidity_pct=61.0))
    clock.now += timedelta(seconds=30)
    second = add(packet(clock, device="climate-1"))
    first = event_store.latest_event("farm", "a", "climate-2")
    event_store.add_trust(first, "partial", ["humidity_pct"], ["stuck_value"], ["inspect humidity_pct"])
    result = snapshot()
    humidity = result["fields"]["humidity_pct"]
    assert humidity["device_id"] == "climate-1" and humidity["value"] == 60.0
    assert [(o["device_id"], o["vetoed"]) for o in humidity["others"]] == [("climate-2", True)]
    assert result["fields"]["air_temperature_c"]["device_id"] == "climate-2"  # only humidity was vetoed
    assert by_device(result)["climate-2"]["trust"] == {
        "status": "judged", "trust_verdict": "partial", "vetoed_fields": ["humidity_pct"],
        "data_quality_labels": ["stuck_value"], "safe_next_checks": ["inspect humidity_pct"]}
    # both vetoed: the first is used, still flagged
    event_store.add_trust(second, "partial", ["humidity_pct"], [], [])
    humidity = snapshot()["fields"]["humidity_pct"]
    assert humidity["device_id"] == "climate-2" and humidity["others"][0] == {
        "device_id": "climate-1", "value": 60.0, "sample_time": humidity["others"][0]["sample_time"], "vetoed": True}


def test_pending_pre_2_2_and_judged_rows(clock):
    first, second = two_devices(clock)
    assert [d["trust"] for d in snapshot()["devices"]] == [{"status": "pending"}] * 2
    with event_store._connect() as db:  # a row as the version before 2.2 wrote it
        db.execute("INSERT INTO event_trust (farm_id, zone_id, device_id, sample_time, trust_verdict, vetoed_fields, created_at) "
                   "VALUES ('farm','a','climate-1',?,'partial','[\"humidity_pct\"]',?)", (first.timestamp.isoformat(), clock.now.isoformat()))
    old = by_device(snapshot())["climate-1"]["trust"]
    assert old == {"status": "judged", "trust_verdict": "partial", "vetoed_fields": ["humidity_pct"],
                   "data_quality_labels": None, "safe_next_checks": None}
    event_store.add_trust(second, "trusted", [], [], [])
    assert by_device(snapshot())["substrate-1"]["trust"] == {
        "status": "judged", "trust_verdict": "trusted", "vetoed_fields": [], "data_quality_labels": [], "safe_next_checks": []}


def test_a_trust_row_belongs_to_the_latest_packet_only(clock):
    first, _ = two_devices(clock)
    event_store.add_trust(first, "partial", ["humidity_pct"], ["stuck_value"], [])
    clock.now += timedelta(seconds=30)
    add(packet(clock))  # a newer packet of climate-1: not judged yet
    assert by_device(snapshot())["climate-1"]["trust"] == {"status": "pending"}


def test_values_never_come_from_older_packets(clock):
    two_devices(clock)
    clock.now += timedelta(seconds=30)
    add(packet(clock, fields={"air_temperature_c": 25.0}))  # climate-1 now sends air only: humidity looks missing
    result = snapshot()
    assert "humidity_pct" not in result["fields"] and result["fields"]["air_temperature_c"]["value"] == 25.0
    assert result["sources"]["humidity_pct"] == ["climate-1"]  # a device expected to carry it is named
    assert "humidity_pct" in result["zone_device_fields"]


def test_a_non_finite_or_absent_reading_is_not_a_candidate(clock):
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    clock.now += timedelta(seconds=30)
    add(packet(clock, fields={"air_temperature_c": 24.0, "humidity_pct": None}))
    assert "humidity_pct" not in snapshot()["fields"]


# --- staleness -------------------------------------------------------------------------------------

def test_per_device_stale_limits_follow_the_devices_own_interval(clock):
    # fast: 30 s packets (limit = the setting), slow: 15 min packets (limit 45 min), lone: one packet (no interval)
    for i in range(7):
        add(packet(clock, device="slow-1", fields=SUBSTRATE))
        for _ in range(30):
            add(packet(clock, device="fast-1"))
            clock.now += timedelta(seconds=30)
    add(packet(clock, device="lone-1", fields={"ph": 6.1}))
    result = snapshot(stale_after_s=600)
    devices = by_device(result)
    assert devices["fast-1"]["interval_s"] == 30 and devices["fast-1"]["stale_limit_s"] == 600
    assert devices["slow-1"]["interval_s"] == 900 and devices["slow-1"]["stale_limit_s"] == 2700
    assert devices["lone-1"]["interval_s"] is None and devices["lone-1"]["stale_limit_s"] == 600


def test_interval_uses_the_last_six_live_packets_and_ignores_retained_ones(clock):
    gaps = [600, 600, 600, 60, 60, 60]  # the last six gaps need seven packets: older gaps must not count
    times = [clock.now]
    for gap in gaps:
        times.append(times[-1] + timedelta(seconds=gap))
    for stamp in times:
        clock.now = stamp
        add(packet(clock, at=stamp))
    for extra in (1, 2, 3):  # retained messages one second apart: not live packets, they must not count
        event_store.add(packet(clock, at=clock.now + timedelta(seconds=extra), mqtt_retained=True))
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    # the last 6 live packets of climate-1 hold the last 5 gaps, [600, 600, 60, 60, 60]: the median is 60
    assert by_device(snapshot())["climate-1"]["interval_s"] == 60


def test_the_stale_filter_leaves_a_quiet_device_out_and_off_means_never(clock):
    first, second = two_devices(clock)
    clock.now += timedelta(seconds=900)
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))  # substrate-1 keeps reporting, climate-1 is quiet for 930 s
    result = snapshot(stale_after_s=600)
    devices = by_device(result)
    assert devices["climate-1"]["stale"] is True and devices["climate-1"]["supplied"] == []
    assert devices["substrate-1"]["stale"] is False
    assert "air_temperature_c" not in result["fields"] and result["fields"]["ph"]["device_id"] == "substrate-1"
    assert result["sources"]["air_temperature_c"] == ["climate-1"]  # a stale carrier is still named
    assert result["zone_device_fields"] == sorted({*CLIMATE, *SUBSTRATE})
    off = snapshot(stale_after_s=0)
    assert by_device(off)["climate-1"]["stale"] is False and by_device(off)["climate-1"]["stale_limit_s"] == 0
    assert off["fields"]["air_temperature_c"]["device_id"] == "climate-1"


def test_when_every_device_is_stale_the_sensor_is_null(clock):
    two_devices(clock)
    clock.now += timedelta(seconds=3600)
    result = snapshot(stale_after_s=600)
    assert result["multi_device"] is True and result["sensor"] is None and result["fields"] == {}
    assert result["newest_age_s"] == 3600 and all(d["stale"] and d["supplied"] == [] for d in result["devices"])
    assert result["context"]  # still returned, nothing uses it


def test_a_slow_device_s_limit_is_capped_at_60_min_so_a_70_min_old_reading_is_stale(clock):
    # slow-1 sends every 30 min: 3 x 30 min would be 90 min, but the router vetoes anything older than 60 min
    add(packet(clock))  # a second device with a live packet makes the zone multi-device; climate-1 is not under test
    for i in range(7):
        add(packet(clock, device="slow-1", fields=SUBSTRATE))
        if i < 6:
            clock.now += timedelta(minutes=30)
    clock.now += timedelta(minutes=50)
    edge = by_device(snapshot(stale_after_s=600))["slow-1"]
    assert edge["interval_s"] == 1800 and edge["stale_limit_s"] == 3600
    assert edge["stale"] is False and set(edge["supplied"]) == set(SUBSTRATE)  # 50 min old: still inside the cap
    clock.now += timedelta(minutes=20)
    result = snapshot(stale_after_s=600)
    device = by_device(result)["slow-1"]
    assert device["interval_s"] == 1800 and device["stale_limit_s"] == 3600
    assert device["stale"] is True and device["supplied"] == []
    assert result["sensor"] is None


# --- the snapshot packet, sources, context -------------------------------------------------------------

def test_the_sensor_packet_has_context_values_no_device_and_the_newest_supplying_time(clock):
    first, second = two_devices(clock)
    result = snapshot()
    sensor = result["sensor"]
    assert "device_id" not in sensor
    assert sensor["farm_id"] == "farm" and sensor["zone_id"] == "a"
    assert sensor["timestamp"] == by_device(result)["substrate-1"]["sample_time"]  # the newest, not the oldest
    assert {k: v for k, v in sensor.items() if k in result["fields"]} == {k: f["value"] for k, f in result["fields"].items()}
    assert sensor["crop"] == "tomato" and sensor["growth_stage"] == "flowering" and sensor["system_type"] == "greenhouse_substrate"
    assert "weather" not in sensor and "zone_area_m2" not in sensor  # null context is left out
    assert result["sources"] == {"air_temperature_c": ["climate-1"], "humidity_pct": ["climate-1"], "ec_ms_cm": ["substrate-1"],
                                 "ph": ["substrate-1"], "substrate_moisture_pct": ["substrate-1"]}
    assert result["zone_device_fields"] == sorted({*CLIMATE, *SUBSTRATE})
    assert result["newest_age_s"] == 0


def test_the_sensor_timestamp_ignores_a_stale_device_that_supplies_nothing(clock):
    two_devices(clock)
    clock.now += timedelta(seconds=900)
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    result = snapshot(stale_after_s=600)
    assert result["sensor"]["timestamp"] == by_device(result)["substrate-1"]["sample_time"]


def test_context_drops_defaults_when_another_device_differs_and_takes_the_newest(clock):
    add(packet(clock, crop="lettuce", system_type="nft", growth_stage="vegetative"))
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))  # sent no context: Core fills the defaults
    result = snapshot()
    assert result["context"] == {"crop": "lettuce", "growth_stage": "vegetative", "system_type": "nft"}
    assert result["context_source"] == {"crop": "climate-1", "growth_stage": "climate-1", "system_type": "climate-1"}
    assert result["context_conflicts"] == []  # the default is not a conflict
    assert result["sensor"]["crop"] == "lettuce"


def test_context_conflicts_are_listed_and_the_newest_value_is_used(clock):
    add(packet(clock, crop="lettuce", weather={"t_mean_c": 20, "t_min_c": 15, "t_max_c": 25, "rh_mean_pct": 60,
                                              "wind_speed_2m_ms": 2, "solar_radiation_mj_m2_day": 15}))
    clock.now += timedelta(seconds=30)
    add(packet(clock, device="substrate-1", fields=SUBSTRATE, crop="basil", system_type="nft",
               weather={"solar_radiation_mj_m2_day": 15, "t_mean_c": 21, "t_min_c": 15, "t_max_c": 25, "rh_mean_pct": 60,
                        "wind_speed_2m_ms": 2}))
    result = snapshot()
    assert result["context"]["crop"] == "basil" and result["context_source"]["crop"] == "substrate-1"
    assert result["context"]["system_type"] == "nft"  # the other device's default is dropped, so no conflict
    assert result["context_conflicts"] == ["crop", "weather"]
    assert result["context"]["weather"]["t_mean_c"] == 21.0
    # the same weather with a different key order is the same value
    clock.now += timedelta(seconds=30)
    add(packet(clock, crop="basil", weather={"wind_speed_2m_ms": 2, "t_max_c": 25, "solar_radiation_mj_m2_day": 15,
                                            "t_mean_c": 21, "t_min_c": 15, "rh_mean_pct": 60}))
    assert snapshot()["context_conflicts"] == []


def test_context_ties_go_to_the_first_device_id_and_all_stale_still_returns_context(clock):
    add(packet(clock, crop="lettuce"))
    add(packet(clock, device="a-first", fields=SUBSTRATE, crop="basil"))
    assert snapshot()["context"]["crop"] == "basil"  # same sample time: the lower device_id
    clock.now += timedelta(seconds=3600)
    result = snapshot(stale_after_s=600)
    assert result["sensor"] is None and result["context"]["crop"] == "basil" and result["context_conflicts"] == ["crop"]


def test_context_comes_from_the_non_stale_devices_when_there_are_any(clock):
    add(packet(clock, crop="lettuce"))
    clock.now += timedelta(seconds=900)
    add(packet(clock, device="substrate-1", fields=SUBSTRATE, crop="basil"))
    result = snapshot(stale_after_s=600)
    assert result["context"]["crop"] == "basil" and result["context_conflicts"] == []


# --- 2.2: event_trust -------------------------------------------------------------------------------

def test_an_old_database_gets_the_new_event_trust_columns_and_keeps_its_rows(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE event_trust (farm_id TEXT NOT NULL, zone_id TEXT NOT NULL, device_id TEXT NOT NULL,
            sample_time TEXT NOT NULL, trust_verdict TEXT NOT NULL, vetoed_fields TEXT NOT NULL, created_at TEXT NOT NULL,
            PRIMARY KEY (farm_id, zone_id, device_id, sample_time))""")
        conn.execute("INSERT INTO event_trust VALUES ('f','z','d','2026-01-01T00:00:00+00:00','partial','[\"ph\"]','2026-01-01T00:00:00+00:00')")
    store = SensorEventStore(db_path=path)
    SensorEventStore(db_path=path)  # a second start-up is fine
    with store._connect() as db:
        columns = [r[1] for r in db.execute("PRAGMA table_info(event_trust)")]
        row = db.execute("SELECT * FROM event_trust").fetchone()
    assert columns[-3:] == ["data_quality_labels", "safe_next_checks", "pair_fields"]  # pair_fields: slow-drift pair check 4b
    assert row["vetoed_fields"] == '["ph"]' and row["data_quality_labels"] is None and row["safe_next_checks"] is None
    assert row["pair_fields"] is None


def test_a_new_database_has_the_columns_and_add_trust_overwrites_them(clock):
    event = add(packet(clock))
    event_store.add_trust(event, "partial", ["humidity_pct", "air_temperature_c"], ["stuck_value"], ["inspect humidity_pct"])
    with event_store._connect() as db:
        row = db.execute("SELECT * FROM event_trust").fetchone()
    assert json.loads(row["vetoed_fields"]) == ["air_temperature_c", "humidity_pct"]
    assert json.loads(row["data_quality_labels"]) == ["stuck_value"] and json.loads(row["safe_next_checks"]) == ["inspect humidity_pct"]
    event_store.add_trust(event, "trusted", [], ["a_label"], ["continue routine monitoring"])  # the same packet judged again
    with event_store._connect() as db:
        rows = db.execute("SELECT * FROM event_trust").fetchall()
    assert len(rows) == 1 and rows[0]["trust_verdict"] == "trusted" and rows[0]["vetoed_fields"] == "[]"
    assert json.loads(rows[0]["data_quality_labels"]) == ["a_label"]
    event_store.add_trust(event, "trusted", [])  # no labels given: stored as not recorded
    with event_store._connect() as db:
        row = db.execute("SELECT * FROM event_trust").fetchone()
    assert row["data_quality_labels"] is None and row["safe_next_checks"] is None


# --- the feed writes them ---------------------------------------------------------------------------------

def test_the_feed_writes_labels_and_checks_in_every_zone(clock, monkeypatch):
    monkeypatch.setattr(settings, "model_router_url", "http://router.test")
    monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
    answer = {"trust_gate": {"trust_verdict": "partial", "vetoed_fields": ["humidity_pct"]},
              "sensor_quality": {"data_quality_labels": ["stuck_value"], "safe_next_checks": ["inspect humidity_pct"]}}
    monkeypatch.setattr(feed_module, "_post", lambda base, path, body: answer if path == "/v1/pipeline/evaluate" else {})
    feed = OutcomeFeed(event_store, queue_size=5)
    single = add(packet(clock))  # a one-device zone
    feed._process(single)
    clock.now += timedelta(seconds=30)
    multi = add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    feed._process(multi)
    with event_store._connect() as db:
        rows = db.execute("SELECT device_id, trust_verdict, vetoed_fields, data_quality_labels, safe_next_checks FROM event_trust "
                          "ORDER BY device_id").fetchall()
    assert [tuple(r) for r in rows] == [("climate-1", "partial", '["humidity_pct"]', '["stuck_value"]', '["inspect humidity_pct"]'),
                                        ("substrate-1", "partial", '["humidity_pct"]', '["stuck_value"]', '["inspect humidity_pct"]')]
    assert by_device(snapshot())["substrate-1"]["trust"]["data_quality_labels"] == ["stuck_value"]


def test_the_feed_writes_empty_lists_when_the_router_answers_without_a_sensor_quality(clock, monkeypatch):
    monkeypatch.setattr(settings, "model_router_url", "http://router.test")
    monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
    monkeypatch.setattr(feed_module, "_post", lambda base, path, body: {"trust_gate": {"trust_verdict": "trusted"}} if path.endswith("evaluate") else {})
    OutcomeFeed(event_store, queue_size=5)._process(add(packet(clock)))
    with event_store._connect() as db:
        row = db.execute("SELECT data_quality_labels, safe_next_checks FROM event_trust").fetchone()
    assert (row["data_quality_labels"], row["safe_next_checks"]) == ("[]", "[]")
