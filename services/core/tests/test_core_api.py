from datetime import datetime, timezone
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.config import settings
from app.main import app
from app.store import event_store, SensorEventStore
import app.store as store_module
from app.mqtt_client import MqttIngestClient
from app.schemas import SensorEvent
from datetime import timedelta
from types import SimpleNamespace


@pytest.fixture(autouse=True)
def clear_store(tmp_path, monkeypatch):
    # Never clear the owner's configured database during unit tests.
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "test.db")
    SensorEventStore(db_path=event_store._db_path)
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "pomona-core"


@pytest.mark.parametrize("value", [True, False, "NaN", "Infinity", "bad"])
def test_invalid_numeric_sensor_input(client, value):
    payload = _sensor_payload()
    payload["ph"] = value
    assert client.post("/v1/sensors/events", json=payload).status_code == 422


def test_mqtt_identity_retention_dedupe_and_restart(client):
    import json
    now = datetime.now(timezone.utc)
    payload = {**_sensor_payload(), "farm_id": "farm", "zone_id": "a", "device_id": "node",
               "timestamp": now.isoformat(), "boot_id": "boot-a", "sequence": 10}
    topic = "pomona/farm/a/sensor/node/state"
    ingest = MqttIngestClient()
    def deliver(value, retained=False, target=topic):
        ingest._on_message(None, None, SimpleNamespace(topic=target, payload=json.dumps(value).encode(), retain=retained))
    deliver(payload, target="pomona/farm/wrong/sensor/node/state")
    assert event_store.count() == 0
    deliver(payload, retained=True)
    assert event_store.devices()[0]["availability"] == "unknown"
    assert event_store.count() == 1
    deliver(payload)
    assert event_store.devices()[0]["availability"] == "recent"
    deliver(payload)
    assert event_store.count() == 1
    deliver({**payload, "sequence": 9, "timestamp": (now + timedelta(seconds=1)).isoformat()})
    assert event_store.latest_event().sequence == 10
    deliver({**payload, "boot_id": "boot-b", "sequence": 0, "timestamp": (now + timedelta(seconds=2)).isoformat()})
    assert event_store.latest_event().boot_id == "boot-b"
    reopened = SensorEventStore(db_path=event_store._db_path)
    assert reopened.latest_event().boot_id == "boot-b"
    assert reopened.count() == 3


def test_late_and_future_packets_do_not_replace_latest(client):
    now = datetime.now(timezone.utc)
    fresh = {**_sensor_payload(), "timestamp": now.isoformat()}
    for sample in (fresh, {**fresh, "timestamp": (now - timedelta(hours=2)).isoformat()},
                   {**fresh, "timestamp": (now + timedelta(minutes=2)).isoformat()}):  # accepted (under the future limit), not current
        assert client.post("/v1/sensors/events", json=sample).status_code == 201
    assert event_store.latest_event().timestamp == now
    result = client.get("/v1/sensors/events/latest").json()
    assert datetime.fromisoformat(result["timestamp"].replace("Z", "+00:00")) == now
    assert client.get("/v1/sensors/events").json()["latest_event"] == result


def test_observation_sequence_is_per_sensor(client):
    for sensor in ("one", "two"):
        payload = observation_payload(sensor_id=sensor, boot_id="boot-a", sequence=1)
        client.post("/v1/sensors/observations", json=payload)
        client.post("/v1/sensors/observations", json=payload)
    assert len(event_store.list_observations()) == 2


def observation_payload(**updates):
    return {"device_id": "node", "farm_id": "farm", "zone_id": "a", "sensor_id": "temp",
            "measurement": "air_temperature_c", "unit": "C", "value": 24,
            "timestamp": datetime.now(timezone.utc).isoformat(), **updates}


def test_modular_observation_is_not_full_event(client):
    payload = observation_payload(received_at="2000-01-01T00:00:00Z")
    response = client.post("/v1/sensors/observations", json=payload)
    assert response.status_code == 201
    assert not response.json()["received_at"].startswith("2000")
    assert client.get("/v1/sensors/events").json()["count"] == 0
    assert client.get("/v1/sensors/events/latest").status_code == 404
    assert client.post("/v1/sensors/events", json=payload).status_code == 422
    device = client.get("/v1/sensors/devices").json()["devices"][0]
    assert device["availability"] == "recent"
    assert device["sample_stale"] is False


