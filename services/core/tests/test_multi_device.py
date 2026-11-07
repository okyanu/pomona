"""Multi-device zones, slice 1 (docs/design/multi-device-zones.md): per-device history, the device-fields table,
the multi-device test, the device filter on the listing endpoints, and what the outcome feed sends."""
import json
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
from app.schemas import SensorEvent, SensorObservation
from app.store import SensorEventStore, event_store

DAY = timedelta(days=1)
T0 = datetime.now(timezone.utc).replace(microsecond=0) - 20 * DAY  # far enough back that every sample time is valid


class Clock:
    """Core's clock for the store: received_at and the retention cutoff follow it."""

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


CLIMATE = {"air_temperature_c": 24.0, "humidity_pct": 60.0}
SUBSTRATE = {"ph": 6.0, "ec_ms_cm": 2.0, "substrate_moisture_pct": 40.0}


def packet(clock, device="climate-1", fields=None, at=None, **updates):
    """A live full packet sampled at the store clock (or `at`)."""
    stamp = (at or clock.now).isoformat()
    return SensorEvent.model_validate({"device_id": device, "farm_id": "farm", "zone_id": "a", "timestamp": stamp,
                                       **(CLIMATE if fields is None else fields), **updates})


def add(event):
    assert event_store.add(event)
    return event


def stored_rows():
    with event_store._connect() as db:
        rows = db.execute("SELECT device_id, field, first_seen, last_seen FROM device_fields "
                          "ORDER BY device_id, field").fetchall()
    return [tuple(row) for row in rows]


# --- 1.3 the device-fields table ----------------------------------------------------------------

def test_upsert_keeps_first_and_last_seen_and_only_finite_reading_fields(clock):
    first = add(packet(clock, fields={**CLIMATE, "ph": None}, weather={"t_mean_c": 20, "t_min_c": 15, "t_max_c": 25,
                                                                         "rh_mean_pct": 60, "wind_speed_2m_ms": 1,
                                                                         "solar_radiation_mj_m2_day": 10},
                       zone_area_m2=20.0, crop_kc=1.1))
    clock.now += timedelta(minutes=5)
    add(packet(clock, fields={"air_temperature_c": 25.0, "ph": 6.1}))
    stamp = lambda offset: (T0 + offset).isoformat()  # noqa: E731
    assert stored_rows() == [
        ("climate-1", "__packet__", stamp(timedelta(0)), stamp(timedelta(minutes=5))),
        ("climate-1", "air_temperature_c", stamp(timedelta(0)), stamp(timedelta(minutes=5))),
        ("climate-1", "humidity_pct", stamp(timedelta(0)), stamp(timedelta(0))),
        ("climate-1", "ph", stamp(timedelta(minutes=5)), stamp(timedelta(minutes=5))),
    ]
    assert first.received_at == T0


def test_retained_ineligible_duplicate_and_observation_packets_are_not_recorded(clock):
    event_store.add(packet(clock, device="retained", mqtt_retained=True))
    event_store.add(packet(clock, device="future", at=clock.now + timedelta(seconds=200)))  # bad clock: stored, not current
    event_store.add_observation(SensorObservation.model_validate({
        "device_id": "obs", "farm_id": "farm", "zone_id": "a", "sensor_id": "t", "measurement": "air_temperature_c",
        "unit": "C", "value": 24, "timestamp": clock.now.isoformat()}))
    assert stored_rows() == []
    live = packet(clock, device="live")
    add(live)
    clock.now += DAY
    assert not event_store.add(packet(clock, device="live", at=T0))  # same content again: duplicate
    assert {row[0] for row in stored_rows()} == {"live"} and {row[3] for row in stored_rows()} == {T0.isoformat()}


def test_a_retained_packet_promoted_by_a_live_copy_is_recorded_then(clock):
    body = {"boot_id": "b", "sequence": 1}
    event_store.add(packet(clock, mqtt_retained=True, **body))
    assert stored_rows() == []
    assert not event_store.add(packet(clock, **body))  # promotes the stored row: not newly inserted, but live now
    assert [row[1] for row in stored_rows()] == ["__packet__", "air_temperature_c", "humidity_pct"]


def test_cleanup_happens_in_add_with_the_retention_cutoff(clock):
    add(packet(clock, device="old"))
    clock.now += timedelta(days=settings.retention_days - 1)
    add(packet(clock, device="new"))
    assert {row[0] for row in stored_rows()} == {"old", "new"}
    clock.now += 2 * DAY
    add(packet(clock, device="new"))
    assert {row[0] for row in stored_rows()} == {"new"}


def test_clear_empties_the_table(clock):
    add(packet(clock))
    assert stored_rows()
    event_store.clear()
    assert stored_rows() == []


