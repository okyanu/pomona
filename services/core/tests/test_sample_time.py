from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.config import Settings, settings
from app.farm_time import format_offset, next_offset_change
from app.main import app
from app.mqtt_client import MqttIngestClient
from app.schemas import SensorEvent
from app.store import event_store, SensorEventStore


@pytest.fixture(autouse=True)
def clear_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "test.db")
    SensorEventStore(db_path=event_store._db_path)
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def event_payload(**updates):
    return {"device_id": "node", "farm_id": "farm", "zone_id": "a", "crop": "tomato", "growth_stage": "flowering",
            "air_temperature_c": 25.0, "humidity_pct": 60.0, "ec_ms_cm": 2.0, "ph": 6.0, "soil_moisture_pct": 40.0,
            "timestamp": datetime.now(timezone.utc).isoformat(), **updates}


def observation_payload(**updates):
    return {"device_id": "node", "farm_id": "farm", "zone_id": "a", "sensor_id": "temp",
            "measurement": "air_temperature_c", "unit": "C", "value": 24,
            "timestamp": datetime.now(timezone.utc).isoformat(), **updates}


def corrected_payload(calibration_id, **updates):
    return {"device_id": "node", "farm_id": "farm", "zone_id": "a", "sensor_id": "ph1", "measurement": "ph",
            "raw_value": 6.5, "corrected_value": 6.4, "calibration_event_id": calibration_id, "method": "two_point",
            "timestamp": datetime.now(timezone.utc).isoformat(), **updates}


def calibration(client):
    body = {"device_id": "node", "farm_id": "farm", "zone_id": "a", "sensor_id": "ph1", "measurement": "ph",
            "method": "two_point", "points": [{"reference": 7.0, "raw": 6.9}],
            "performed_at": datetime.now(timezone.utc).isoformat()}
    return client.post("/v1/sensors/calibrations", json=body).json()["id"]


def test_event_without_timestamp_is_rejected_over_http(client):
    payload = event_payload()
    del payload["timestamp"]
    response = client.post("/v1/sensors/events", json=payload)
    assert response.status_code == 422
    assert "timestamp" in response.text
    assert event_store.count() == 0


def test_event_without_timestamp_is_rejected_over_mqtt(client):
    payload = event_payload()
    del payload["timestamp"]
    MqttIngestClient()._on_message(None, None, SimpleNamespace(
        topic="pomona/farm/a/sensor/node/state", payload=json.dumps(payload).encode(), retain=False))
    assert event_store.count() == 0


@pytest.mark.parametrize("stamp", ["1970-01-01T00:00:00Z", "2000-01-01T00:00:00Z", "2019-12-31T23:59:59Z"])
def test_dead_clock_samples_are_rejected(client, stamp):
    response = client.post("/v1/sensors/events", json=event_payload(timestamp=stamp))
    assert response.status_code == 422
    assert "2020-01-01T00:00:00+00:00" in response.text and "RTC battery" in response.text
    assert client.post("/v1/sensors/observations", json=observation_payload(timestamp=stamp)).status_code == 422
    assert client.post("/v1/sensors/corrected-observations",
                       json=corrected_payload(calibration(client), timestamp=stamp)).status_code == 422
    assert event_store.count() == 0 and event_store.list_observations() == [] and event_store.list_corrected() == []


def test_dead_clock_sample_over_mqtt_is_not_stored(client):
    payload = event_payload(timestamp="1970-01-01T00:00:00Z")
    MqttIngestClient()._on_message(None, None, SimpleNamespace(
        topic="pomona/farm/a/sensor/node/state", payload=json.dumps(payload).encode(), retain=False))
    assert event_store.count() == 0


def test_timestamp_just_after_the_floor_is_accepted(client):
    stamp = "2020-01-01T00:00:01Z"
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=stamp)).status_code == 201
    assert client.post("/v1/sensors/observations", json=observation_payload(timestamp=stamp)).status_code == 201
    assert client.post("/v1/sensors/corrected-observations",
                       json=corrected_payload(calibration(client), timestamp=stamp)).status_code == 201


def test_floor_is_configurable(client, monkeypatch):
    stamp = "2021-06-01T00:00:00Z"
    monkeypatch.setattr(settings, "min_sample_time", datetime(2022, 1, 1, tzinfo=timezone.utc))
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=stamp)).status_code == 422
    monkeypatch.setattr(settings, "min_sample_time", datetime(2021, 1, 1, tzinfo=timezone.utc))
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=stamp)).status_code == 201


def test_floor_setting_must_be_timezone_aware():
    with pytest.raises(ValueError):
        Settings(min_sample_time="2020-01-01T00:00:00")
    assert Settings(min_sample_time="2021-01-01T00:00:00Z").min_sample_time == datetime(2021, 1, 1, tzinfo=timezone.utc)


def test_rows_stored_before_a_floor_change_still_load(client, monkeypatch):
    old = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=old)).status_code == 201
    assert client.post("/v1/sensors/observations", json=observation_payload(timestamp=old)).status_code == 201
    monkeypatch.setattr(settings, "min_sample_time", datetime.now(timezone.utc))
    assert len(event_store.list_events()) == 1 and len(event_store.list_observations()) == 1
    assert client.get("/v1/sensors/events").status_code == 200
    assert client.get("/v1/sensors/events/latest").status_code == 200
    assert client.get("/v1/sensors/export.csv").status_code == 200


def future(**delta):
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat()


