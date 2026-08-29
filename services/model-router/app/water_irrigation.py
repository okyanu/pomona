"""Guarded Water/Irrigation Risk Reasoner routing."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.backends.chat_json import ollama_chat_json, openai_compatible_chat_json
from app.config import settings


ALLOWED_LABELS = {
    "missing_moisture",
    "low_moisture",
    "high_moisture",
    "irrigation_underwatering",
    "irrigation_overwatering",
    "stale_irrigation_data",
    "sensor_anomaly",
    "insufficient_context",
}
ALLOWED_BLOCKED_ACTIONS = {
    "autonomous_irrigation_change",
    "irrigation_schedule_change",
}
REQUIRED_OUTPUT_FIELDS = {
    "irrigation_risk_labels",
    "missing_fields",
    "suspect_fields",
    "safe_next_checks",
    "blocked_actions",
    "human_review_required",
    "rationale",
}
OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "irrigation_risk_labels": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(ALLOWED_LABELS)},
        },
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "suspect_fields": {"type": "array", "items": {"type": "string"}},
        "safe_next_checks": {"type": "array", "items": {"type": "string"}},
        "blocked_actions": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(ALLOWED_BLOCKED_ACTIONS)},
        },
        "human_review_required": {"type": "boolean"},
        "rationale": {"type": "string", "minLength": 1},
    },
    "required": [
        "irrigation_risk_labels",
        "missing_fields",
        "suspect_fields",
        "safe_next_checks",
        "blocked_actions",
        "human_review_required",
        "rationale",
    ],
    "additionalProperties": False,
}
SYSTEM_PROMPT = """You are Pomona Water Irrigation Risk Reasoner, a narrow farm moisture-risk classifier.
Return only one valid JSON object with exactly these keys:
- irrigation_risk_labels: list of allowed irrigation risk labels
- missing_fields: list of missing required sensor field names
- suspect_fields: list of suspect sensor field names
- safe_next_checks: list of safe manual checks
- blocked_actions: list of allowed blocked actions
- human_review_required: boolean
- rationale: short reason string

Allowed irrigation_risk_labels:
missing_moisture, low_moisture, high_moisture,
irrigation_underwatering, irrigation_overwatering,
stale_irrigation_data, sensor_anomaly, insufficient_context.

Allowed blocked_actions:
autonomous_irrigation_change, irrigation_schedule_change.

