import sys
from pathlib import Path

from fastapi.testclient import TestClient


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import app  # noqa: E402


client = TestClient(app)


def base_input():
    return {
        "system_type": "controlled_greenhouse",
        "crop": "tomato",
        "growth_stage": "fruiting",
        "air_temperature_c": 24.0,
        "humidity_pct": 68.0,
        "co2_ppm": 600,
        "light_lux": None,
        "light_ppfd": 350,
        "ph": 6.2,
        "ec_ms_cm": 2.4,
        "tds_ppm": None,
        "water_temperature_c": 21.0,
        "substrate_temperature_c": 23.0,
        "substrate_moisture_pct": 45.0,
        "actuator_states": {},
        "symptoms": [],
    }


def test_health():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "pomona-safety-checker"
    assert body["ruleset"] == "tomato-greenhouse-v0.1"


def test_tomato_risk_check_normal_reading():
    response = client.post("/v1/tomato-risk/check", json={"input": base_input()})

    assert response.status_code == 200
    body = response.json()
    assert body["risk_labels"] == []
    assert body["blocked_actions"] == []
    assert body["human_review_required"] is False
    assert body["safe_next_checks"] == ["continue routine monitoring"]


def test_tomato_risk_check_blocks_unsafe_fungal_path():
    reading = base_input()
    reading["humidity_pct"] = 90.0

    response = client.post("/v1/tomato-risk/check", json={"input": reading})

    assert response.status_code == 200
    body = response.json()
    assert body["risk_labels"] == ["fungal_pressure"]
    assert body["blocked_actions"] == [
        "direct_pesticide_dosage",
        "definitive_disease_diagnosis",
        "unsafe_chemical_recommendation",
    ]
    assert body["human_review_required"] is True


def test_tomato_risk_check_requires_input_object():
    response = client.post("/v1/tomato-risk/check", json={})

    assert response.status_code == 422


def test_actuator_command_gate_blocks_direct_control():
    response = client.post(
        "/v1/actuator-command-gate/check",
        json={
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "controlled_greenhouse"},
                "sensor": base_input(),
                "sensor_quality": {"data_quality_labels": [], "missing_fields": [], "suspect_fields": []},
                "risk_labels": ["heat_stress"],
                "actor": "automation_engine",
                "proposed_command": {
                    "action_type": "open_vent",
                    "description": "Open the roof vents automatically for 20 minutes.",
                },
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision"] == "blocked"
    assert body["blocked_actions"] == ["direct_actuator_control"]
    assert body["human_approval_required"] is True
