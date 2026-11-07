"""Deterministic actuator command gate rules.

The command gate is the hard safety layer between Pomona recommendations and any
real greenhouse equipment. Models may classify or explain, but this module keeps
actuator and chemical decisions advisory unless a human-controlled path approves them.
"""

from __future__ import annotations

import re
import unicodedata
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


# The exact phrases the gate matched before the stems; for observation types they still block.
OLD_ACTUATOR_PHRASES = {"open vent", "close vent", "fan speed", "start pump", "start irrigation", "turn heater", "set valve"}
OLD_FERTIGATION_PHRASES = {"dose acid", "dose base", "change recipe", "increase ec", "decrease ec", "nutrient concentration"}
OLD_CHEMICAL_PHRASES = {"pesticide", "fungicide", "chemical treatment", "spray sulfur"}

KNOWN_ACTION_TYPES = OBSERVATION_TYPES | ACTUATOR_TYPES | FERTIGATION_TYPES | CHEMICAL_TYPES | DIAGNOSIS_TYPES
IRRIGATION_ACTION_TYPES = {"start_irrigation", "stop_irrigation", "set_pump", "set_valve"}

# --- Word-stem matching ---------------------------------------------------------------------------
# The gate is default-deny: only the listed OBSERVATION_TYPES can come out "allowed", and only when their
# text (description / command) carries none of the stems below. Stems classify what a command asks for, so
# the verdict names it (blocked) instead of just routing it to a human (needs_human_approval).
#
# A stem matches only at the start of a word (not inside one), optionally behind a fused verb ("setvalve",
# "openvent"), and must end the word or an inflection: "vent" matches "vent", "vents", "open_vent", "openvent"
# but not "event", "prevent", "invent" or "adventure". Text is lower-cased, NFKC-normalised and stripped of
# invisible characters first.
#
# Judgement call: text cannot tell a command from a mention, so an observation note that names equipment or
# a chemical ("check the vent", "ventilation looks fine", "add nitric acid") is never allowed: for an observation
# type it needs human approval (and is blocked only where an old exact phrase such as "open vent" matches);
# for unknown or free-text commands it is blocked. A
# plain adjective is not a stem: "acidic reading noted" and "pH is acidic" stay allowed ("acid"/"acids" and
# "acidify" are stems, "acidic" and "acidification" are not).
_FUSED_VERBS = r"(?:set|open|close|start|stop|turn|run|toggle|switch|enable|disable|activate)?"
_SEP = r"[\s_\-]*"


def _stems(*alternatives: str) -> re.Pattern[str]:
    return re.compile(r"(?<![a-z])" + _FUSED_VERBS + r"(?:" + "|".join(alternatives) + r")(?![a-z])")


