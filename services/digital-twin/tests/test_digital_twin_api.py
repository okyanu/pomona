import sys
from pathlib import Path

from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

# Multiple services use an ``app`` package; isolate this service when tests
# are collected together with the safety-checker suite.
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import app


client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "pomona-digital-twin"


def test_forecast_is_bounded_and_not_a_command():
    response = client.post(
        "/v1/digital-twin/scenarios/simulate",
        json={
            "state": {"air_temperature_c": 24.0, "humidity_pct": 70.0, "substrate_moisture_pct": 40.0},
            "scenario": {"temperature_delta_c": 8.0, "humidity_delta_pct": 50.0, "irrigation_duration_min": 30},
            "horizon_steps": 4,
            "step_minutes": 15,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "forecast_only"
    assert len(body["trajectory"]) == 4
    assert body["trajectory"][-1]["humidity_pct"] == 100.0
    assert "Never execute" in body["safety_note"]