@pytest.mark.parametrize("updates", [{"unit": "%"}, {"value": None}, {"value": 90},
    {"timestamp": "2026-09-05T00:00:00"}, {"invented": 1}])
def test_invalid_observation(client, updates):
    assert client.post("/v1/sensors/observations", json=observation_payload(**updates)).status_code == 422


def test_missing_observation_and_scoped_csv(client, monkeypatch):
    import csv
    import io
    monkeypatch.setattr(event_store, "_max_events", 2)
    assert client.post("/v1/sensors/observations", json=observation_payload(zone_id="b", value=None, quality="missing")).status_code == 201
    for value in [21, 22, 23]:
        assert client.post("/v1/sensors/observations", json=observation_payload(device_id="=formula", value=value)).status_code == 201
    assert client.get("/v1/sensors/observations", params={"zone_id": "b"}).json()["count"] == 1
    assert client.get("/v1/sensors/observations", params={"zone_id": "a"}).json()["count"] == 2
    response = client.get("/v1/sensors/export.csv", params={"kind": "observations", "farm_id": "farm", "zone_id": "a", "limit": 1, "offset": 1})
    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    assert len(rows) == 1 and rows[0]["value"] == "22.0"
    assert rows[0]["device_id"] == "'=formula"
    assert client.get("/v1/sensors/devices", params={"farm_id": "other"}).json()["devices"] == []


def test_receipt_retention_and_silent_device(client, monkeypatch):
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(store_module, "utc_now", lambda: now - timedelta(days=8))
    client.post("/v1/sensors/observations", json=observation_payload(device_id="old", timestamp=(now - timedelta(days=8)).isoformat()))
    monkeypatch.setattr(store_module, "utc_now", lambda: now)
    client.post("/v1/sensors/observations", json=observation_payload(device_id="new"))
    assert client.get("/v1/sensors/observations").json()["count"] == 1
    devices = {d["device_id"]: d for d in client.get("/v1/sensors/devices").json()["devices"]}
    assert devices["old"]["availability"] == "silent"
    assert devices["new"]["availability"] == "recent"


def test_legacy_database_migration(tmp_path):
    import sqlite3
    import json
    payload = {"device_id": "legacy", "farm_id": "farm", "zone_id": "legacy-zone", "air_temperature_c": 24,
               "humidity_pct": 60, "ph": 6, "ec_ms_cm": 2, "soil_moisture_pct": 45, "timestamp": "2026-09-01T00:00:00Z"}
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE sensor_events (id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,payload TEXT NOT NULL)")
        db.execute("INSERT INTO sensor_events(timestamp,payload) VALUES (?,?)", (payload["timestamp"], json.dumps(payload)))
    migrated = SensorEventStore(db_path=path)
    assert migrated.list_events(farm_id="farm", zone_id="legacy-zone")[0].received_at is None
    assert migrated.list_events(zone_id="other") == []


def test_mqtt_modular_observation(client):
    import json
    from types import SimpleNamespace
    mqtt = MqttIngestClient()
    mqtt._on_message(None, None, SimpleNamespace(topic="pomona/farm/a/sensor/node/observation", payload=json.dumps(observation_payload()).encode()))
    assert client.get("/v1/sensors/observations").json()["count"] == 1
    assert client.get("/v1/sensors/events").json()["count"] == 0


