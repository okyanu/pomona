from pathlib import Path
import importlib.util

import pytest


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


def command_input(command, **over):
    data = base_input()
    data["proposed_command"] = command
    data.update(over)
    return data


@pytest.mark.parametrize("action_type", ["OPEN_VENT", "open-vent", "Open Vent", "  open_vent  ", "open__vent", "Set_Valve", "SET-FAN-SPEED"])
def test_action_type_is_normalised_before_matching(action_type):
    result = derive_actuator_gate(command_input({"action_type": action_type, "description": "Do it."}))

    assert result["decision"] == "blocked"
    assert "direct_actuator_control_request" in result["gate_labels"]
    assert "out_of_policy_request" not in result["gate_labels"]
    assert result["blocked_actions"] == ["direct_actuator_control"]


@pytest.mark.parametrize("action_type", ["open_valve", "valve_open", "start-pump", "setvalve", "openvent"])
def test_unlisted_actuator_spellings_are_blocked_by_stem(action_type):
    result = derive_actuator_gate(command_input({"action_type": action_type, "description": "Do it."}))

    assert result["decision"] == "blocked"
    assert "out_of_policy_request" in result["gate_labels"]
    assert "direct_actuator_control_request" in result["gate_labels"]
    assert result["blocked_actions"] == ["direct_actuator_control"]


def test_irrigation_words_are_reported_as_irrigation_not_climate():
    result = derive_actuator_gate(command_input({"action_type": "open_valve", "description": "Open the zone valve."}))

    assert "irrigation_control_request" in result["gate_labels"]
    assert "climate_control_request" not in result["gate_labels"]


@pytest.mark.parametrize("command", [
    {"action_type": "reorganise_benches", "description": "Move the benches."},
    {"action_type": "free_text", "description": "Everything looks fine, continue."},
    "Everything looks fine, continue.",
    {"description": "Everything looks fine, continue."},
    {"action_type": "unknown"},
    {"action_type": ["log_observation"]},
    ["log_observation"],
])
def test_unknown_action_type_or_free_text_needs_human_approval(command):
    result = derive_actuator_gate(command_input(command))

    assert result["decision"] == "needs_human_approval"
    assert "out_of_policy_request" in result["gate_labels"]
    assert "human_approval_required" in result["gate_labels"]
    assert result["human_approval_required"] is True
    assert result["blocked_actions"] == []


@pytest.mark.parametrize("command", [None, {}, "", "   ", {"action_type": ""}, {"action_type": None, "description": ""}])
def test_nothing_proposed_stays_allowed(command):
    """Callers send continue_monitoring when nothing is proposed; an empty command still means 'nothing'."""
    result = derive_actuator_gate(command_input(command))

    assert result["decision"] == "allowed"
    assert result["gate_labels"] == ["safe_observation_only"]


@pytest.mark.parametrize("action_type", sorted(actuator_gate_rules.OBSERVATION_TYPES))
def test_each_observation_type_is_still_allowed(action_type):
    result = derive_actuator_gate(command_input({"action_type": action_type, "description": "Record the readings and continue monitoring."}))

    assert result["decision"] == "allowed"
    assert result["human_approval_required"] is False
    assert result["gate_labels"] == ["safe_manual_check" if action_type == "manual_check" else "safe_observation_only"]


@pytest.mark.parametrize("description", [
    "Event logged: nothing to do.",
    "Prevent condensation by watching the trend.",
    "Preventive check on the screening results, no screenshot needed.",
    "Adventure of the day: calm.",
    "The reading is acidic, note it only.",
    "Eventually the sensor drifts.",
])
def test_innocent_words_that_contain_a_stem_do_not_trip_it(description):
    result = derive_actuator_gate(command_input({"action_type": "dashboard_note", "description": description}))

    assert result["decision"] == "allowed", description
    assert result["gate_labels"] == ["safe_observation_only"]


