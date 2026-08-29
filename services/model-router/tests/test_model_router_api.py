import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
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


def test_advisor_explain_uses_guarded_context():
    response = client.post(
        "/v1/advisor/explain",
        json={
            "instruction": "Explain the guarded result.",
            "sensor": {"humidity_pct": 90.0},
            "guarded_context": {
                "blocked_actions": ["direct_actuator_control"],
                "safe_next_checks": ["review ventilation state with a human operator"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "direct_actuator_control" in body["explanation"]
    assert "review ventilation state with a human operator" in body["safe_checks"]


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
    assert "requires a configured" in response.json()["detail"]


def test_tomato_risk_reasoner_model_only_uses_guarded_ollama_contract(monkeypatch):
    async def fungal_pressure(*args, **kwargs):
        return ["fungal_pressure"]

    monkeypatch.setattr("app.tomato_reasoner.ollama_chat_json_array", fungal_pressure)
    response = client.post(
        "/v1/reasoners/tomato-risk",
        json={
            "mode": "model_only",
            "backend": "ollama",
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

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "model_only"
    assert body["backend"] == "ollama"
    assert body["source"] == "ollama"
    assert body["risk_labels"] == ["fungal_pressure"]
    assert "direct_pesticide_dosage" in body["blocked_actions"]
    assert "definitive_disease_diagnosis" in body["blocked_actions"]
    assert body["human_review_required"] is True


def test_water_irrigation_reasoner_rules_only():
    response = client.post(
        "/v1/reasoners/water-irrigation-risk",
        json={
            "mode": "rules_only",
            "backend": "rules",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"substrate_moisture_pct": 24.0, "timestamp": "2026-07-12T10:00:00Z"},
                "expected_fields": ["substrate_moisture_pct"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "deterministic_rules"
    assert body["irrigation_risk_labels"] == ["low_moisture", "irrigation_underwatering"]
    assert body["blocked_actions"] == ["autonomous_irrigation_change", "irrigation_schedule_change"]
    assert body["human_review_required"] is True


def test_water_irrigation_hybrid_falls_back_when_ollama_is_unavailable(monkeypatch):
    async def unavailable(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("app.water_irrigation.ollama_chat_json", unavailable)
    response = client.post(
        "/v1/reasoners/water-irrigation-risk",
        json={
            "backend": "ollama",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"substrate_moisture_pct": 84.0},
                "expected_fields": ["substrate_moisture_pct"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "deterministic_rules"
    assert "used deterministic rules" in body["fallback_reason"]
    assert body["human_review_required"] is True


def test_water_irrigation_hybrid_rules_override_unsafe_normal_model_output(monkeypatch):
    async def unsafe_normal(*args, **kwargs):
        return {
            "irrigation_risk_labels": [],
            "missing_fields": [],
            "suspect_fields": [],
            "safe_next_checks": ["continue routine irrigation monitoring"],
            "blocked_actions": [],
            "human_review_required": False,
            "rationale": "Moisture telemetry is present and inside expected operating range.",
        }

    monkeypatch.setattr("app.water_irrigation.ollama_chat_json", unsafe_normal)
    response = client.post(
        "/v1/reasoners/water-irrigation-risk",
        json={
            "backend": "ollama",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"substrate_moisture_pct": 84.0},
                "expected_fields": ["substrate_moisture_pct"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "ollama_guarded"
    assert "high_moisture" in body["irrigation_risk_labels"]
    assert "autonomous_irrigation_change" in body["blocked_actions"]
    assert "irrigation_schedule_change" in body["blocked_actions"]
    assert body["human_review_required"] is True
    assert "continue routine irrigation monitoring" not in body["safe_next_checks"]


def test_water_irrigation_hybrid_drops_model_false_positive(monkeypatch):
    async def false_positive(*args, **kwargs):
        return {
            "irrigation_risk_labels": ["low_moisture", "irrigation_underwatering"],
            "missing_fields": [],
            "suspect_fields": ["substrate_moisture_pct"],
            "safe_next_checks": ["confirm low moisture with a second reading before changing irrigation"],
            "blocked_actions": ["autonomous_irrigation_change", "irrigation_schedule_change"],
            "human_review_required": True,
            "rationale": "Model-only false positive.",
        }

    monkeypatch.setattr("app.water_irrigation.ollama_chat_json", false_positive)
    response = client.post(
        "/v1/reasoners/water-irrigation-risk",
        json={
            "backend": "ollama",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"substrate_moisture_pct": 50.0},
                "expected_fields": ["substrate_moisture_pct"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "ollama_guarded"
    assert body["irrigation_risk_labels"] == []
    assert body["blocked_actions"] == []
    assert body["safe_next_checks"] == ["continue routine irrigation monitoring"]
    assert body["human_review_required"] is False


def test_water_irrigation_model_only_rejects_invalid_runtime_output(monkeypatch):
    async def invalid(*args, **kwargs):
        return {"irrigation_risk_labels": ["invented_label"]}

    monkeypatch.setattr("app.water_irrigation.ollama_chat_json", invalid)
    response = client.post(
        "/v1/reasoners/water-irrigation-risk",
        json={
            "mode": "model_only",
            "backend": "ollama",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"substrate_moisture_pct": 50.0},
                "expected_fields": ["substrate_moisture_pct"],
            },
        },
    )

    assert response.status_code == 503
    assert "missing keys" in response.json()["detail"]


def test_actuator_command_gate_reasoner_rules_only_blocks_actuator():
    response = client.post(
        "/v1/reasoners/actuator-command-gate",
        json={
            "mode": "rules_only",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"substrate_moisture_pct": 42.0},
                "risk_labels": [],
                "actor": "assistant_model",
                "proposed_command": {"action_type": "start_irrigation"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "pomona-actuator-command-gate-reasoner-v0.1"
    assert body["source"] == "deterministic_safety_rules"
    assert body["decision"] == "blocked"
    assert "direct_actuator_control_request" in body["gate_labels"]
    assert body["blocked_actions"] == ["direct_actuator_control"]
    assert body["human_approval_required"] is True


def test_actuator_command_gate_reasoner_hybrid_is_advisory_fallback():
    response = client.post(
        "/v1/reasoners/actuator-command-gate",
        json={
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "controlled_greenhouse"},
                "sensor": {},
                "risk_labels": [],
                "actor": "assistant_model",
                "proposed_command": {"action_type": "manual_check"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "hybrid_guarded"
    assert body["fallback_reason"] is not None
    assert body["decision"] == "allowed"


def test_actuator_command_gate_reasoner_model_only_is_not_wired():
    response = client.post(
        "/v1/reasoners/actuator-command-gate",
        json={
            "mode": "model_only",
            "input": {"proposed_command": {"action_type": "manual_check"}},
        },
    )

    assert response.status_code == 501
    assert "LoRA inference" in response.json()["detail"]


def test_safety_triage_reasoner_blocks_chemical_and_actuator_request():
    response = client.post(
        "/v1/reasoners/safety-triage",
        json={
            "mode": "rules_only",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "controlled_greenhouse"},
                "sensor": {"humidity_pct": 91.0},
                "risk_labels": ["fungal_pressure"],
                "actor": "assistant_model",
                "proposed_action": "Apply pesticide now and close vent.",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["model_id"] == "pomona-safety-triage-reasoner-v0.1"
    assert body["source"] == "deterministic_safety_rules"
    assert "unsafe_chemical_recommendation" in body["safety_labels"]
    assert "direct_actuator_control_request" in body["safety_labels"]
    assert "direct_pesticide_dosage" in body["blocked_actions"]
    assert "direct_actuator_control" in body["blocked_actions"]
    assert body["human_review_required"] is True


def test_safety_triage_reasoner_allows_manual_check():
    response = client.post(
        "/v1/reasoners/safety-triage",
        json={
            "input": {
                "farm_context": {"crop": "lettuce", "system_type": "hydroponic"},
                "sensor": {"ph": 6.1},
                "risk_labels": [],
                "actor": "human_operator",
                "proposed_action": {"action_type": "manual_check"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["safety_labels"] == ["safe_manual_check"]
    assert body["blocked_actions"] == []
    assert body["human_review_required"] is False


def test_safety_triage_reasoner_model_only_is_not_wired():
    response = client.post(
        "/v1/reasoners/safety-triage",
        json={"mode": "model_only", "input": {"proposed_action": "Continue monitoring."}},
    )

    assert response.status_code == 501
    assert "LoRA inference" in response.json()["detail"]


def test_nutrient_ph_ec_reasoner_rules_only_blocks_high_ec():
    response = client.post(
        "/v1/reasoners/nutrient-ph-ec",
        json={
            "mode": "rules_only",
            "input": {
                "farm_context": {"system_type": "controlled_greenhouse", "crop": "tomato"},
                "sensor": {"ph": 7.4, "ec_ms_cm": 4.8},
                "expected_fields": ["ph", "ec_ms_cm"],
            },
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["nutrient_risk_labels"] == ["high_ph", "high_ec", "nutrient_uptake_issue"]
    assert body["blocked_actions"] == ["autonomous_fertigation_change"]
    assert body["human_review_required"] is True


def test_nutrient_ph_ec_reasoner_missing_fields():
    response = client.post(
        "/v1/reasoners/nutrient-ph-ec",
        json={"input": {"sensor": {"ph": None, "ec_ms_cm": 1.5}, "expected_fields": ["ph", "ec_ms_cm"]}},
    )
    assert response.status_code == 200
    body = response.json()
    assert "missing_critical_data" in body["nutrient_risk_labels"]
    assert body["missing_fields"] == ["ph"]
    assert body["blocked_actions"] == ["autonomous_fertigation_change"]


def test_nutrient_ph_ec_reasoner_model_only_is_not_wired():
    response = client.post(
        "/v1/reasoners/nutrient-ph-ec",
        json={"mode": "model_only", "input": {}},
    )
    assert response.status_code == 501


def test_nutrient_ph_ec_hybrid_drops_model_false_positive(monkeypatch):
    async def false_positive(*args, **kwargs):
        return {
            "nutrient_risk_labels": ["high_ph", "nutrient_uptake_issue"],
            "missing_fields": [],
            "safe_next_checks": ["repeat pH measurement with a calibrated meter"],
            "blocked_actions": ["autonomous_fertigation_change"],
            "human_review_required": True,
            "rationale": "Model-only false positive.",
        }

    monkeypatch.setattr("app.nutrient_ph_ec.ollama_chat_json", false_positive)
    response = client.post(
        "/v1/reasoners/nutrient-ph-ec",
        json={
            "mode": "hybrid_guarded",
            "backend": "ollama",
            "input": {
                "farm_context": {"system_type": "controlled_greenhouse", "crop": "tomato"},
                "sensor": {"ph": 6.2, "ec_ms_cm": 2.4},
                "expected_fields": ["ph", "ec_ms_cm"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "ollama_guarded"
    assert body["nutrient_risk_labels"] == []
    assert body["blocked_actions"] == []
    assert body["human_review_required"] is False


def test_nutrient_ph_ec_model_only_uses_validated_ollama_output(monkeypatch):
    async def high_ph(*args, **kwargs):
        return {
            "nutrient_risk_labels": ["high_ph", "nutrient_uptake_issue"],
            "missing_fields": [],
            "safe_next_checks": ["repeat pH measurement with a calibrated meter"],
            "blocked_actions": ["autonomous_fertigation_change"],
            "human_review_required": True,
            "rationale": "High pH needs manual verification.",
        }

    monkeypatch.setattr("app.nutrient_ph_ec.ollama_chat_json", high_ph)
    response = client.post(
        "/v1/reasoners/nutrient-ph-ec",
        json={
            "mode": "model_only",
            "backend": "ollama",
            "input": {
                "farm_context": {"system_type": "controlled_greenhouse", "crop": "tomato"},
                "sensor": {"ph": 7.4, "ec_ms_cm": 2.4},
                "expected_fields": ["ph", "ec_ms_cm"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "ollama"
    assert body["nutrient_risk_labels"] == ["high_ph", "nutrient_uptake_issue"]
    assert body["blocked_actions"] == ["autonomous_fertigation_change"]
    assert body["human_review_required"] is True


def test_nutrient_ph_ec_rejects_schema_valid_but_inconsistent_model_output(monkeypatch):
    async def inconsistent(*args, **kwargs):
        return {
            "nutrient_risk_labels": ["nutrient_uptake_issue"],
            "missing_fields": ["ph", "ec_ms_cm"],
            "safe_next_checks": ["verify pH and EC manually"],
            "blocked_actions": ["autonomous_fertigation_change"],
            "human_review_required": False,
            "rationale": "Internally inconsistent model response.",
        }

    monkeypatch.setattr("app.nutrient_ph_ec.ollama_chat_json", inconsistent)
    response = client.post(
        "/v1/reasoners/nutrient-ph-ec",
        json={
            "mode": "model_only",
            "backend": "ollama",
            "input": {
                "farm_context": {"system_type": "controlled_greenhouse", "crop": "tomato"},
                "sensor": {"ph": 6.2, "ec_ms_cm": 2.4},
                "expected_fields": ["ph", "ec_ms_cm"],
            },
        },
    )

    assert response.status_code == 503
    assert "must require human review" in response.json()["detail"]


def test_shared_reasoner_chain_normal_packet():
    response = client.post(
        "/v1/reasoners/shared-chain",
        json={
            "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"},
            "sensor": {"air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": 6.2, "ec_ms_cm": 0.18, "substrate_moisture_pct": 52.0, "substrate_temperature_c": 23.0},
            "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"],
            "mode": "rules_only",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["sensor_quality"]["data_quality_labels"] == []
    assert body["water_irrigation"]["irrigation_risk_labels"] == []
    assert body["actuator_safety"]["decision"] == "allowed"
    assert body["human_review_required"] is False


def test_shared_reasoner_chain_missing_data_blocks_command():
    response = client.post(
        "/v1/reasoners/shared-chain",
        json={
            "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
            "sensor": {"air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": None, "ec_ms_cm": 0.18, "substrate_moisture_pct": 24.0},
            "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"],
            "proposed_command": {"action_type": "start_irrigation"},
            "mode": "hybrid_guarded",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "missing_ph" in body["sensor_quality"]["data_quality_labels"]
    assert "low_moisture" in body["water_irrigation"]["irrigation_risk_labels"]
    assert body["actuator_safety"]["decision"] == "blocked"
    assert "direct_actuator_control" in body["blocked_actions"]
    assert body["human_review_required"] is True


def test_pipeline_evaluate_integrates_specialists_and_audit_output():
    response = client.post(
        "/v1/pipeline/evaluate",
        json={
            "scenario_id": "test-tomato-risk",
            "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"},
            "sensor": {
                "air_temperature_c": 33.0,
                "humidity_pct": 80.0,
                "ph": 5.2,
                "ec_ms_cm": 3.8,
                "substrate_moisture_pct": 27.0,
                "substrate_temperature_c": 27.0,
            },
            "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct", "substrate_temperature_c"],
            "proposed_command": {"action_type": "start_irrigation"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "deterministic_guarded_pipeline"
    assert body["pipeline_id"].startswith("pipeline-")
    assert body["sensor_quality"]["source"] == "deterministic_rules"
    assert body["sensor_quality"]["mode"] == "hybrid_guarded"
    assert "low_ph" in body["nutrient_ph_ec"]["nutrient_risk_labels"]
    assert body["nutrient_ph_ec"]["source"] == "deterministic_rules"
    assert body["nutrient_ph_ec"]["mode"] == "hybrid_guarded"
    assert "low_moisture" in body["water_irrigation"]["irrigation_risk_labels"]
    assert body["safety"]["decision"] == "blocked"
    assert body["safety_triage"]["source"] == "deterministic_safety_rules"
    assert body["safety_triage"]["human_review_required"] is True
    assert body["final_decision"]["human_review_required"] is True
    assert body["final_decision"]["blocked_actions"]


def test_pipeline_evaluate_normal_leafy_greens_is_routine():
    response = client.post(
        "/v1/pipeline/evaluate",
        json={
            "scenario_id": "test-lettuce-normal",
            "farm_context": {"crop": "lettuce", "system_type": "hydroponic", "zone_id": "rack-1"},
            "sensor": {"air_temperature_c": 21.0, "humidity_pct": 64.0, "ph": 6.1, "ec_ms_cm": 1.8, "water_temperature_c": 20.0},
            "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "water_temperature_c"],
            "proposed_command": {"action_type": "continue_monitoring"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["final_decision"]["risk_level"] == "routine"
    assert body["final_decision"]["blocked_actions"] == []
    assert body["final_decision"]["human_review_required"] is False


def test_pipeline_uses_configured_guarded_water_backend(monkeypatch):
    calls = {}

    async def configured_backend(input_data, mode, backend, model_id):
        calls.update({"mode": mode, "backend": backend, "model_id": model_id})
        return {
            "irrigation_risk_labels": [],
            "missing_fields": [],
            "suspect_fields": [],
            "safe_next_checks": ["continue routine irrigation monitoring"],
            "blocked_actions": [],
            "human_review_required": False,
            "rationale": "Guarded runtime normal result.",
            "model_id": model_id,
            "mode": mode,
            "backend": backend,
            "source": "ollama_guarded",
            "fallback_reason": None,
        }

    async def configured_nutrient_backend(input_data, mode, model_id, backend):
        return {
            "nutrient_risk_labels": [],
            "missing_fields": [],
            "safe_next_checks": ["continue routine nutrient monitoring"],
            "blocked_actions": [],
            "human_review_required": False,
            "rationale": "Guarded runtime normal result.",
            "model_id": model_id,
            "mode": mode,
            "backend": backend,
            "source": "ollama_guarded",
            "fallback_reason": None,
        }

    monkeypatch.setattr("app.pipeline.settings.reasoner_backend", "ollama")
    monkeypatch.setattr("app.pipeline.route_water_irrigation_reasoner", configured_backend)
    monkeypatch.setattr("app.pipeline.route_nutrient_ph_ec_reasoner", configured_nutrient_backend)
    response = client.post(
        "/v1/pipeline/evaluate",
        json={
            "scenario_id": "test-configured-water-runtime",
            "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
            "sensor": {"substrate_moisture_pct": 50.0},
            "expected_fields": ["substrate_moisture_pct"],
            "proposed_command": {"action_type": "continue_monitoring"},
        },
    )

    assert response.status_code == 200
    assert calls == {
        "mode": "hybrid_guarded",
        "backend": "ollama",
        "model_id": "pomona-water-irrigation-risk-reasoner-v0.1",
    }
    assert response.json()["water_irrigation"]["source"] == "ollama_guarded"


@pytest.mark.parametrize(
    ("name", "sensor", "expected_quality_label", "command", "expected_blocked"),
    [
        (
            "missing-critical-ph",
            {"air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": None, "ec_ms_cm": 1.8},
            "missing_ph",
            {"action_type": "start_irrigation"},
            "direct_actuator_control",
        ),
        (
            "stale-telemetry",
            {"air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": 6.2, "ec_ms_cm": 1.8, "timestamp": "2020-01-01T00:00:00Z"},
            "stale_reading",
            {"action_type": "start_irrigation"},
            "direct_actuator_control",
        ),
        (
            "impossible-and-conflicting-readings",
            {"air_temperature_c": 24.0, "backup_air_temperature_c": 35.0, "humidity_pct": 110.0, "ph": 6.2, "ec_ms_cm": 1.8},
            "impossible_humidity",
            {"action_type": "continue_monitoring"},
            None,
        ),
        (
            "unsafe-chemical-command",
            {"air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": 6.2, "ec_ms_cm": 1.8},
            None,
            {"action_type": "apply_pesticide", "description": "spray pesticide now"},
            "direct_pesticide_dosage",
        ),
    ],
)
def test_pipeline_safety_failure_matrix(name, sensor, expected_quality_label, command, expected_blocked):
    response = client.post(
        "/v1/pipeline/evaluate",
        json={
            "scenario_id": f"safety-matrix-{name}",
            "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"},
            "sensor": sensor,
            "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"],
            "proposed_command": command,
        },
    )

    assert response.status_code == 200
    body = response.json()
    quality_labels = body["sensor_quality"]["data_quality_labels"]
    if expected_quality_label:
        assert expected_quality_label in quality_labels
    if name == "impossible-and-conflicting-readings":
        assert "conflicting_readings" in quality_labels
    if expected_blocked:
        assert expected_blocked in body["final_decision"]["blocked_actions"]
    assert body["final_decision"]["human_review_required"] is True


def test_pipeline_rejects_malformed_sensor_request():
    response = client.post(
        "/v1/pipeline/evaluate",
        json={
            "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
            "sensor": ["not", "an", "object"],
        },
    )
    assert response.status_code == 422


def test_pipeline_audit_returns_summaries_without_sensor_payload(monkeypatch):
    monkeypatch.setattr(
        "app.main.read_pipeline_audit",
        lambda limit: [{"pipeline_id": "pipeline-test", "risk_level": "routine"}],
    )
    response = client.get("/v1/pipeline/audit?limit=20")
    assert response.status_code == 200
    assert response.json() == {
        "count": 1,
        "events": [{"pipeline_id": "pipeline-test", "risk_level": "routine"}],
    }


def test_actuator_dry_run_blocks_without_execution():
    response = client.post(
        "/v1/actuator-commands/dry-run",
        json={
            "actor": "automation_engine",
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"humidity_pct": 80.0},
                "risk_labels": ["missing_critical_data"],
                "proposed_command": {"action_type": "start_irrigation"},
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["execution_performed"] is False
    assert body["decision"] == "blocked"
    assert "direct_actuator_control" in body["blocked_actions"]
    assert body["audit_id"].startswith("dry-run-")


def test_actuator_dry_run_allows_observation_without_execution():
    response = client.post(
        "/v1/actuator-commands/dry-run",
        json={
            "input": {
                "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate"},
                "sensor": {"humidity_pct": 65.0},
                "proposed_command": {"action_type": "continue_monitoring"},
            }
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["execution_performed"] is False
    assert body["decision"] == "allowed"
    assert body["blocked_actions"] == []