def test_backfill_runs_once_when_the_table_is_created_on_an_existing_database(clock):
    add(packet(clock, device="a-old", fields={"ph": 6.0}))  # received at T0
    clock.now += 6 * DAY
    add(packet(clock, device="b", fields=SUBSTRATE))  # event cleanup (7 days) has not removed a-old yet
    clock.now += timedelta(minutes=1)
    add(packet(clock, device="b", fields={"ph": 6.2, "air_temperature_c": 22.0}))
    event_store.add(packet(clock, device="retained-only", mqtt_retained=True))
    event_store.add(packet(clock, device="future", at=clock.now + timedelta(seconds=200)))
    expected = [row for row in stored_rows() if row[0] == "b"]
    with event_store._connect() as db:
        db.execute("DROP TABLE device_fields")  # the database as it was before this feature
        assert db.execute("SELECT COUNT(*) FROM sensor_events WHERE device_id='a-old'").fetchone()[0] == 1
    clock.now += 2 * DAY  # the upgrade: a-old (received 8 days ago) is still stored but older than retention
    SensorEventStore(db_path=event_store._db_path)
    assert stored_rows() == expected and expected  # a-old, the retained-only and the future-clock packets are not backfilled
    with event_store._connect() as db:
        db.execute("DELETE FROM device_fields WHERE field='ph'")
    SensorEventStore(db_path=event_store._db_path)  # a second start-up does not scan again
    assert not [row for row in stored_rows() if row[1] == "ph"]


def test_index_for_the_per_device_queries_exists():
    with event_store._connect() as db:
        names = {row[1] for row in db.execute("PRAGMA index_list(sensor_events)")}
    assert "sensor_events_device" in names


# --- 1.1 when is a zone multi-device -------------------------------------------------------------

def test_a_zone_is_multi_device_from_the_second_devices_first_live_packet(clock):
    one = add(packet(clock))
    assert event_store.device_fields_for(one) is None
    clock.now += timedelta(seconds=30)
    two = add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    assert event_store.device_fields_for(two) == ["ec_ms_cm", "ph", "substrate_moisture_pct"]
    clock.now += timedelta(seconds=30)
    again = add(packet(clock, fields={"air_temperature_c": 24.5}))
    assert event_store.device_fields_for(again) == ["air_temperature_c", "humidity_pct"]  # humidity within 7 days still counts


def test_the_test_uses_the_readings_own_received_at(clock):
    first = add(packet(clock))
    clock.now += timedelta(hours=1)
    second = add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    # Judged later, the first device's reading still sees the zone as it was when it was received.
    assert event_store.device_fields_for(first) is None
    assert event_store.device_fields_for(second) is not None


@pytest.mark.parametrize("days_silent, multi", [(6, True), (8, False)])
def test_a_partner_silent_for_6_days_counts_for_8_days_does_not(clock, days_silent, multi):
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    clock.now += days_silent * DAY
    reading = add(packet(clock))
    assert (event_store.device_fields_for(reading) is not None) is multi


def test_a_probe_silent_for_6_days_stays_expected_for_8_days_is_forgotten(clock):
    ph_and_moisture = {"ph": 6.1, "substrate_moisture_pct": 41.0}
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    add(packet(clock))  # a partner that stays alive
    clock.now += 6 * DAY
    add(packet(clock))
    near = add(packet(clock, device="substrate-1", fields=ph_and_moisture))
    assert event_store.device_fields_for(near) == ["ec_ms_cm", "ph", "substrate_moisture_pct"]
    clock.now += 2 * DAY  # EC was last seen 8 days ago
    add(packet(clock))
    later = add(packet(clock, device="substrate-1", fields=ph_and_moisture))
    assert event_store.device_fields_for(later) == ["ph", "substrate_moisture_pct"]


def insert_fields(device, fields, first_seen, last_seen):
    with event_store._connect() as db:
        for field in fields:
            db.execute("INSERT INTO device_fields VALUES ('farm','a',?,?,?,?)",
                       (device, field, first_seen.isoformat(), last_seen.isoformat()))


@pytest.mark.parametrize("last_seen_days_before, multi", [(6, True), (8, False)])
def test_the_sql_rule_checks_last_seen_against_received_at_minus_retention(clock, last_seen_days_before, multi):
    reading = packet(clock)
    reading.received_at = T0 + 30 * DAY  # judged long after the rows were written: no cleanup involved
    insert_fields("substrate-1", [store_module.PACKET_FIELD, "ph"], T0, T0 + (30 - last_seen_days_before) * DAY)
    insert_fields("climate-1", [store_module.PACKET_FIELD, "air_temperature_c", "humidity_pct"], T0, T0 + 30 * DAY)
    assert (event_store.device_fields_for(reading) is not None) is multi


