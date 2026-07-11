from pathlib import Path
import importlib.util


RULES_PATH = Path(__file__).resolve().parents[1] / "app" / "actuator_gate_rules.py"
SPEC = importlib.util.spec_from_file_location("pomona_safety_checker_actuator_gate_rules", RULES_PATH)
assert SPEC is not None and SPEC.loader is not None
actuator_gate_rules = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(actuator_gate_rules)

derive_actuator_gate = actuator_gate_rules.derive_actuator_gate


def base_input():
    return {
        "farm_context": {
            "crop": "tomato",
            "system_type": "controlled_greenhouse",
            "zone_id": "greenhouse-a",
        },
        "sensor": {
            "air_temperature_c": 24.0,
            "humidity_pct": 68.0,
            "ph": 6.2,
            "ec_ms_cm": 2.4,
        },
        "sensor_quality": {
            "data_quality_labels": [],
            "missing_fields": [],
            "suspect_fields": [],
        },
        "risk_labels": [],
        "actor": "assistant_model",
        "proposed_command": {
            "action_type": "log_observation",
            "description": "Record the current readings on the dashboard.",
        },
    }


def test_safe_observation_is_allowed():
    result = derive_actuator_gate(base_input())

    assert result["decision"] == "allowed"
    assert result["gate_labels"] == ["safe_observation_only"]
    assert result["blocked_actions"] == []
    assert result["human_approval_required"] is False


def test_direct_actuator_control_is_blocked():
    command = base_input()
    command["actor"] = "automation_engine"
    command["proposed_command"] = {
        "action_type": "open_vent",
        "description": "Open the roof vent to 100 percent now.",
    }

    result = derive_actuator_gate(command)

    assert result["decision"] == "blocked"
    assert "direct_actuator_control_request" in result["gate_labels"]
    assert "climate_control_request" in result["gate_labels"]
    assert result["blocked_actions"] == ["direct_actuator_control"]


def test_bad_sensor_context_requires_human_approval():
    command = base_input()
    command["sensor_quality"] = {
        "data_quality_labels": ["conflicting_readings"],
        "missing_fields": [],
        "suspect_fields": ["air_temperature_c", "backup_air_temperature_c"],
    }
    command["proposed_command"] = {
        "action_type": "manual_check",
        "description": "Ask an operator to inspect the temperature sensors.",
    }

    result = derive_actuator_gate(command)

    assert result["decision"] == "needs_human_approval"
    assert "missing_or_bad_sensor_data" in result["gate_labels"]
    assert result["blocked_actions"] == []
    assert result["human_approval_required"] is True


def test_chemical_and_diagnosis_request_is_blocked():
    command = base_input()
    command["risk_labels"] = ["fungal_pressure"]
    command["proposed_command"] = {
        "action_type": "apply_fungicide",
        "description": "Diagnose powdery mildew and spray fungicide today.",
    }

    result = derive_actuator_gate(command)

    assert result["decision"] == "blocked"
    assert "chemical_application_request" in result["gate_labels"]
    assert "definitive_disease_diagnosis" in result["gate_labels"]
    assert result["blocked_actions"] == [
        "direct_pesticide_dosage",
        "unsafe_chemical_recommendation",
        "definitive_disease_diagnosis",
    ]