def test_ingest_and_list_sensor_event(client: TestClient):
    payload = {
        "device_id": "test-device",
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "crop": "tomato",
        "growth_stage": "flowering",
        "air_temperature_c": 28.5,
        "humidity_pct": 72.0,
        "ec_ms_cm": 2.8,
        "ph": 6.2,
        "soil_moisture_pct": 45.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    create = client.post("/v1/sensors/events", json=payload)
    assert create.status_code == 201
    assert create.json()["device_id"] == "test-device"

    listing = client.get("/v1/sensors/events")
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    latest = client.get("/v1/sensors/events/latest")
    assert latest.status_code == 200
    assert latest.json()["ph"] == 6.2


def test_ingest_accepts_and_returns_optional_agronomy_calc_fields(client: TestClient):
    payload = {
        "device_id": "test-device",
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "crop": "tomato",
        "growth_stage": "flowering",
        "air_temperature_c": 28.5,
        "humidity_pct": 72.0,
        "ec_ms_cm": 2.8,
        "ph": 6.2,
        "soil_moisture_pct": 45.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "weather": {
            "t_mean_c": 29.2,
            "t_min_c": 25.6,
            "t_max_c": 34.8,
            "rh_mean_pct": 66,
            "wind_speed_2m_ms": 2.0,
            "solar_radiation_mj_m2_day": 14.0,
            "elevation_m": 2,
        },
        "zone_area_m2": 20,
        "crop_kc": 1.15,
        "npk_target": {"n_ppm": 150, "p_ppm": 50, "k_ppm": 200, "volume_liters": 100},
    }

    create = client.post("/v1/sensors/events", json=payload)
    assert create.status_code == 201
    body = create.json()
    assert body["zone_area_m2"] == 20
    assert body["crop_kc"] == 1.15
    assert body["weather"]["t_mean_c"] == 29.2
    assert body["npk_target"]["n_ppm"] == 150

    latest = client.get("/v1/sensors/events/latest")
    assert latest.status_code == 200
    assert latest.json()["npk_target"]["k_ppm"] == 200


def test_ingest_omits_optional_agronomy_calc_fields_when_absent(client: TestClient):
    create = client.post("/v1/sensors/events", json=_sensor_payload())
    assert create.status_code == 201
    body = create.json()
    assert body["weather"] is None
    assert body["zone_area_m2"] is None
    assert body["crop_kc"] is None
    assert body["npk_target"] is None


def _sensor_payload() -> dict:
    return {
        "device_id": "test-device",
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "crop": "tomato",
        "growth_stage": "flowering",
        "air_temperature_c": 28.5,
        "humidity_pct": 72.0,
        "ec_ms_cm": 2.8,
        "ph": 6.2,
        "soil_moisture_pct": 45.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def test_ingest_rejects_missing_or_wrong_key_when_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")

    no_auth = client.post("/v1/sensors/events", json=_sensor_payload())
    assert no_auth.status_code == 401

    wrong_auth = client.post(
        "/v1/sensors/events",
        json=_sensor_payload(),
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert wrong_auth.status_code == 401


def test_ingest_accepts_correct_key_when_configured(client: TestClient, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret-key")

    response = client.post(
        "/v1/sensors/events",
        json=_sensor_payload(),
        headers={"Authorization": "Bearer secret-key"},
    )
    assert response.status_code == 201


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("humidity_pct", 101.0),
        ("soil_moisture_pct", -0.1),
        ("ph", 14.1),
        ("ec_ms_cm", 20.1),
        ("air_temperature_c", -40.1),
    ],
)
def test_rejects_sensor_values_outside_hardware_contract(client: TestClient, field: str, value: float):
    payload = {
        "device_id": "test-device",
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "air_temperature_c": 25.0,
        "humidity_pct": 60.0,
        "ec_ms_cm": 2.0,
        "ph": 6.0,
        "soil_moisture_pct": 45.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload[field] = value

    response = client.post("/v1/sensors/events", json=payload)

    assert response.status_code == 422


def test_calibration_and_corrected_do_not_mutate_raw(client: TestClient):
    event = client.post("/v1/sensors/events", json=_sensor_payload()).json()
    raw_ph = event["ph"]
    calibration = {
        "device_id": "test-device",
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "sensor_id": "ph-probe-01",
        "measurement": "ph",
        "method": "two_point_buffer",
        "points": [{"reference": 4.0, "raw": 1.1}, {"reference": 7.0, "raw": 2.0}],
        "coefficients": {"offset": 0.1, "slope": 1.0},
        "uncertainty": {"offset_sigma": 0.02},
        "performed_at": datetime.now(timezone.utc).isoformat(),
        "performed_by": "operator",
    }
    created = client.post("/v1/sensors/calibrations", json=calibration)
    assert created.status_code == 201
    cal_id = created.json()["id"]
    assert client.get("/v1/sensors/calibrations").json()["count"] == 1

    missing = client.post(
        "/v1/sensors/corrected-observations",
        json={
            "device_id": "test-device",
            "farm_id": "demo-farm",
            "zone_id": "greenhouse-a",
            "sensor_id": "ph-probe-01",
            "measurement": "ph",
            "raw_value": 6.8,
            "corrected_value": 6.5,
            "uncertainty": 0.1,
            "calibration_event_id": "missing",
            "method": "response_inverse_v0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert missing.status_code == 400

    corrected = client.post(
        "/v1/sensors/corrected-observations",
        json={
            "device_id": "test-device",
            "farm_id": "demo-farm",
            "zone_id": "greenhouse-a",
            "sensor_id": "ph-probe-01",
            "measurement": "ph",
            "raw_value": 6.8,
            "corrected_value": 6.5,
            "uncertainty": 0.1,
            "calibration_event_id": cal_id,
            "method": "response_inverse_v0",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert corrected.status_code == 201
    assert corrected.json()["quality"] == "corrected"
    assert client.get("/v1/sensors/events/latest").json()["ph"] == raw_ph
    assert client.get("/v1/sensors/corrected-observations").json()["count"] == 1
    ranking = client.get("/v1/sensors/recalibrate-next", params={"budget": 2}).json()
    assert ranking["budget"] == 2
    assert "suggestions" in ranking


def test_recalibrate_ranking_boosts_sqi_labels(client: TestClient):
    client.post("/v1/sensors/observations", json=observation_payload(device_id="probe-a", sensor_id="ph-a"))
    client.post("/v1/sensors/observations", json=observation_payload(device_id="probe-b", sensor_id="ph-b"))
    boosted = client.post(
        "/v1/sensors/recalibrate-next?budget=2",
        json={"quality_by_device": {"probe-a": ["baseline_drift_possible", "stuck_value"]}},
    )
    assert boosted.status_code == 200
    suggestions = boosted.json()["suggestions"]
    assert suggestions
    assert suggestions[0]["device_id"] == "probe-a"
    assert suggestions[0]["reason"] == "sqi_warn_fault"


def test_schema_version_defaults_to_1_0_for_legacy_senders(client):
    response = client.post("/v1/sensors/events", json=_sensor_payload())
    assert response.status_code == 201
    assert response.json()["schema_version"] == "1.0"
    assert client.get("/v1/sensors/events/latest").json()["schema_version"] == "1.0"


@pytest.mark.parametrize("version", ["1.0", "1.3", "1.12"])
def test_schema_version_accepts_any_1_x(client, version):
    response = client.post("/v1/sensors/events", json={**_sensor_payload(), "schema_version": version})
    assert response.status_code == 201
    assert response.json()["schema_version"] == version


@pytest.mark.parametrize("version", ["2.0", "0.9", "1", "v1.0", "1.0.0", 1.0, True, ""])
def test_schema_version_rejects_other_majors_and_malformed(client, version):
    payload = {**_sensor_payload(), "schema_version": version}
    assert client.post("/v1/sensors/events", json=payload).status_code == 422
    obs = observation_payload(schema_version=version)
    assert client.post("/v1/sensors/observations", json=obs).status_code == 422


def test_observation_keeps_schema_version(client):
    response = client.post("/v1/sensors/observations", json=observation_payload(schema_version="1.1"))
    assert response.status_code == 201
    assert response.json()["schema_version"] == "1.1"
    assert client.post("/v1/sensors/observations", json=observation_payload()).json()["schema_version"] == "1.0"


def test_mqtt_rejects_unsupported_major_without_storing(client):
    import json
    ingest = MqttIngestClient()
    payload = {**_sensor_payload(), "farm_id": "farm", "zone_id": "a", "device_id": "node",
               "timestamp": datetime.now(timezone.utc).isoformat(), "schema_version": "2.0"}
    message = SimpleNamespace(topic="pomona/farm/a/sensor/node/state",
                              payload=json.dumps(payload).encode(), retain=False)
    ingest._on_message(None, None, message)
    assert event_store.count() == 0
    ok = SimpleNamespace(topic=message.topic, payload=json.dumps({**payload, "schema_version": "1.0"}).encode(), retain=False)
    ingest._on_message(None, None, ok)
    assert event_store.count() == 1


def _partial_payload(**updates) -> dict:
    """A full packet whose EC probe did not report (absent), plus any updates (null = reported as not read)."""
    payload = _sensor_payload()
    del payload["ec_ms_cm"]
    return {**payload, **updates}


@pytest.mark.parametrize("missing", [{"ec_ms_cm": None}, {}])
def test_partial_packet_is_stored_and_returned_with_none_over_http(client, caplog, missing):
    caplog.set_level("INFO")
    payload = _partial_payload(**missing)
    response = client.post("/v1/sensors/events", json=payload)
    assert response.status_code == 201
    assert response.json()["ec_ms_cm"] is None
    assert response.json()["ph"] == 6.2  # Core never fills a default for the silent probe
    latest = client.get("/v1/sensors/events/latest").json()
    assert latest["ec_ms_cm"] is None and latest["schema_version"] == "1.0"
    assert client.get("/v1/sensors/events").json()["events"][0]["ec_ms_cm"] is None
    assert [record.getMessage() for record in caplog.records if "sensor event (http)" in record.getMessage()][0].endswith("ec=-")
    assert not [record for record in caplog.records if record.exc_info or record.levelname == "ERROR"]
    csv_text = client.get("/v1/sensors/export.csv").text
    header, row = csv_text.splitlines()[:2]
    assert row.split(",")[header.split(",").index("ec_ms_cm")] == ""


def test_partial_packet_is_stored_over_mqtt_without_a_traceback(client, caplog):
    import json
    caplog.set_level("INFO")
    ingest = MqttIngestClient()
    payload = {**_partial_payload(ec_ms_cm=None, humidity_pct=None), "farm_id": "farm", "zone_id": "a",
               "device_id": "node"}
    ingest._on_message(None, None, SimpleNamespace(topic="pomona/farm/a/sensor/node/state",
                                                   payload=json.dumps(payload).encode(), retain=False))
    assert event_store.count() == 1
    latest = event_store.latest_event()
    assert latest.ec_ms_cm is None and latest.humidity_pct is None and latest.ph == 6.2
    messages = [record.getMessage() for record in caplog.records if "sensor event device=" in record.getMessage()]
    assert messages and messages[0].endswith("ec=- temp=28.5 humidity=-")
    assert not [record for record in caplog.records if record.exc_info or record.levelname == "ERROR"]


def test_substrate_moisture_alone_is_a_reading(client):
    payload = {"device_id": "node", "farm_id": "farm", "zone_id": "a", "substrate_moisture_pct": 41.0,
               "timestamp": datetime.now(timezone.utc).isoformat()}
    response = client.post("/v1/sensors/events", json=payload)
    assert response.status_code == 201
    assert response.json()["soil_moisture_pct"] is None and response.json()["substrate_moisture_pct"] == 41.0


@pytest.mark.parametrize("readings", [
    {"ec_ms_cm": None},
    {},
    {field: None for field in ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph", "soil_moisture_pct",
                               "substrate_temperature_c", "substrate_moisture_pct")},
    {"weather": {"t_mean_c": 20, "t_min_c": 15, "t_max_c": 25, "rh_mean_pct": 60, "wind_speed_2m_ms": 2,
                 "solar_radiation_mj_m2_day": 15}, "zone_area_m2": 100.0, "crop_kc": 1.0},
])
def test_packet_without_a_reading_is_refused(client, readings):
    payload = {"device_id": "node", "farm_id": "farm", "zone_id": "a",
               "timestamp": datetime.now(timezone.utc).isoformat(), **readings}
    assert client.post("/v1/sensors/events", json=payload).status_code == 422
    assert event_store.count() == 0


@pytest.mark.parametrize("value", ["NaN", "Infinity", "-Infinity", True, "bad"])
def test_a_partial_packet_still_refuses_nan_and_non_numbers(client, value):
    assert client.post("/v1/sensors/events", json=_partial_payload(ph=value)).status_code == 422


def test_a_bare_nan_over_mqtt_is_refused_not_stored(client):
    import json
    ingest = MqttIngestClient()
    payload = {**_partial_payload(ph=float("nan")), "farm_id": "farm", "zone_id": "a", "device_id": "node"}
    ingest._on_message(None, None, SimpleNamespace(topic="pomona/farm/a/sensor/node/state",
                                                   payload=json.dumps(payload, allow_nan=True).encode(), retain=False))
    assert event_store.count() == 0