def test_the_sql_rule_counts_only_the_fields_of_the_device_whose_last_seen_is_in_the_window(clock):
    reading = packet(clock)
    reading.received_at = T0 + 30 * DAY
    insert_fields("substrate-1", [store_module.PACKET_FIELD], T0, T0 + 30 * DAY)
    insert_fields("climate-1", [store_module.PACKET_FIELD, "air_temperature_c"], T0, T0 + 30 * DAY)
    insert_fields("climate-1", ["humidity_pct"], T0, T0 + 20 * DAY)  # last seen 10 days before the reading: forgotten
    assert event_store.device_fields_for(reading) == ["air_temperature_c"]


@pytest.mark.parametrize("partner", ["retained", "future", "observation"])
def test_partners_that_are_not_live_full_packets_do_not_make_a_zone_multi_device(clock, partner):
    if partner == "retained":
        event_store.add(packet(clock, device="other", mqtt_retained=True))
    elif partner == "future":
        event_store.add(packet(clock, device="other", at=clock.now + timedelta(seconds=200)))
    else:
        event_store.add_observation(SensorObservation.model_validate({
            "device_id": "other", "farm_id": "farm", "zone_id": "a", "sensor_id": "t",
            "measurement": "air_temperature_c", "unit": "C", "value": 24, "timestamp": clock.now.isoformat()}))
    clock.now += timedelta(seconds=30)
    assert event_store.device_fields_for(add(packet(clock, device="mine"))) is None


def test_other_farms_and_zones_do_not_count(clock):
    add(packet(clock, device="other-zone", zone_id="b"))
    add(packet(clock, device="other-farm", farm_id="farm-2"))
    assert event_store.device_fields_for(add(packet(clock))) is None


def test_the_switch_turns_the_feature_off(clock, monkeypatch):
    add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    reading = add(packet(clock))
    assert event_store.device_fields_for(reading) is not None
    monkeypatch.setattr(settings, "multi_device_zones", False)
    assert event_store.device_fields_for(reading) is None


# --- 1.2 per-device history ----------------------------------------------------------------------

def test_prior_events_are_the_devices_own(clock):
    mine = []
    for i in range(3):
        mine.append(add(packet(clock, fields={"air_temperature_c": 20.0 + i})))
        add(packet(clock, device="other", fields={"air_temperature_c": 30.0 + i}))
        clock.now += timedelta(seconds=30)
    last = add(packet(clock))
    history = event_store.prior_events(last, 11)
    assert [e.device_id for e in history] == ["climate-1"] * 3
    assert [e.air_temperature_c for e in history] == [20.0, 21.0, 22.0]


def test_same_sample_time_tie_rule_holds_within_one_device(clock):
    first = add(packet(clock, fields={"air_temperature_c": 20.0}))
    assert event_store.prior_events(first, 11) == []
    second = add(packet(clock, fields={"air_temperature_c": 21.0}))  # same sample time, stored after
    other = add(packet(clock, device="other"))
    assert [e.air_temperature_c for e in event_store.prior_events(second, 11)] == [20.0]
    assert event_store.prior_events(other, 11) == []  # the other device's packets at that time are not history


# --- the feed ------------------------------------------------------------------------------------

@pytest.fixture
def calls(monkeypatch):
    monkeypatch.setattr(settings, "model_router_url", "http://router.test")
    monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
    recorded = []
    monkeypatch.setattr(feed_module, "_post", lambda base, path, body: recorded.append((path, body)) or {})
    return recorded


def evaluations(calls):
    return [body for path, body in calls if path == "/v1/pipeline/evaluate"]


def test_device_fields_are_sent_only_in_multi_device_zones(clock, calls):
    feed = OutcomeFeed(event_store, queue_size=5)
    one = add(packet(clock))
    feed._process(one)
    assert "device_fields" not in evaluations(calls)[0] and "not_expected_fields" not in evaluations(calls)[0]
    clock.now += timedelta(seconds=30)
    two = add(packet(clock, device="substrate-1", fields=SUBSTRATE))
    feed._process(two)
    assert evaluations(calls)[1]["device_fields"] == ["ec_ms_cm", "ph", "substrate_moisture_pct"]
    clock.now += timedelta(seconds=30)
    again = add(packet(clock))
    feed._process(again)
    sent = evaluations(calls)[2]
    assert sent["device_fields"] == ["air_temperature_c", "humidity_pct"]
    assert [h["device_id"] for h in sent["history"]] == ["climate-1"]  # not the other device's packet


def test_a_single_device_request_is_unchanged(clock, calls):
    feed = OutcomeFeed(event_store, queue_size=5)
    feed._process(add(packet(clock)))
    assert list(evaluations(calls)[0]) == ["scenario_id", "farm_context", "sensor", "history", "proposed_command",
                                           "actor", "mode"]


