"""Deterministic nutrient and pH/EC reasoner for advisory use."""

from __future__ import annotations

from typing import Any, Dict, List


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


def route_nutrient_ph_ec_reasoner(input_data: Dict[str, Any], mode: str, model_id: str) -> Dict[str, Any]:
    selected = mode.strip().lower()
    if selected == "model_only":
        raise NotImplementedError("Nutrient/pH-EC LoRA inference is not wired yet; use rules_only or hybrid_guarded.")
    if selected not in {"rules_only", "hybrid_guarded"}:
        raise ValueError(f"unsupported nutrient/pH-EC mode: {mode}")
    return {
        "model_id": model_id,
        "mode": selected,
        "source": "deterministic_rules",
        **derive_nutrient_ph_ec(input_data),
        "fallback_reason": (
            "The nutrient/pH-EC model is not configured; deterministic rules were used."
            if selected == "hybrid_guarded"
            else None
        ),
    }
