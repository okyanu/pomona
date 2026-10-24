from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.config import Settings, settings
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
