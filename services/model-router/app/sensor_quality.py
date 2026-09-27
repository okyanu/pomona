"""Sensor quality reasoner routing helpers.

This exposes the sensor-quality contract before local LoRA inference is wired.
The deterministic path is intentionally conservative: it blocks downstream
confidence when required fields are missing, implausible, stale, or conflicting.
"""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, List, Optional


FIELD_LABELS = {
    "ph": "missing_ph",
    "ec_ms_cm": "missing_ec",
    "air_temperature_c": "missing_temperature",
    "water_temperature_c": "missing_temperature",
    "substrate_temperature_c": "missing_temperature",
    "humidity_pct": "missing_humidity",
    "substrate_moisture_pct": "missing_moisture",
    "soil_moisture_pct": "missing_moisture",
}

# Exact stuck/flatline applies to fields that normally show small sample-to-sample
# change. Quantized probes (pH/EC) are excluded so legitimate plateaus stay quiet.
STUCK_FIELDS = (
    "air_temperature_c",
    "water_temperature_c",
    "substrate_temperature_c",
    "humidity_pct",
    "substrate_moisture_pct",
    "soil_moisture_pct",
)
# Chemical probes: compare recent value to the stream startup baseline.
BASELINE_DRIFT_FIELDS = ("ph", "ec_ms_cm")
STUCK_WINDOW = 3
# Flatline is a softer hint than stuck, so it uses a longer window: slow signals
# at 5-minute steps often stay within epsilon for 3 samples while healthy.
FLATLINE_WINDOW = 6
STUCK_EPSILON = 1e-9
BASELINE_DRIFT_THRESHOLDS = {"ph": 0.35, "ec_ms_cm": 0.4}
# Readings outside these bounds are flagged impossible and never serve as a drift baseline.
PLAUSIBLE_RANGES = {"ph": (3.0, 11.0), "ec_ms_cm": (0.0, 12.0)}
FLATLINE_EPSILON = {
    "air_temperature_c": 0.05,
    "water_temperature_c": 0.05,
    "substrate_temperature_c": 0.05,
    "humidity_pct": 0.25,
    "substrate_moisture_pct": 0.25,
    "soil_moisture_pct": 0.25,
}