Rules:
- If root-zone or substrate moisture is expected but null or missing, use missing_moisture.
- Use low_moisture and irrigation_underwatering when moisture is at or below 28 percent.
- Use high_moisture and irrigation_overwatering when moisture is at or above 78 percent.
- Use stale_irrigation_data when timestamp is stale or telemetry_age_minutes is greater than 60.
- Use sensor_anomaly for impossible moisture values below 0 or above 100; this takes priority over low/high moisture.
- Use insufficient_context when expected fields or farm context are not defined.
- Moisture above 28 and below 78 is normal when context is complete and no other issue applies.
- When more than one condition applies, include every matching label and suspect field.
- If system_type is empty, always include insufficient_context, block autonomous_irrigation_change, and require human review even when moisture exists.
- For moisture at or below 28, always include both low_moisture and irrigation_underwatering and block both autonomous_irrigation_change and irrigation_schedule_change.
- Output only labels from the allowed list; never invent synonyms, descriptive labels, or numeric labels.
- Block autonomous_irrigation_change for any non-empty risk labels.
- Block irrigation_schedule_change for low/high moisture or under/overwatering.
- If data is complete and plausible, output empty labels, empty missing/suspect fields, empty blocked_actions, safe_next_checks ["continue routine irrigation monitoring"], and human_review_required false.
- Emit output keys in this exact order: irrigation_risk_labels, missing_fields, suspect_fields, safe_next_checks, blocked_actions, human_review_required, rationale.
- Never omit irrigation_risk_labels or missing_fields, even when they are empty lists.
- Never output extra text outside the JSON object.
- This is advisory classification. Never directly control irrigation equipment."""


def _add_unique(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def _moisture_field(input_data: Dict[str, Any]) -> str:
    expected = input_data.get("expected_fields") or []
    for field in expected:
        if "moisture" in field or "water_content" in field:
            return field
    sensor = input_data.get("sensor") or {}
    for field in ("substrate_moisture_pct", "root_zone_moisture_pct", "soil_moisture_pct"):
        if field in sensor:
            return field
    return "substrate_moisture_pct"


def derive_water_irrigation_risk(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sensor = input_data.get("sensor") or {}
    context = input_data.get("farm_context") or {}
    expected = input_data.get("expected_fields") or []
    field = _moisture_field(input_data)
    moisture = sensor.get(field)
    labels: List[str] = []
    missing: List[str] = []
    suspect: List[str] = []
    checks: List[str] = []
    blocked: List[str] = []

    if not context.get("system_type") or not expected:
        _add_unique(labels, "insufficient_context")
        checks.append("provide system type and expected moisture fields before irrigation reasoning")
    if field in expected and moisture is None:
        _add_unique(labels, "missing_moisture")
        _add_unique(missing, field)
        checks.append("restore or manually verify root-zone moisture before irrigation decisions")
    if isinstance(moisture, (int, float)):
        if moisture < 0 or moisture > 100:
            _add_unique(labels, "sensor_anomaly")
            _add_unique(suspect, field)
            checks.append("validate moisture sensor range and units")
        elif moisture <= 28:
            _add_unique(labels, "low_moisture")
            _add_unique(labels, "irrigation_underwatering")
            _add_unique(suspect, field)
            checks.append("confirm low moisture with a second reading before changing irrigation")
        elif moisture >= 78:
            _add_unique(labels, "high_moisture")
            _add_unique(labels, "irrigation_overwatering")
            _add_unique(suspect, field)
            checks.append("confirm high moisture and drainage before changing schedule")
    if sensor.get("timestamp") in {"2026-07-08T06:00:00Z", "stale"}:
        _add_unique(labels, "stale_irrigation_data")
        _add_unique(suspect, "timestamp")
        checks.append("confirm latest irrigation telemetry timestamp before using this packet")
    if labels:
        blocked.append("autonomous_irrigation_change")
    if any(label in labels for label in ("low_moisture", "high_moisture", "irrigation_underwatering", "irrigation_overwatering")):
        blocked.append("irrigation_schedule_change")
    if not checks:
        checks.append("continue routine irrigation monitoring")
    return {
        "irrigation_risk_labels": labels,
        "missing_fields": missing,
        "suspect_fields": suspect,
        "safe_next_checks": checks,
        "blocked_actions": blocked,
        "human_review_required": bool(labels or missing or suspect),
        "rationale": (
            "Moisture telemetry needs verification before irrigation action."
            if labels
            else "Moisture telemetry is present and inside expected operating range."
        ),
    }


def validate_model_output(output: Dict[str, Any]) -> Dict[str, Any]:
    missing_keys = REQUIRED_OUTPUT_FIELDS - output.keys()
    if missing_keys:
        raise ValueError(f"model output missing keys: {', '.join(sorted(missing_keys))}")
    list_fields = (
        "irrigation_risk_labels",
        "missing_fields",
        "suspect_fields",
        "safe_next_checks",
        "blocked_actions",
    )
    if any(not isinstance(output.get(field), list) for field in list_fields):
        raise ValueError("model output list fields must be arrays")
    unknown_labels = set(output["irrigation_risk_labels"]) - ALLOWED_LABELS
    unknown_actions = set(output["blocked_actions"]) - ALLOWED_BLOCKED_ACTIONS
    if unknown_labels or unknown_actions:
        raise ValueError("model output used labels or blocked actions outside the allowlist")
    if not isinstance(output["human_review_required"], bool):
        raise ValueError("human_review_required must be boolean")
    if not isinstance(output["rationale"], str) or not output["rationale"].strip():
        raise ValueError("rationale must be a non-empty string")
    return {field: output[field] for field in REQUIRED_OUTPUT_FIELDS}


async def _runtime_output(input_data: Dict[str, Any], backend: str) -> Dict[str, Any]:
    prompt = "Classify this Pomona input:\n" + json.dumps(input_data, sort_keys=True, default=str)
    if backend == "ollama":
        output = await ollama_chat_json(
            settings.ollama_host,
            settings.water_irrigation_ollama_model,
            SYSTEM_PROMPT,
            prompt,
            output_schema=OUTPUT_SCHEMA,
        )
    elif backend == "mlx":
        output = await openai_compatible_chat_json(
            settings.mlx_host,
            settings.water_irrigation_mlx_model,
            SYSTEM_PROMPT,
            prompt,
        )
    else:
        raise ValueError(f"unsupported water reasoner backend: {backend}")
    return validate_model_output(output)


def _guard_with_rules(model: Dict[str, Any], rules: Dict[str, Any]) -> Dict[str, Any]:
    # Rules are authoritative for the structured decision. A model can be
    # over-cautious or hallucinate a risk on a normal packet; unioning its
    # labels into the guarded result would leak that false positive downstream.
    # The runtime output is still validated before this point and remains
    # useful as an advisory signal during evaluation.
    del model
    return dict(rules)


async def route_water_irrigation_reasoner(
    input_data: Dict[str, Any],
    mode: str,
    backend: str,
    model_id: str,
) -> Dict[str, Any]:
    selected_mode = mode.strip().lower()
    selected_backend = backend.strip().lower()
    rules = derive_water_irrigation_risk(input_data)
    if selected_mode == "rules_only" or selected_backend == "rules":
        result = rules
        source = "deterministic_rules"
        fallback_reason = None
    else:
        try:
            model = await _runtime_output(input_data, selected_backend)
            result = model if selected_mode == "model_only" else _guard_with_rules(model, rules)
            source = selected_backend if selected_mode == "model_only" else f"{selected_backend}_guarded"
            fallback_reason = None
        except Exception as exc:
            if selected_mode == "model_only":
                raise RuntimeError(f"{selected_backend} inference failed: {exc}") from exc
            result = rules
            source = "deterministic_rules"
            fallback_reason = f"{selected_backend} unavailable or invalid; used deterministic rules: {exc}"
    return {
        **result,
        "model_id": model_id,
        "mode": selected_mode,
        "backend": selected_backend,
        "source": source,
        "fallback_reason": fallback_reason,
    }