# Water-side equipment: reported as irrigation_control_request.
IRRIGATION_STEMS = _stems(r"valves?", r"pump(?:s|ed|ing)?", r"irrigat\w*", r"sprinklers?", r"drip[\s_\-]*lines?")
# Air-side equipment: reported as climate_control_request. "screen" only counts as a thermal/shade screen or
# behind an action verb ("set screen", "close the screen"), so "screening" and "screenshot" do not trip it.
CLIMATE_STEMS = _stems(
    r"vent(?:s|ed|ing)?", r"ventilat\w*", r"fans?", r"heat(?:ers?|ing)", r"cooling", r"mist(?:er|ers|ing)?",
    r"fogg(?:er|ers|ing)", r"dehumidif\w*", r"humidifiers?", r"dampers?", r"lou?vres?|louvers?",
    r"(?:thermal|shade|energy|curtain)[\s_\-]*screens?", r"shade[\s_\-]*(?:cloth|net)s?", r"curtains?",
    r"co2[\s_\-]*(?:injection|dosing|enrichment)",
)
CLIMATE_SCREEN = re.compile(r"(?<![a-z])(?:set|open|close|deploy|retract|raise|lower|move)[\s_\-]*(?:the[\s_\-]+)?screens?(?![a-z])")
GENERIC_ACTUATOR_STEMS = _stems(r"actuators?", r"relays?", r"solenoids?")
# Pesticide-type chemicals: chemical_application_request + unsafe_chemical_recommendation.
CHEMICAL_STEMS = _stems(
    r"pesticides?", r"fungicides?", r"insecticides?", r"herbicides?", r"miticides?", r"biocides?", r"fumigat\w*",
    r"sul(?:f|ph)ur", r"spray(?:s|ed|ing)?", r"chemicals?",
)
# Acids and bases used to move pH: chemical too, unless the text is plainly a fertigation change ("dose acid").
PH_CHEMICAL_STEMS = _stems(r"acids?", r"acidify(?:ing)?", r"nitric", r"phosphoric", r"sulfuric", r"sulphuric", r"citric")
FERTIGATION_STEMS = _stems(
    r"dos(?:e|es|ed|ing)" + _SEP + r"(?:the[\s_\-]+)?(?:acid|base|alkali|nutrients?|fertili[sz]\w*|ph|ec)", r"fertig\w*", r"fertili[sz]\w*", r"recipes?",
    r"nutrient[\s_\-]*(?:concentration|solution|mix|recipe)s?",
    r"(?:increase|decrease|raise|lower|adjust|change|reduce|boost)" + _SEP + r"(?:the[\s_\-]+)?(?:ec|ph)",
    r"(?:ec|ph)" + _SEP + r"(?:up|down)",
)

_INVISIBLE = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\u200e\u200f\u2060\u2061\u2062\u2063\u2064\ufeff"))


def normalize_text(value: Any) -> str:
    """Lower-case, NFKC-fold and drop invisible characters, so "V\u200balve" is read as "valve"."""
    return unicodedata.normalize("NFKC", str(value)).translate(_INVISIBLE).lower()


def normalize_action_type(value: Any) -> str:
    """`OPEN_VENT`, `open-vent` and `Open Vent` all become `open_vent`."""
    return re.sub(r"[\s_\-]+", "_", normalize_text(value).strip()).strip("_")


def add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def text_contains_any(text: str, needles: set[str]) -> bool:
    lowered = text.lower()
    return any(needle in lowered for needle in needles)