MENTIONS = [
    ("Approve opening valve_main for 6 hours", "direct_actuator_control_request", "direct_actuator_control"),
    ("Switch the fans on", "direct_actuator_control_request", "direct_actuator_control"),
    ("Increase ventilation", "climate_control_request", "direct_actuator_control"),
    ("Close the screen at night", "climate_control_request", "direct_actuator_control"),
    ("Apply nitric acid now", "chemical_application_request", "unsafe_chemical_recommendation"),
    ("Spray the leaves", "chemical_application_request", "direct_pesticide_dosage"),
    ("Lower EC to 1.8", "autonomous_fertigation_change", "autonomous_fertigation_change"),
    ("Dose nutrients into the tank", "autonomous_fertigation_change", "autonomous_fertigation_change"),
    ("Use a new nutrient recipe", "autonomous_fertigation_change", "autonomous_fertigation_change"),
    ("v\u200balve open", "direct_actuator_control_request", "direct_actuator_control"),
]


@pytest.mark.parametrize("description,label,blocked", MENTIONS)
@pytest.mark.parametrize("shape", ["free_text", "string"])
def test_equipment_chemical_and_fertigation_words_are_blocked_in_free_text(shape, description, label, blocked):
    command = {
        "free_text": {"action_type": "free_text", "description": description},
        "string": description,
    }[shape]

    result = derive_actuator_gate(command_input(command))

    assert result["decision"] == "blocked", description
    assert label in result["gate_labels"]
    assert blocked in result["blocked_actions"]


@pytest.mark.parametrize("description,label,blocked", MENTIONS)
def test_equipment_chemical_and_fertigation_words_in_an_observation_need_a_person(description, label, blocked):
    """An observation never executes anything: a mention is labelled and routed to a human, not blocked."""
    result = derive_actuator_gate(command_input({"action_type": "log_observation", "description": description}))

    assert result["decision"] == "needs_human_approval", description
    assert label in result["gate_labels"]
    assert "human_approval_required" in result["gate_labels"]
    assert "out_of_policy_request" not in result["gate_labels"]
    assert result["blocked_actions"] == []
    assert result["human_approval_required"] is True


@pytest.mark.parametrize("action_type,description,label", [
    ("manual_check", "Inspect the moisture probe and irrigation log.", "irrigation_control_request"),
    ("dashboard_note", "open valve_main now", "direct_actuator_control_request"),
    ("send_alert", "Alert that the fan and vent state conflicts.", "climate_control_request"),
    ("manual_check", "Compare EC against a handheld meter before changing recipes.", "autonomous_fertigation_change"),
    ("manual_check", "Check the acid tank level by hand.", "chemical_application_request"),
])
def test_observation_that_only_mentions_a_family_is_needs_human_approval_not_blocked(action_type, description, label):
    result = derive_actuator_gate(command_input({"action_type": action_type, "description": description}))

    assert result["decision"] == "needs_human_approval"
    assert label in result["gate_labels"]
    assert result["blocked_actions"] == []


@pytest.mark.parametrize("action_type", sorted(actuator_gate_rules.OBSERVATION_TYPES))
@pytest.mark.parametrize("description,blocked", [
    ("Open vent to 100 percent.", "direct_actuator_control"),
    ("Set valve zone_1 open.", "direct_actuator_control"),
    ("Start pump now.", "direct_actuator_control"),
    ("Dose acid to pH 5.8.", "autonomous_fertigation_change"),
    ("Increase EC by 0.4.", "autonomous_fertigation_change"),
    ("Apply pesticide tonight.", "direct_pesticide_dosage"),
    ("Spray sulfur on the leaves.", "direct_pesticide_dosage"),
])
def test_old_exact_phrases_still_block_inside_observation_types(action_type, description, blocked):
    result = derive_actuator_gate(command_input({"action_type": action_type, "description": description}))

    assert result["decision"] == "blocked"
    assert blocked in result["blocked_actions"]


def test_command_field_is_read_as_well_as_description():
    result = derive_actuator_gate(command_input({"action_type": "log_observation", "description": "Fine.", "command": "open vent"}))

    assert result["decision"] == "blocked"


def test_every_gate_label_in_a_result_is_allowed():
    for command in ("open vent", "free text", {"action_type": "x"}, {"action_type": "manual_check"}):
        result = derive_actuator_gate(command_input(command))
        assert set(result["gate_labels"]) <= actuator_gate_rules.ALLOWED_GATE_LABELS
