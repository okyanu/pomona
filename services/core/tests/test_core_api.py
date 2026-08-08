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

from app.main import app
from app.store import event_store


@pytest.fixture(autouse=True)
def clear_store():
    event_store.clear()
    yield
    event_store.clear()


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