def normalize_action(input_data: dict[str, Any]) -> dict[str, Any]:
    action = input_data.get("proposed_command") or input_data.get("proposed_action") or {}
    if isinstance(action, str):
        # An empty string proposes nothing; any text is free text, which the gate never allows.
        return {"action_type": "free_text", "description": action} if action.strip() else {}
    if isinstance(action, dict):
        return action
    # A list, number or other shape is not a command the gate understands: unknown, not "nothing proposed".
    return {"action_type": "unsupported_command_shape"}


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
    """Return a deterministic gate decision for a proposed Pomona action.

    Default deny: only a listed observation type without equipment, chemical or fertigation words is allowed.
    An unknown action type, free text, or a command with no type but with text needs a human.
    """
    action = normalize_action(input_data)
    action_type = normalize_action_type(action.get("action_type") or "")
    text = normalize_text(f"{action.get('description') or ''} {action.get('command') or ''}")
    # Nothing proposed (no type, no text): the callers' "continue_monitoring" default, kept allowed.
    if not action_type and text.strip():
        action_type = "free_text"
    known_type = action_type in KNOWN_ACTION_TYPES
    # Known types are classified by their set; an unknown type is classified by its words as well.
    stem_text = text if known_type or not action_type else f"{action_type} {text}"
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

    if action_type and not known_type:
        add_unique(labels, "out_of_policy_request")
        add_unique(labels, "human_approval_required")
        safe_alternatives.append("This action type or free text is not on the gate's allowed list; ask a human operator to review it. Nothing is executed automatically.")

    if has_bad_sensor_context(input_data):
        add_unique(labels, "missing_or_bad_sensor_data")
        add_unique(labels, "human_approval_required")
        safe_alternatives.append("Restore or manually verify critical sensor data before approving any operational change.")

    if "actuator_conflict" in risk_labels:
        add_unique(labels, "actuator_conflict")
        add_unique(labels, "human_approval_required")
        safe_alternatives.append("Ask a human operator to review actuator state and recent trend data before acting.")

    # An observation type never executes anything, so text that merely mentions equipment, a chemical or a
    # recipe needs a person's eye, not a block. For observation types the old exact phrases keep their old effect
    # (blocked); a new stem hit the phrases would not have caught only adds the family label and
    # human_approval_required. Every other type (unknown, free text, equipment types) blocks on any stem hit.
    observation = action_type in OBSERVATION_TYPES
    irrigation_hit = bool(IRRIGATION_STEMS.search(stem_text))
    climate_hit = bool(CLIMATE_STEMS.search(stem_text) or CLIMATE_SCREEN.search(stem_text))
    generic_hit = bool(GENERIC_ACTUATOR_STEMS.search(stem_text))
    stem_actuator = irrigation_hit or climate_hit or generic_hit
    if observation and text_contains_any(text, OLD_ACTUATOR_PHRASES):
        add_unique(labels, "direct_actuator_control_request")
        add_unique(labels, "climate_control_request")
        add_unique(blocked_actions, "direct_actuator_control")
        safe_alternatives.append("Present the proposed actuator change for human approval instead of executing it.")
    elif action_type in ACTUATOR_TYPES or stem_actuator:
        add_unique(labels, "direct_actuator_control_request")
        is_irrigation = action_type in IRRIGATION_ACTION_TYPES or irrigation_hit
        is_climate = (action_type in ACTUATOR_TYPES and action_type not in IRRIGATION_ACTION_TYPES) or climate_hit
        if is_irrigation:
            add_unique(labels, "irrigation_control_request")
        if is_climate or not is_irrigation:
            add_unique(labels, "climate_control_request")
        if observation:
            add_unique(labels, "human_approval_required")
        else:
            add_unique(blocked_actions, "direct_actuator_control")
        safe_alternatives.append("Present the proposed actuator change for human approval instead of executing it.")

    stem_fertigation = bool(FERTIGATION_STEMS.search(stem_text))
    fertigation_hit = action_type in FERTIGATION_TYPES or stem_fertigation
    if observation and text_contains_any(text, OLD_FERTIGATION_PHRASES):
        add_unique(labels, "autonomous_fertigation_change")
        add_unique(blocked_actions, "autonomous_fertigation_change")
        safe_alternatives.append("Verify pH/EC manually and require a human grower before any fertigation change.")
    elif fertigation_hit:
        add_unique(labels, "autonomous_fertigation_change")
        if observation:
            add_unique(labels, "human_approval_required")
        else:
            add_unique(blocked_actions, "autonomous_fertigation_change")
        safe_alternatives.append("Verify pH/EC manually and require a human grower before any fertigation change.")

    stem_chemical = bool(CHEMICAL_STEMS.search(stem_text) or (not fertigation_hit and PH_CHEMICAL_STEMS.search(stem_text)))
    if action_type in CHEMICAL_TYPES or stem_chemical:
        add_unique(labels, "chemical_application_request")
        add_unique(labels, "unsafe_chemical_recommendation")
        add_unique(labels, "human_approval_required")
        if not observation or text_contains_any(text, OLD_CHEMICAL_PHRASES):
            add_unique(blocked_actions, "direct_pesticide_dosage")
            add_unique(blocked_actions, "unsafe_chemical_recommendation")
        safe_alternatives.append("Request human scouting and qualified review before any chemical treatment.")

    if action_type in DIAGNOSIS_TYPES or text_contains_any(text, {"diagnose", "confirm disease", "this is powdery mildew", "infected"}):
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
        "rationale": "Default deny: only observation-only commands are allowed. Unknown action types and free text need human approval; direct equipment, fertigation, chemical, diagnosis, or bad-data conditions are blocked or routed to human approval.",
    }