# --- 1.5 the device filter and the response keys -------------------------------------------------

@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def post_two_devices(client):
    now = datetime.now(timezone.utc)
    for i, device, fields in ((0, "climate-1", CLIMATE), (1, "substrate-1", SUBSTRATE), (2, "climate-1", CLIMATE)):
        stamp = (now - timedelta(seconds=60 - 10 * i)).isoformat()
        body = {"device_id": device, "farm_id": "farm", "zone_id": "a", "timestamp": stamp, **fields}
        assert client.post("/v1/sensors/events", json=body).status_code == 201
        body = {"device_id": device, "farm_id": "farm", "zone_id": "a", "sensor_id": "s", "measurement": "ph",
                "unit": "pH", "value": 6.0 + i / 10, "timestamp": stamp}
        assert client.post("/v1/sensors/observations", json=body).status_code == 201


def test_device_filter_on_the_four_endpoints(client):
    post_two_devices(client)
    everything = client.get("/v1/sensors/events", params={"zone_id": "a"}).json()
    assert everything["count"] == 3 and everything["latest_event"]["device_id"] == "climate-1"
    only = client.get("/v1/sensors/events", params={"zone_id": "a", "device_id": "substrate-1"}).json()
    assert only["count"] == 1 and only["events"][0]["device_id"] == "substrate-1"
    assert only["latest_event"]["device_id"] == "substrate-1"
    assert client.get("/v1/sensors/events/latest", params={"device_id": "substrate-1"}).json()["device_id"] == "substrate-1"
    assert client.get("/v1/sensors/events/latest").json()["device_id"] == "climate-1"
    assert client.get("/v1/sensors/events/latest", params={"device_id": "nobody"}).status_code == 404
    csv_all = client.get("/v1/sensors/export.csv", params={"zone_id": "a"}).text.strip().splitlines()
    csv_one = client.get("/v1/sensors/export.csv", params={"zone_id": "a", "device_id": "substrate-1"}).text.strip().splitlines()
    assert len(csv_all) == 4 and len(csv_one) == 2 and "substrate-1" in csv_one[1]
    observations = client.get("/v1/sensors/observations", params={"zone_id": "a"}).json()
    assert observations["count"] == 3
    one_device = client.get("/v1/sensors/observations", params={"zone_id": "a", "device_id": "climate-1"}).json()
    assert one_device["count"] == 2 and {o["device_id"] for o in one_device["observations"]} == {"climate-1"}
    csv_obs = client.get("/v1/sensors/export.csv", params={"kind": "observations", "device_id": "substrate-1"}).text.strip()
    assert len(csv_obs.splitlines()) == 2


def test_other_listings_are_unchanged_by_the_filter_work(client):
    post_two_devices(client)
    assert {d["device_id"] for d in client.get("/v1/sensors/devices").json()["devices"]} == {"climate-1", "substrate-1"}
    assert client.get("/v1/sensors/calibrations", params={"device_id": "nobody"}).json()["count"] == 0
    assert client.get("/v1/sensors/corrected-observations").json()["count"] == 0


def test_events_response_says_whether_the_zone_is_multi_device(client):
    now = datetime.now(timezone.utc)
    body = {"device_id": "climate-1", "farm_id": "farm", "zone_id": "a", "timestamp": (now - timedelta(seconds=30)).isoformat(),
            **CLIMATE}
    client.post("/v1/sensors/events", json=body)
    single = client.get("/v1/sensors/events").json()
    assert single["zone_multi_device"] is False and single["latest_device_fields"] is None
    other = {k: v for k, v in body.items() if k not in CLIMATE}
    client.post("/v1/sensors/events", json={**other, "device_id": "substrate-1", **SUBSTRATE,
                                            "timestamp": (now - timedelta(seconds=20)).isoformat()})
    multi = client.get("/v1/sensors/events").json()
    assert multi["zone_multi_device"] is True and multi["latest_device_fields"] == ["ec_ms_cm", "ph", "substrate_moisture_pct"]
    assert client.get("/v1/sensors/events", params={"device_id": "climate-1"}).json()["latest_device_fields"] is None  # before the partner
    client.post("/v1/sensors/events", json={**body, "air_temperature_c": 24.5, "timestamp": (now - timedelta(seconds=10)).isoformat()})
    climate = client.get("/v1/sensors/events", params={"device_id": "climate-1"}).json()
    assert climate["latest_device_fields"] == ["air_temperature_c", "humidity_pct"]
    empty = client.get("/v1/sensors/events", params={"farm_id": "nobody"}).json()
    assert empty["zone_multi_device"] is False and empty["latest_device_fields"] is None
