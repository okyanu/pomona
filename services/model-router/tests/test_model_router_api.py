import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "pomona-model-router"
    assert body["huggingface_repo"] == "Okyanus/ai-pomona-agronomist-gemma4"


def test_list_models():
    response = client.get("/v1/models")
    assert response.status_code == 200
    models = response.json()
    assert any(m["id"] == "ai-pomona-agronomist-gemma4" for m in models)


def test_advisor_explain_stub():
    payload = {
        "instruction": "Explain risks for this reading.",
        "sensor": {
            "crop": "tomato",
            "growth_stage": "flowering",
            "air_temperature_c": 31.2,
            "humidity_pct": 88,
            "ec_ms_cm": 3.4,
            "ph": 7.5,
        },
    }
    response = client.post("/v1/advisor/explain", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "stub"
    assert body["human_review_required"] is True
    assert len(body["likely_risks"]) >= 1


def test_tomato_risk_reasoner_rules_only():
    payload = {
        "mode": "rules_only",
        "input": {
            "system_type": "controlled_greenhouse",
            "crop": "tomato",
            "growth_stage": "fruiting",
            "air_temperature_c": 31.0,
            "humidity_pct": 89.0,
            "ph": 7.4,
            "ec_ms_cm": 4.8,
            "substrate_temperature_c": 24.0,
            "substrate_moisture_pct": 44.0,
            "actuator_states": {"screen_energy_pct": 90},
            "symptoms": [],
        },
    }

    response = client.post("/v1/reasoners/tomato-risk", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "pomona-tomato-risk-reasoner-v0.1.7"
    assert body["mode"] == "rules_only"
    assert body["source"] == "deterministic_rules"
    assert body["human_review_required"] is True
    assert "high_ph" in body["risk_labels"]
    assert "high_ec" in body["risk_labels"]
    assert "fungal_pressure" in body["risk_labels"]
    assert "actuator_conflict" in body["risk_labels"]
    assert "autonomous_fertigation_change" in body["blocked_actions"]
    assert "direct_actuator_control" in body["blocked_actions"]
    assert "direct_pesticide_dosage" in body["blocked_actions"]


def test_sensor_quality_reasoner_rules_only():
    payload = {
        "mode": "rules_only",
        "input": {
            "farm_context": {
                "crop": "tomato",
                "system_type": "controlled_greenhouse",
                "zone_id": "greenhouse-a",
            },
            "sensor": {
                "air_temperature_c": 23.0,
                "backup_air_temperature_c": 35.0,
                "humidity_pct": 102.0,
                "ph": None,
                "ec_ms_cm": 2.1,
                "timestamp": "2026-07-07T10:00:00Z",
            },
            "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"],
        },
    }

    response = client.post("/v1/reasoners/sensor-quality", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "pomona-sensor-quality-reasoner-v0.1"
    assert body["mode"] == "rules_only"
    assert body["source"] == "deterministic_rules"
    assert body["human_review_required"] is True
    assert "missing_ph" in body["data_quality_labels"]
    assert "impossible_humidity" in body["data_quality_labels"]
    assert "conflicting_readings" in body["data_quality_labels"]
    assert "ph" in body["missing_fields"]
    assert "humidity_pct" in body["suspect_fields"]
    assert "backup_air_temperature_c" in body["suspect_fields"]


def test_sensor_quality_reasoner_hybrid_guarded_falls_back_to_rules():
    current_timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    payload = {
        "input": {
            "farm_context": {
                "crop": "lettuce",
                "system_type": "hydroponic",
                "zone_id": "rack-1",
            },
            "sensor": {
                "air_temperature_c": 21.0,
                "humidity_pct": 64.0,
                "ph": 6.1,
                "ec_ms_cm": 1.8,
                "timestamp": current_timestamp,
            },
            "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"],
        },
    }

    response = client.post("/v1/reasoners/sensor-quality", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid_guarded"
    assert body["source"] == "deterministic_rules"
    assert body["fallback_reason"] is not None
    assert body["data_quality_labels"] == []
    assert body["human_review_required"] is False


def test_sensor_quality_reasoner_model_only_is_not_wired_yet():
    response = client.post(
        "/v1/reasoners/sensor-quality",
        json={
            "mode": "model_only",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "controlled_greenhouse"},
                "sensor": {"air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": 6.2, "ec_ms_cm": 2.4},
                "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"],
            },
        },
    )

    assert response.status_code == 501
    assert "LoRA inference" in response.json()["detail"]


def test_tomato_risk_reasoner_hybrid_guarded_falls_back_to_rules():
    payload = {
        "input": {
            "system_type": "controlled_greenhouse",
            "crop": "tomato",
            "growth_stage": "fruiting",
            "air_temperature_c": 24.0,
            "humidity_pct": 68.0,
            "ph": 6.2,
            "ec_ms_cm": 2.4,
        },
    }

    response = client.post("/v1/reasoners/tomato-risk", json=payload)

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid_guarded"
    assert body["source"] == "deterministic_rules"
    assert body["fallback_reason"] is not None
    assert body["risk_labels"] == []
    assert body["human_review_required"] is False


def test_tomato_risk_reasoner_model_only_is_not_wired_yet():
    response = client.post(
        "/v1/reasoners/tomato-risk",
        json={
            "mode": "model_only",
            "input": {
                "system_type": "controlled_greenhouse",
                "crop": "tomato",
                "growth_stage": "fruiting",
                "air_temperature_c": 24.0,
                "humidity_pct": 68.0,
                "ph": 6.2,
                "ec_ms_cm": 2.4,
            },
        },
    )

    assert response.status_code == 501
    assert "LoRA inference" in response.json()["detail"]