def test_sample_four_hours_ahead_is_rejected_with_time_zone_wording(client):
    # Local Dubai time written as Z: the common ESP32 / spreadsheet mistake.
    stamp = future(hours=4)
    for path, payload in (("/v1/sensors/events", event_payload(timestamp=stamp)),
                          ("/v1/sensors/observations", observation_payload(timestamp=stamp)),
                          ("/v1/sensors/corrected-observations", corrected_payload(calibration(client), timestamp=stamp))):
        response = client.post(path, json=payload)
        assert response.status_code == 422
        assert "4.0 h ahead of Core's clock" in response.text
        assert "looks like a time-zone offset" in response.text and "+04:00" in response.text
    assert event_store.count() == 0 and event_store.list_observations() == [] and event_store.list_corrected() == []


def test_sample_ahead_by_an_odd_gap_just_says_the_clock_is_ahead(client):
    response = client.post("/v1/sensors/events", json=event_payload(timestamp=future(minutes=40, seconds=20)))
    assert response.status_code == 422
    assert "40 min ahead of Core's clock" in response.text and "time-zone" not in response.text


def test_sample_two_minutes_ahead_is_accepted(client):
    stamp = future(minutes=2)
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=stamp)).status_code == 201
    assert client.post("/v1/sensors/observations", json=observation_payload(timestamp=stamp)).status_code == 201


def test_future_limit_is_configurable_and_zero_disables_it(client, monkeypatch):
    stamp = future(hours=4)
    monkeypatch.setattr(settings, "max_future_sample_s", 0)
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=stamp)).status_code == 201
    monkeypatch.setattr(settings, "max_future_sample_s", 6 * 3600)
    assert client.post("/v1/sensors/observations", json=observation_payload(timestamp=stamp)).status_code == 201
    monkeypatch.setattr(settings, "max_future_sample_s", 60)
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=future(minutes=2))).status_code == 422


def test_future_limit_setting_cannot_be_negative():
    with pytest.raises(ValueError):
        Settings(max_future_sample_s=-1)
    assert Settings().max_future_sample_s == 300


def test_rows_stored_before_a_limit_change_still_load(client, monkeypatch):
    stamp = future(hours=4)
    monkeypatch.setattr(settings, "max_future_sample_s", 0)
    assert client.post("/v1/sensors/events", json=event_payload(timestamp=stamp)).status_code == 201
    assert client.post("/v1/sensors/observations", json=observation_payload(timestamp=stamp)).status_code == 201
    monkeypatch.setattr(settings, "max_future_sample_s", 300)
    assert len(event_store.list_events()) == 1 and len(event_store.list_observations()) == 1
    assert client.get("/v1/sensors/events").status_code == 200
    assert client.get("/v1/sensors/export.csv").status_code == 200


def test_future_sample_over_mqtt_is_not_stored(client):
    payload = event_payload(timestamp=future(hours=4))
    MqttIngestClient()._on_message(None, None, SimpleNamespace(
        topic="pomona/farm/a/sensor/node/state", payload=json.dumps(payload).encode(), retain=False))
    observation = observation_payload(timestamp=future(hours=4))
    MqttIngestClient()._on_message(None, None, SimpleNamespace(
        topic="pomona/farm/a/sensor/node/observation", payload=json.dumps(observation).encode(), retain=False))
    assert event_store.count() == 0 and event_store.list_observations() == []


def test_farm_timezone_must_be_a_known_name():
    with pytest.raises(ValueError, match="FARM_TIMEZONE 'Asia/Dubay'"):
        Settings(farm_timezone="Asia/Dubay")
    with pytest.raises(ValueError):
        Settings(farm_timezone="")
    assert Settings().farm_timezone == "UTC"
    assert Settings(farm_timezone="Europe/Berlin").farm_timezone == "Europe/Berlin"


def test_health_reports_a_zone_without_clock_changes(client, monkeypatch):
    monkeypatch.setattr(settings, "farm_timezone", "Asia/Dubai")
    time = client.get("/health").json()["time"]
    assert time["farm_timezone"] == "Asia/Dubai" and time["utc_offset_now"] == "+04:00"
    assert time["next_offset_change"] is None and time["offset_after_change"] is None
    assert time["tzdata_version"] is None or isinstance(time["tzdata_version"], str)


def test_health_reports_the_next_clock_change(client, monkeypatch):
    monkeypatch.setattr(settings, "farm_timezone", "Europe/Berlin")
    time = client.get("/health").json()["time"]
    assert time["utc_offset_now"] in ("+01:00", "+02:00")
    change = datetime.fromisoformat(time["next_offset_change"])
    assert datetime.now(timezone.utc) < change < datetime.now(timezone.utc) + timedelta(days=200)
    assert change.minute == 0 and time["offset_after_change"] == {"+01:00": "+02:00", "+02:00": "+01:00"}[time["utc_offset_now"]]


def test_next_offset_change_finds_the_exact_minute():
    start = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    instant, offset = next_offset_change(ZoneInfo("Europe/Berlin"), start)
    assert instant == datetime(2027, 3, 28, 1, 0, tzinfo=timezone.utc) and format_offset(offset) == "+02:00"
    assert next_offset_change(ZoneInfo("Asia/Kolkata"), start) is None
    assert format_offset(start.astimezone(ZoneInfo("Asia/Kolkata")).utcoffset()) == "+05:30"
    assert format_offset(start.astimezone(ZoneInfo("America/St_Johns")).utcoffset()) == "-03:30"
