"""Sensor-quality veto: a reading that failed the sensor check is not reasoned on.

Pure and deterministic. Domain specialists (water, nutrient, tomato) only see
the readings the sensor-quality reasoner did not flag, so an impossible pH can
no longer become a `high_ph` label. The safety/actuator gate still sees everything.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Labels that make the whole packet untrustworthy, not one probe.
GLOBAL_VETO_LABELS = {"stale_reading", "insufficient_context", "unit_mismatch"}
# Fields that describe one measurement: vetoing one vetoes the others.
COMPANION_GROUPS = (
    ("ph", "previous_ph"),
    ("air_temperature_c", "backup_air_temperature_c", "temperature_f"),
)
WATER_MODEL_ID = "pomona-water-irrigation-risk-reasoner-v0.1"
NUTRIENT_MODEL_ID = "pomona-nutrient-ph-ec-reasoner-v0.1"
VETO_CHECK = "resolve the sensor-quality flags before domain reasoning"
ROUTINE_CHECK = "continue routine monitoring"
NEEDS_VERIFICATION = "Sensor packet needs verification before downstream risk or action reasoning."


def _mask(packet: Any, vetoed: set) -> Any:
    return {key: value for key, value in packet.items() if key not in vetoed} if isinstance(packet, dict) else packet


def merge_known_checks(
    quality: Dict[str, Any],
    sensor: Dict[str, Any],
    vetoed: Optional[List[str]] = None,
    labels: Optional[List[str]] = None,
    checks: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Merge the sensor-check results of other devices of a zone into `quality`, before `apply_sensor_veto`
    (multi-device zones, docs/design/multi-device-zones-slice2.md 2.3). Returns a new dict; `quality` is not changed.

    - Labels are added, except `GLOBAL_VETO_LABELS` (a stale packet of one device must not veto the whole zone) and
      `missing_*` (the router decides missing fields on the snapshot itself).
    - A known vetoed field becomes a suspect field only when `sensor` holds a value for it.
    - Known safe next checks not already present are appended; "continue routine monitoring" goes when any other is there.
    - Anything added makes human review required; labels added to a clean result give the "needs verification" rationale.
    - `from_device_checks` lists what was added; the key is absent when nothing was.
    """
    merged = dict(quality)
    merged_labels = list(quality.get("data_quality_labels") or [])
    merged_suspects = list(quality.get("suspect_fields") or [])
    merged_checks = list(quality.get("safe_next_checks") or [])
    added_labels: List[str] = []
    added_fields: List[str] = []
    added_checks: List[str] = []
    for label in labels or []:
        if label in GLOBAL_VETO_LABELS or label.startswith("missing_") or label in merged_labels:
            continue
        merged_labels.append(label)
        added_labels.append(label)
    for field in vetoed or []:
        if sensor.get(field) is None or field in merged_suspects:
            continue
        merged_suspects.append(field)
        added_fields.append(field)
    for check in checks or []:
        if check not in merged_checks:
            merged_checks.append(check)
            added_checks.append(check)
    if not (added_labels or added_fields or added_checks):
        return merged
    if len(merged_checks) > 1:
        merged_checks = [check for check in merged_checks if check != ROUTINE_CHECK]
    was_clean = not (quality.get("data_quality_labels") or [])
    merged["data_quality_labels"] = merged_labels
    merged["suspect_fields"] = merged_suspects
    merged["safe_next_checks"] = merged_checks
    merged["human_review_required"] = True
    if added_labels and was_clean:
        merged["rationale"] = NEEDS_VERIFICATION
    merged["from_device_checks"] = {"data_quality_labels": added_labels, "vetoed_fields": added_fields}
    return merged


def apply_sensor_veto(
    sensor: Dict[str, Any],
    history: Optional[List[Dict[str, Any]]],
    quality: Dict[str, Any],
    expected_fields: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Return (masked sensor, masked history, gate). Vetoed fields are removed, never rewritten."""
    labels = set(quality.get("data_quality_labels") or [])
    vetoed = set(quality.get("suspect_fields") or []) | set(quality.get("missing_fields") or [])
    present = {key for frame in [sensor, *(history or [])] if isinstance(frame, dict) for key in frame}
    for group in COMPANION_GROUPS:
        if vetoed & set(group):
            vetoed |= set(group) & present
    expected = set(expected_fields or [])
    global_labels = sorted(labels & GLOBAL_VETO_LABELS)
    global_veto = bool(global_labels) or "timestamp" in vetoed
    if global_veto:
        vetoed |= expected

    if global_veto or (expected and expected <= vetoed):
        verdict = "cannot_confirm"
    elif labels or vetoed:
        verdict = "partial"
    else:
        verdict = "trusted"
    if verdict == "trusted":
        reason = "all expected readings passed the sensor check"
    elif global_veto:
        reason = f"packet could not be confirmed ({', '.join(global_labels) or 'timestamp'}); no readings used"
    else:
        reason = f"{', '.join(sorted(vetoed)) or 'readings'} failed the sensor check and were not used"
    gate = {"trust_verdict": verdict, "vetoed_fields": sorted(vetoed), "global_veto": global_veto, "reason": reason}
    return _mask(sensor, vetoed), [_mask(frame, vetoed) for frame in history or []], gate


def neutral_specialists(mode: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Empty water, nutrient and tomato results (same shapes the specialists return) for a vetoed packet."""
    meta = {"mode": mode, "backend": "rules", "source": "sensor_veto", "fallback_reason": None}
    common = {"safe_next_checks": [VETO_CHECK], "blocked_actions": [], "human_review_required": False}
    water = {"irrigation_risk_labels": [], "missing_fields": [], "suspect_fields": [], **common,
             "rationale": "Sensor check vetoed this packet; no irrigation reasoning.",
             "model_id": WATER_MODEL_ID, **meta}
    nutrient = {"nutrient_risk_labels": [], "missing_fields": [], **common,
                "rationale": "Sensor check vetoed this packet; no pH/EC reasoning.",
                "model_id": NUTRIENT_MODEL_ID, **meta}
    tomato = {"risk_labels": [], "missing_data": [], **common, "vpd_kpa": None}
    return water, nutrient, tomato
