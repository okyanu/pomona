"""Deterministic actuator command gate rules.

The command gate is the hard safety layer between Pomona recommendations and any
real greenhouse equipment. Models may classify or explain, but this module keeps
actuator and chemical decisions advisory unless a human-controlled path approves them.
"""

from __future__ import annotations

from typing import Any


ALLOWED_DECISIONS = {"allowed", "blocked", "needs_human_approval"}

ALLOWED_GATE_LABELS = {
    "safe_observation_only",
    "safe_manual_check",
    "human_approval_required",
    "direct_actuator_control_request",
    "autonomous_fertigation_change",
    "irrigation_control_request",
    "climate_control_request",
    "chemical_application_request",
    "unsafe_chemical_recommendation",
    "definitive_disease_diagnosis",
    "missing_or_bad_sensor_data",
    "actuator_conflict",
    "out_of_policy_request",
}

ALLOWED_BLOCKED_ACTIONS = {
    "direct_pesticide_dosage",
    "autonomous_fertigation_change",
    "direct_actuator_control",
    "definitive_disease_diagnosis",
    "unsafe_chemical_recommendation",
}

OBSERVATION_TYPES = {
    "log_observation",
    "send_alert",
    "manual_check",
    "dashboard_note",
    "continue_monitoring",
}

ACTUATOR_TYPES = {
    "open_vent",
    "close_vent",
    "set_fan_speed",
    "set_heater",
    "set_cooling_pad",
    "set_screen",
    "start_irrigation",
    "stop_irrigation",
    "set_pump",
    "set_valve",
}

FERTIGATION_TYPES = {
    "change_fertigation_recipe",
    "dose_acid",
    "dose_base",
    "increase_ec",
    "decrease_ec",
    "change_nutrient_concentration",
}

CHEMICAL_TYPES = {
    "apply_pesticide",
    "apply_fungicide",
    "chemical_treatment",
}

DIAGNOSIS_TYPES = {
    "confirm_disease",
    "definitive_diagnosis",
}


def add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def text_contains_any(text: str, needles: set[str]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def normalize_action(input_data: dict[str, Any]) -> dict[str, Any]:
    action = input_data.get("proposed_command") or input_data.get("proposed_action") or {}
    if isinstance(action, str):
        return {"action_type": "free_text", "description": action}
    if isinstance(action, dict):
        return action
    return {}


def has_bad_sensor_context(input_data: dict[str, Any]) -> bool:
    sensor_quality = input_data.get("sensor_quality") or {}
    quality_labels = sensor_quality.get("data_quality_labels") or []
    missing_fields = sensor_quality.get("missing_fields") or []
    risk_labels = input_data.get("risk_labels") or []
    return bool(
        missing_fields
        or "missing_critical_data" in risk_labels
        or any(label in quality_labels for label in ("stale_reading", "sensor_drift_possible", "conflicting_readings", "unit_mismatch"))
    )


def derive_actuator_gate(input_data: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic gate decision for a proposed Pomona action."""
    action = normalize_action(input_data)
    action_type = str(action.get("action_type") or "").strip()
    description = str(action.get("description") or action.get("command") or "")
    actor = str(input_data.get("actor") or action.get("actor") or "")
    risk_labels = input_data.get("risk_labels") or []

    labels: list[str] = []
    blocked_actions: list[str] = []
    safe_alternatives: list[str] = []

    if action_type in OBSERVATION_TYPES:
        if action_type == "manual_check":
            add_unique(labels, "safe_manual_check")
            safe_alternatives.append("Keep this as a manual verification task and do not change equipment automatically.")
        else:
            add_unique(labels, "safe_observation_only")
            safe_alternatives.append("Log or display the observation without changing actuators or recipes.")

    if has_bad_sensor_context(input_data):
        add_unique(labels, "missing_or_bad_sensor_data")
        add_unique(labels, "human_approval_required")
        safe_alternatives.append("Restore or manually verify critical sensor data before approving any operational change.")

    if "actuator_conflict" in risk_labels:
        add_unique(labels, "actuator_conflict")
        add_unique(labels, "human_approval_required")
        safe_alternatives.append("Ask a human operator to review actuator state and recent trend data before acting.")

    if action_type in ACTUATOR_TYPES or text_contains_any(description, {"open vent", "close vent", "fan speed", "start pump", "start irrigation", "turn heater", "set valve"}):
        add_unique(labels, "direct_actuator_control_request")
        if action_type in {"start_irrigation", "stop_irrigation", "set_pump", "set_valve"}:
            add_unique(labels, "irrigation_control_request")
        else:
            add_unique(labels, "climate_control_request")
        add_unique(blocked_actions, "direct_actuator_control")
        safe_alternatives.append("Present the proposed actuator change for human approval instead of executing it.")

    if action_type in FERTIGATION_TYPES or text_contains_any(description, {"dose acid", "dose base", "change recipe", "increase ec", "decrease ec", "nutrient concentration"}):
        add_unique(labels, "autonomous_fertigation_change")
        add_unique(blocked_actions, "autonomous_fertigation_change")
        safe_alternatives.append("Verify pH/EC manually and require a human grower before any fertigation change.")

    if action_type in CHEMICAL_TYPES or text_contains_any(description, {"pesticide", "fungicide", "chemical treatment", "spray sulfur"}):
        add_unique(labels, "chemical_application_request")
        add_unique(labels, "unsafe_chemical_recommendation")
        add_unique(labels, "human_approval_required")
        add_unique(blocked_actions, "direct_pesticide_dosage")
        add_unique(blocked_actions, "unsafe_chemical_recommendation")
        safe_alternatives.append("Request human scouting and qualified review before any chemical treatment.")

    if action_type in DIAGNOSIS_TYPES or text_contains_any(description, {"diagnose", "confirm disease", "this is powdery mildew", "infected"}):
        add_unique(labels, "definitive_disease_diagnosis")
        add_unique(labels, "human_approval_required")
        add_unique(blocked_actions, "definitive_disease_diagnosis")
        safe_alternatives.append("Describe disease as a possible risk signal and request visual inspection or lab-supported confirmation.")

    if actor in {"automation_engine", "assistant_model", "digital_twin"} and blocked_actions:
        add_unique(labels, "human_approval_required")

    if not labels:
        add_unique(labels, "safe_observation_only")
    if not safe_alternatives:
        safe_alternatives.append("Continue routine monitoring.")

    if blocked_actions:
        decision = "blocked"
    elif "human_approval_required" in labels or "missing_or_bad_sensor_data" in labels or "actuator_conflict" in labels:
        decision = "needs_human_approval"
    else:
        decision = "allowed"

    return {
        "decision": decision,
        "gate_labels": [label for label in labels if label in ALLOWED_GATE_LABELS],
        "blocked_actions": [action for action in blocked_actions if action in ALLOWED_BLOCKED_ACTIONS],
        "human_approval_required": decision != "allowed",
        "safe_alternatives": safe_alternatives,
        "rationale": "Direct equipment, fertigation, chemical, diagnosis, or bad-data conditions are blocked or routed to human approval.",
    }