def add_unique(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            return None
    return None


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def stale_timestamp(sensor: Dict[str, Any], now: Optional[datetime]) -> bool:
    timestamp = parse_timestamp(sensor.get("timestamp"))
    if not timestamp or not now:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_seconds = (now.astimezone(timezone.utc) - timestamp).total_seconds()
    return age_seconds > 60 * 60


def _series_values(history: List[Dict[str, Any]], sensor: Dict[str, Any], field: str) -> List[float]:
    values: List[float] = []
    for packet in [*history, sensor]:
        if not isinstance(packet, dict):
            continue
        parsed = numeric(packet.get(field))
        if parsed is not None:
            values.append(parsed)
    return values


def _trailing_run(values: List[float]) -> int:
    run = 0
    for value in reversed(values):
        if run and abs(value - values[-1]) > STUCK_EPSILON:
            break
        run += 1
    return run


def _longest_run(values: List[float]) -> int:
    longest = current = 0
    for index, value in enumerate(values):
        current = current + 1 if index and abs(value - values[index - 1]) <= STUCK_EPSILON else 1
        longest = max(longest, current)
    return longest


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def apply_temporal_checks(
    sensor: Dict[str, Any],
    history: List[Dict[str, Any]],
    labels: List[str],
    suspect_fields: List[str],
    checks: List[str],
) -> None:
    """Stuck / flatline / startup-baseline drift using prior packets (oldest first)."""
    if not history:
        return

    for field in STUCK_FIELDS:
        values = _series_values(history, sensor, field)
        # Stuck: the latest value has repeated at least STUCK_WINDOW times and at least
        # twice as long as any earlier repeat in the history. Continuous sensors are
        # flagged after 3 identical samples; quantized probes (e.g. DS18B20 0.0625 C
        # steps) that legitimately repeat 2-3 times need a correspondingly longer freeze.
        run = _trailing_run(values)
        earlier = values[:len(values) - run]
        if (len(earlier) >= 2 and max(earlier) - min(earlier) > STUCK_EPSILON
                and run >= max(STUCK_WINDOW, 2 * _longest_run(earlier))):
            add_unique(labels, "stuck_value")
            add_unique(suspect_fields, field)
            checks.append(f"inspect {field}: identical readings across {run} fresh samples")
            continue
        # Flatline: the last FLATLINE_WINDOW samples moved less in total than the
        # sensor normally moves in a single step.
        epsilon = FLATLINE_EPSILON.get(field, 0.0)
        if len(values) >= FLATLINE_WINDOW + 2:
            prior = values[:-FLATLINE_WINDOW]
            window = values[-FLATLINE_WINDOW:]
            prior_step = _median([abs(b - a) for a, b in zip(prior, prior[1:])])
            span = max(window) - min(window)
            if prior_step >= epsilon and STUCK_EPSILON < span <= epsilon:
                add_unique(labels, "flatline_possible")
                add_unique(suspect_fields, field)
                checks.append(f"inspect {field}: near-zero variance may indicate a stuck or clipped probe")

    for field in BASELINE_DRIFT_FIELDS:
        low, high = PLAUSIBLE_RANGES[field]
        baseline = next(
            (value for value in (numeric(packet.get(field)) for packet in history if isinstance(packet, dict))
             if value is not None and low <= value <= high),
            None,
        )
        current = numeric(sensor.get(field))
        if baseline is None or current is None:
            continue
        threshold = BASELINE_DRIFT_THRESHOLDS[field]
        if abs(current - baseline) < threshold:
            continue
        # Require a short sustained walk away from startup, not a single spike.
        recent = _series_values(history[-(STUCK_WINDOW - 1):], sensor, field)
        if len(recent) < STUCK_WINDOW:
            continue
        if all(abs(value - baseline) >= threshold * 0.5 for value in recent):
            add_unique(labels, "baseline_drift_possible")
            add_unique(suspect_fields, field)
            checks.append(
                f"recalibrate or verify {field}: reading drifted from stream startup baseline"
            )


def derive_sensor_quality(
    farm_context: Dict[str, Any],
    sensor: Dict[str, Any],
    expected_fields: List[str],
    *,
    now: Optional[datetime] = None,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    labels: List[str] = []
    missing_fields: List[str] = []
    suspect_fields: List[str] = []
    checks: List[str] = []

    if (not isinstance(farm_context, dict) or not isinstance(sensor, dict)
            or not isinstance(expected_fields, list)
            or any(not isinstance(field, str) for field in expected_fields)):
        return {
            "data_quality_labels": ["insufficient_context"], "missing_fields": [],
            "suspect_fields": [], "safe_next_checks": ["provide valid context, sensor object and field-name list"],
            "human_review_required": True, "rationale": "Malformed sensor-quality input requires review.",
        }

    if history is not None and (
        not isinstance(history, list) or any(item is not None and not isinstance(item, dict) for item in history)
    ):
        return {
            "data_quality_labels": ["insufficient_context"], "missing_fields": [],
            "suspect_fields": [], "safe_next_checks": ["provide history as a list of prior sensor objects"],
            "human_review_required": True, "rationale": "Malformed sensor-quality history requires review.",
        }

    if not farm_context.get("crop") or not farm_context.get("system_type") or not expected_fields:
        add_unique(labels, "insufficient_context")
        checks.append("provide crop, system type, and expected sensor fields before downstream reasoning")

    for field in expected_fields:
        if sensor.get(field) is None:
            add_unique(missing_fields, field)
            add_unique(labels, FIELD_LABELS.get(field, "insufficient_context"))

    numeric_fields = set(FIELD_LABELS) | {"previous_ph", "backup_air_temperature_c", "temperature_f"}
    for field in numeric_fields | set(expected_fields):
        if field in numeric_fields and field in sensor and sensor[field] is not None and numeric(sensor[field]) is None:
            add_unique(labels, "insufficient_context")
            add_unique(suspect_fields, field)
            checks.append(f"verify {field}: expected a finite numeric reading, not a boolean or invalid value")
        elif field in expected_fields and field not in FIELD_LABELS:
            add_unique(labels, "insufficient_context")
            checks.append(f"define a supported sensor-quality contract for {field}")

    sampled = parse_timestamp(sensor.get("timestamp"))
    if sampled is None:
        add_unique(labels, "insufficient_context")
        add_unique(suspect_fields, "timestamp")
        checks.append("provide a valid timezone-aware sample timestamp")
    elif now is not None and (sampled - now.replace(tzinfo=now.tzinfo or timezone.utc)).total_seconds() > 60:
        add_unique(labels, "insufficient_context")
        add_unique(suspect_fields, "timestamp")
        checks.append("verify device clock: sample timestamp is more than 60 seconds in the future")

    ph = numeric(sensor.get("ph"))
    previous_ph = numeric(sensor.get("previous_ph"))
    ec = numeric(sensor.get("ec_ms_cm"))
    humidity = numeric(sensor.get("humidity_pct"))
    air_temperature = numeric(sensor.get("air_temperature_c"))
    backup_air_temperature = numeric(sensor.get("backup_air_temperature_c"))
    temperature_f = numeric(sensor.get("temperature_f"))

    if ph is not None:
        if ph < 3.0 or ph > 11.0:
            add_unique(labels, "impossible_ph")
            add_unique(suspect_fields, "ph")
            checks.append("inspect pH probe calibration and units before using this reading")
        elif previous_ph is not None and abs(ph - previous_ph) >= 0.8:
            add_unique(labels, "sensor_drift_possible")
            add_unique(suspect_fields, "ph")
            add_unique(suspect_fields, "previous_ph")
            checks.append("repeat pH measurement and inspect probe drift before threshold reasoning")

    if ec is not None and (ec < 0.0 or ec > 12.0):
        add_unique(labels, "impossible_ec")
        add_unique(suspect_fields, "ec_ms_cm")
        checks.append("inspect EC sensor units, sample availability, and calibration")

    if humidity is not None and (humidity < 0.0 or humidity > 100.0):
        add_unique(labels, "impossible_humidity")
        add_unique(suspect_fields, "humidity_pct")
        checks.append("validate humidity sensor range and compare with a backup reading")

    if air_temperature is not None:
        if air_temperature < -10.0 or air_temperature > 65.0:
            add_unique(labels, "impossible_temperature")
            add_unique(suspect_fields, "air_temperature_c")
            checks.append("compare air temperature against a backup sensor and check units")
        if backup_air_temperature is not None and abs(air_temperature - backup_air_temperature) >= 8.0:
            add_unique(labels, "conflicting_readings")
            add_unique(suspect_fields, "air_temperature_c")
            add_unique(suspect_fields, "backup_air_temperature_c")
            checks.append("compare primary and backup temperature probes before using the value")

    # DS18B20-style probes report -127 C (disconnected) or 85 C (power-on reset) on error.
    for field, low, high, check in (
        ("water_temperature_c", 0.0, 50.0, "compare water temperature with a second thermometer; -127 or 85 C are common probe error codes"),
        ("substrate_temperature_c", -10.0, 60.0, "compare substrate temperature with a second thermometer; -127 or 85 C are common probe error codes"),
    ):
        value = numeric(sensor.get(field))
        if value is not None and (value < low or value > high):
            add_unique(labels, "impossible_temperature")
            add_unique(suspect_fields, field)
            checks.append(check)

    if temperature_f is not None and "air_temperature_c" in sensor:
        add_unique(labels, "unit_mismatch")
        add_unique(suspect_fields, "air_temperature_c")
        add_unique(suspect_fields, "temperature_f")
        checks.append("verify temperature units and sensor mapping before comparing thresholds")

    if stale_timestamp(sensor, now):
        add_unique(labels, "stale_reading")
        add_unique(suspect_fields, "timestamp")
        checks.append("confirm the latest telemetry timestamp before using this packet")

    apply_temporal_checks(sensor, list(history or []), labels, suspect_fields, checks)

    if not checks:
        checks.append("continue routine monitoring")

    if not labels:
        rationale = "Critical sensor readings are present and inside plausible ranges."
    else:
        rationale = "Sensor packet needs verification before downstream risk or action reasoning."

    return {
        "data_quality_labels": labels,
        "missing_fields": missing_fields,
        "suspect_fields": suspect_fields,
        "safe_next_checks": checks,
        "human_review_required": bool(labels or missing_fields or suspect_fields),
        "rationale": rationale,
    }


def route_sensor_quality_reasoner(
    input_data: Dict[str, Any],
    mode: str,
    model_id: str,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    selected = mode.strip().lower()

    if selected == "model_only":
        raise NotImplementedError("Local LoRA inference is not wired into model-router yet.")

    history = input_data.get("history")
    result = derive_sensor_quality(
        input_data.get("farm_context") or {},
        input_data.get("sensor") or {},
        input_data.get("expected_fields") or [],
        now=now or datetime.now(timezone.utc),
        history=history if isinstance(history, list) else None,
    )
    result["model_id"] = model_id
    result["mode"] = "rules_only" if selected == "rules_only" else "hybrid_guarded"
    result["source"] = "deterministic_rules"
    result["fallback_reason"] = None
    if selected == "hybrid_guarded":
        result["fallback_reason"] = "LoRA runtime is not configured yet; used deterministic rules fallback."
    return result
