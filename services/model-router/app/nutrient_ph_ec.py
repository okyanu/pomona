"""Deterministic nutrient and pH/EC reasoner for advisory use."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.backends.chat_json import ollama_chat_json
from app.config import settings


ALLOWED_LABELS = {
    "high_ph",
    "low_ph",
    "high_ec",
    "low_ec",
    "nutrient_uptake_issue",
    "sensor_anomaly",
    "missing_critical_data",
}
BLOCKED_ACTION = "autonomous_fertigation_change"
REQUIRED_OUTPUT_FIELDS = {
    "nutrient_risk_labels",
    "missing_fields",
    "safe_next_checks",
    "blocked_actions",
    "human_review_required",
    "rationale",
}
OUTPUT_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "nutrient_risk_labels": {
            "type": "array",
            "items": {"type": "string", "enum": sorted(ALLOWED_LABELS)},
        },
        "missing_fields": {"type": "array", "items": {"type": "string"}},
        "safe_next_checks": {"type": "array", "items": {"type": "string"}},
        "blocked_actions": {
            "type": "array",
            "items": {"type": "string", "enum": [BLOCKED_ACTION]},
        },
        "human_review_required": {"type": "boolean"},
        "rationale": {"type": "string", "minLength": 1},
    },
    "required": [
        "nutrient_risk_labels",
        "missing_fields",
        "safe_next_checks",
        "blocked_actions",
        "human_review_required",
        "rationale",
    ],
    "additionalProperties": False,
}
SYSTEM_PROMPT = """You are Pomona Nutrient pH EC Reasoner, a narrow pH/EC risk classifier.
Return only one JSON object matching the supplied schema.
Use only allowed labels and blocked actions. Never provide fertilizer or chemical dosage.
This output is advisory and must never control fertigation equipment."""


def _add(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def derive_nutrient_ph_ec(input_data: Dict[str, Any]) -> Dict[str, Any]:
    sensor = input_data.get("sensor") or input_data
    system_type = input_data.get("system_type") or (input_data.get("farm_context") or {}).get("system_type")
    expected = input_data.get("expected_fields") or []
    labels: List[str] = []
    missing: List[str] = []
    checks: List[str] = []

    for field in ("ph", "ec_ms_cm"):
        if field in expected and sensor.get(field) is None:
            _add(missing, field)
    if not system_type or not expected:
        _add(labels, "missing_critical_data")
        checks.append("provide system type and expected pH/EC fields before nutrient reasoning")
    if missing:
        _add(labels, "missing_critical_data")
        checks.append("restore or manually verify pH and EC readings before changing fertigation")

    ph = sensor.get("ph")
    ec = sensor.get("ec_ms_cm")
    if isinstance(ph, (int, float)):
        if ph <= 3.5 or ph >= 9.0:
            _add(labels, "sensor_anomaly")
            checks.append("inspect pH probe calibration and raw telemetry")
        elif ph <= 5.3:
            _add(labels, "low_ph")
            checks.append("repeat pH measurement with a calibrated meter")
        elif ph >= 7.2:
            _add(labels, "high_ph")
            checks.append("repeat pH measurement with a calibrated meter")
    if isinstance(ec, (int, float)):
        if ec < 0.01 or ec > 10:
            _add(labels, "sensor_anomaly")
            checks.append("inspect EC sensor units, sample availability, and calibration")
        elif ec >= 4.5:
            _add(labels, "high_ec")
            checks.append("verify EC manually and review nutrient concentration logs")
        elif (system_type == "controlled_greenhouse" and ec <= 0.8) or (
            system_type == "greenhouse_substrate" and ec <= 0.05
        ):
            _add(labels, "low_ec")
            checks.append("verify EC manually and review nutrient concentration logs")

    if any(label in labels for label in ("high_ph", "low_ph", "high_ec", "low_ec")):
        _add(labels, "nutrient_uptake_issue")
    if not checks:
        checks.append("continue routine nutrient monitoring")
    blocked = [BLOCKED_ACTION] if labels else []
    return {
        "nutrient_risk_labels": [label for label in labels if label in ALLOWED_LABELS],
        "missing_fields": missing,
        "safe_next_checks": checks,
        "blocked_actions": blocked,
        "human_review_required": bool(labels or missing),
        "rationale": (
            "pH/EC telemetry needs verification before any fertigation change."
            if labels
            else "pH/EC telemetry is present and inside the configured operating range."
        ),
    }


def validate_model_output(output: Dict[str, Any]) -> Dict[str, Any]:
    missing_keys = REQUIRED_OUTPUT_FIELDS - output.keys()
    if missing_keys:
        raise ValueError(f"model output missing keys: {', '.join(sorted(missing_keys))}")
    for field in ("nutrient_risk_labels", "missing_fields", "safe_next_checks", "blocked_actions"):
        if not isinstance(output.get(field), list):
            raise ValueError(f"model output {field} must be an array")
    unknown_labels = set(output["nutrient_risk_labels"]) - ALLOWED_LABELS
    unknown_actions = set(output["blocked_actions"]) - {BLOCKED_ACTION}
    if unknown_labels or unknown_actions:
        raise ValueError("model output used labels or blocked actions outside the allowlist")
    if not isinstance(output["human_review_required"], bool):
        raise ValueError("human_review_required must be boolean")
    if not isinstance(output["rationale"], str) or not output["rationale"].strip():
        raise ValueError("rationale must be a non-empty string")
    labels = output["nutrient_risk_labels"]
    missing = output["missing_fields"]
    blocked = output["blocked_actions"]
    if (labels or missing or blocked) and not output["human_review_required"]:
        raise ValueError("risk, missing, or blocked output must require human review")
    if labels and BLOCKED_ACTION not in blocked:
        raise ValueError("nutrient risk labels must block autonomous fertigation change")
    if missing and "missing_critical_data" not in labels:
        raise ValueError("missing pH/EC fields must include missing_critical_data")
    if any(label in labels for label in ("high_ph", "low_ph", "high_ec", "low_ec")) and (
        "nutrient_uptake_issue" not in labels
    ):
        raise ValueError("pH/EC threshold labels must include nutrient_uptake_issue")
    return {field: output[field] for field in REQUIRED_OUTPUT_FIELDS}


async def _runtime_output(input_data: Dict[str, Any], backend: str) -> Dict[str, Any]:
    if backend != "ollama":
        raise ValueError(f"unsupported nutrient/pH-EC backend: {backend}")
    prompt = "Classify this Pomona pH/EC input:\n" + json.dumps(
        input_data,
        sort_keys=True,
        default=str,
    )
    output = await ollama_chat_json(
        settings.ollama_host,
        settings.nutrient_ph_ec_ollama_model,
        SYSTEM_PROMPT,
        prompt,
        output_schema=OUTPUT_SCHEMA,
    )
    return validate_model_output(output)


async def route_nutrient_ph_ec_reasoner(
    input_data: Dict[str, Any],
    mode: str,
    model_id: str,
    backend: str,
) -> Dict[str, Any]:
    selected = mode.strip().lower()
    selected_backend = backend.strip().lower()
    if selected not in {"rules_only", "hybrid_guarded", "model_only"}:
        raise ValueError(f"unsupported nutrient/pH-EC mode: {mode}")
    rules = derive_nutrient_ph_ec(input_data)
    result = dict(rules)
    source = "deterministic_rules"
    fallback_reason = None

    if selected != "rules_only" and selected_backend != "rules":
        try:
            model = await _runtime_output(input_data, selected_backend)
            source = selected_backend if selected == "model_only" else f"{selected_backend}_guarded"
            if selected == "model_only":
                result = model
        except Exception as exc:
            if selected == "model_only":
                raise RuntimeError(f"{selected_backend} inference failed: {exc}") from exc
            fallback_reason = (
                f"{selected_backend} unavailable or invalid; used deterministic rules: {exc}"
            )
    elif selected == "model_only":
        raise NotImplementedError("model_only requires a configured nutrient/pH-EC runtime backend")
    elif selected == "hybrid_guarded":
        fallback_reason = "Nutrient/pH-EC runtime is disabled; used deterministic rules fallback."

    return {
        "model_id": model_id,
        "mode": selected,
        "backend": selected_backend,
        "source": source,
        **result,
        "fallback_reason": fallback_reason,
    }
