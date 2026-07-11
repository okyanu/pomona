"""Deterministic tomato greenhouse risk rules.

These rules are the safety-oriented baseline for Pomona's small reasoner. A model may
suggest labels, but actuator and chemical safety boundaries must remain enforceable in code.
"""

from __future__ import annotations

from typing import Any


ALLOWED_RISK_LABELS = {
    "high_ph",
    "low_ph",
    "high_ec",
    "low_ec",
    "heat_stress",
    "cold_stress",
    "fungal_pressure",
    "nutrient_uptake_issue",
    "sensor_anomaly",
    "missing_critical_data",
    "water_level_risk",
    "actuator_conflict",
}

ALLOWED_BLOCKED_ACTIONS = {
    "direct_pesticide_dosage",
    "autonomous_fertigation_change",
    "direct_actuator_control",
    "definitive_disease_diagnosis",
    "unsafe_chemical_recommendation",
}

PESTICIDE_AND_DIAGNOSIS_BLOCKS = [
    "direct_pesticide_dosage",
    "definitive_disease_diagnosis",
    "unsafe_chemical_recommendation",
]


def add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def missing_input_fields(input_data: dict[str, Any]) -> list[str]:
    critical = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
    system_type = input_data.get("system_type")
    if system_type == "greenhouse_substrate":
        critical.extend(["substrate_temperature_c", "substrate_moisture_pct"])
    return [field for field in critical if input_data.get(field) is None]


def is_actuator_conflict(input_data: dict[str, Any]) -> bool:
    states = input_data.get("actuator_states") or {}
    humidity = input_data.get("humidity_pct")
    moisture = input_data.get("substrate_moisture_pct")
    screen_energy = states.get("screen_energy_pct")
    screen_blackout = states.get("screen_blackout_pct")
    water_flow = states.get("water_flow_duration_min")

    if humidity is not None and humidity >= 88:
        if (screen_energy is not None and screen_energy >= 80) or (
            screen_blackout is not None and screen_blackout >= 80
        ):
            return True
    if moisture is not None and moisture < 30 and water_flow is not None and water_flow <= 0:
        return True
    return False


def derive_tomato_risk(input_data: dict[str, Any]) -> dict[str, Any]:
    """Return Pomona risk JSON from a normalized tomato greenhouse input record."""
    risks: list[str] = []
    safe_next_checks: list[str] = []
    blocked_actions: list[str] = []

    missing = missing_input_fields(input_data)
    if missing:
        add_unique(risks, "missing_critical_data")
        safe_next_checks.append("restore or manually verify missing critical sensor readings")

    ph = input_data.get("ph")
    ec = input_data.get("ec_ms_cm")
    air_temp = input_data.get("air_temperature_c")
    humidity = input_data.get("humidity_pct")
    substrate_temp = input_data.get("substrate_temperature_c")
    substrate_moisture = input_data.get("substrate_moisture_pct")
    system_type = input_data.get("system_type")

    if ph is not None:
        if ph <= 3.5 or ph >= 9.0:
            add_unique(risks, "sensor_anomaly")
            safe_next_checks.append("inspect pH probe calibration and raw telemetry")
        elif ph >= 7.2:
            add_unique(risks, "high_ph")
            safe_next_checks.append("repeat pH measurement with a calibrated meter")
        elif ph <= 5.3:
            add_unique(risks, "low_ph")
            safe_next_checks.append("repeat pH measurement with a calibrated meter")

    if ec is not None:
        if ec < 0.01 or ec > 10:
            add_unique(risks, "sensor_anomaly")
            safe_next_checks.append("inspect EC sensor units, sample availability, and calibration")
        elif ec >= 4.5:
            add_unique(risks, "high_ec")
            safe_next_checks.append("verify EC manually and review nutrient concentration logs")
        elif system_type == "controlled_greenhouse" and ec <= 0.8:
            add_unique(risks, "low_ec")
            safe_next_checks.append("verify EC manually and review nutrient concentration logs")
        elif system_type == "greenhouse_substrate" and ec <= 0.05:
            add_unique(risks, "low_ec")
            safe_next_checks.append("verify soil EC manually before making any nutrient conclusion")

    if air_temp is not None:
        if air_temp < -5 or air_temp > 60:
            add_unique(risks, "sensor_anomaly")
            safe_next_checks.append("compare air temperature against a backup sensor")
        elif air_temp >= 30:
            add_unique(risks, "heat_stress")
            safe_next_checks.append("review greenhouse temperature trend and ventilation state")
        elif air_temp <= 16:
            add_unique(risks, "cold_stress")
            safe_next_checks.append("review greenhouse heating state and overnight temperature trend")

    if substrate_temp is not None:
        if substrate_temp >= 30:
            add_unique(risks, "heat_stress")
            safe_next_checks.append("review substrate temperature trend and root-zone conditions")
        elif substrate_temp <= 16:
            add_unique(risks, "cold_stress")
            safe_next_checks.append("review substrate temperature trend and root-zone conditions")

    if humidity is not None:
        if humidity < 0 or humidity > 100:
            add_unique(risks, "sensor_anomaly")
            safe_next_checks.append("validate humidity sensor range")
        elif humidity >= 85:
            add_unique(risks, "fungal_pressure")
            safe_next_checks.append("inspect canopy and leaf surfaces before any disease conclusion")

    if substrate_moisture is not None:
        if substrate_moisture < 10 or substrate_moisture > 85:
            add_unique(risks, "water_level_risk")
            safe_next_checks.append("confirm substrate moisture with a second reading")

    if any(label in risks for label in ("high_ph", "low_ph", "high_ec", "low_ec")):
        add_unique(risks, "nutrient_uptake_issue")

    if is_actuator_conflict(input_data):
        add_unique(risks, "actuator_conflict")
        safe_next_checks.append("review actuator state with a human operator before changing settings")

    if any(label in risks for label in ("high_ph", "low_ph", "high_ec", "low_ec", "nutrient_uptake_issue")):
        add_unique(blocked_actions, "autonomous_fertigation_change")
    if any(label in risks for label in ("heat_stress", "cold_stress", "water_level_risk", "actuator_conflict")):
        add_unique(blocked_actions, "direct_actuator_control")
    if "fungal_pressure" in risks:
        for action in PESTICIDE_AND_DIAGNOSIS_BLOCKS:
            add_unique(blocked_actions, action)

    if not safe_next_checks:
        safe_next_checks.append("continue routine monitoring")

    return {
        "risk_labels": risks,
        "missing_data": missing,
        "safe_next_checks": safe_next_checks,
        "blocked_actions": [action for action in blocked_actions if action in ALLOWED_BLOCKED_ACTIONS],
        "human_review_required": bool(risks or blocked_actions),
    }
