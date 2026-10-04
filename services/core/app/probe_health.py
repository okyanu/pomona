"""Probe health from calibration history: does a pH probe still respond like it did when new?

Every two-point (or more) buffer calibration says how many volts the probe moves per pH unit
(its sensitivity, mV/pH) and what voltage it gives at pH 7. A healthy probe keeps both roughly
constant; a worn or fouled one loses sensitivity and its pH 7 voltage wanders. This module fits
those two numbers from each stored calibration (CalibrationPoint.raw is the probe voltage in
volts, as logged by the cress logger) and compares the latest with the first.

Advisory only: it recommends cleaning, re-checking buffers or replacing a probe, never acts, and
never edits a stored raw reading or calibration.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

# Any real probe + amplifier board lands in this window (bare probe ~59 mV/pH, boards up to ~250).
ABS_MIN_MV_PER_PH = 20.0
ABS_MAX_MV_PER_PH = 600.0
# Sensitivity of the latest calibration as a share of the first one.
OK_PCT = 90.0
WORN_PCT = 80.0
# Voltage at pH 7 moving more than this between first and latest calibration (volts).
V7_SHIFT_V = 0.10
# More than two buffers: the straight line must fit every point within this many pH.
MAX_FIT_ERROR_PH = 0.25


def fit_calibration(points: Iterable[Any]) -> Optional[Dict[str, float]]:
    """Least-squares line volts = a + b * pH through the points; None if it cannot be fitted.

    Returns sensitivity_mv_per_ph (|b| * 1000), signed slope_v_per_ph, v_at_ph7 and the worst
    residual in pH.
    """
    refs = [float(p.reference) for p in points]
    raws = [float(p.raw) for p in points]
    if len(refs) < 2 or len(set(refs)) < 2:
        return None
    n = len(refs)
    mean_x, mean_y = sum(refs) / n, sum(raws) / n
    sxx = sum((x - mean_x) ** 2 for x in refs)
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(refs, raws)) / sxx
    if slope == 0:
        return None
    intercept = mean_y - slope * mean_x
    worst = max(abs((y - intercept) / slope - x) for x, y in zip(refs, raws))
    return {"sensitivity_mv_per_ph": abs(slope) * 1000.0, "slope_v_per_ph": slope,
            "v_at_ph7": intercept + slope * 7.0, "worst_fit_error_ph": worst}


def _stream_key(event: Any) -> tuple:
    return (event.farm_id, event.zone_id, event.device_id, event.sensor_id)


def assess_probe(history: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Status of one probe from its fitted calibrations, oldest first."""
    reasons: List[str] = []
    if not history:
        return {"status": "no_data", "reasons": ["no usable pH calibration recorded"]}
    first, latest = history[0], history[-1]
    status = "ok"
    if not ABS_MIN_MV_PER_PH <= latest["sensitivity_mv_per_ph"] <= ABS_MAX_MV_PER_PH:
        status = "suspect"
        reasons.append("latest sensitivity is outside 20-600 mV/pH: identical, swapped or wrong buffers?")
    if latest["worst_fit_error_ph"] > MAX_FIT_ERROR_PH:
        status = "suspect"
        reasons.append(f"latest calibration points do not lie on a line (worst {latest['worst_fit_error_ph']:.2f} pH)")
    result: Dict[str, Any] = {"calibrations": len(history), "latest": latest, "first": first}
    if len(history) == 1:
        if status == "ok":
            status = "baseline_only"
            reasons.append("one calibration so far: a trend needs at least two")
    else:
        pct = 100.0 * latest["sensitivity_mv_per_ph"] / first["sensitivity_mv_per_ph"]
        result["sensitivity_vs_first_pct"] = round(pct, 1)
        days = (datetime.fromisoformat(latest["performed_at"]) - datetime.fromisoformat(first["performed_at"])).total_seconds() / 86400
        if days > 0:
            result["sensitivity_lost_pct_per_30_days"] = round((100.0 - pct) / days * 30.0, 2)
        shift = latest["v_at_ph7"] - first["v_at_ph7"]
        result["v_at_ph7_shift_v"] = round(shift, 4)
        if status == "ok":
            if pct < WORN_PCT:
                status = "worn"
                reasons.append(f"sensitivity is {pct:.0f} % of the first calibration: clean the probe, check the buffers, then replace it if it stays low")
            elif pct < OK_PCT:
                status = "weakening"
                reasons.append(f"sensitivity is {pct:.0f} % of the first calibration: clean the probe and recalibrate soon")
        if abs(shift) >= V7_SHIFT_V:
            reasons.append(f"pH 7 voltage moved {shift * 1000:+.0f} mV since the first calibration: reference junction or cable?")
            if status == "ok":
                status = "weakening"
    result["status"] = status
    result["reasons"] = reasons
    return result


def probe_health(calibrations: Iterable[Any], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """One entry per (farm, zone, device, sensor) with pH calibrations, worst status first."""
    now = now or datetime.now(timezone.utc)
    streams: Dict[tuple, List[Any]] = {}
    for event in calibrations:
        if event.measurement == "ph":
            streams.setdefault(_stream_key(event), []).append(event)
    rank = {"suspect": 0, "worn": 1, "weakening": 2, "baseline_only": 3, "ok": 4, "no_data": 5}
    entries = []
    for (farm_id, zone_id, device_id, sensor_id), events in streams.items():
        history = []
        for event in sorted(events, key=lambda e: e.performed_at):
            fit = fit_calibration(event.points)
            if fit:
                history.append({"performed_at": event.performed_at.astimezone(timezone.utc).isoformat(),
                                "calibration_id": event.id, **{k: round(v, 4) for k, v in fit.items()}})
        assessment = assess_probe(history)
        last = events and max(e.performed_at for e in events)
        assessment["days_since_last_calibration"] = (round((now - last).total_seconds() / 86400, 1)
                                                     if last else None)
        entries.append({"farm_id": farm_id, "zone_id": zone_id, "device_id": device_id, "sensor_id": sensor_id,
                        "measurement": "ph", **assessment})
    entries.sort(key=lambda e: (rank.get(e["status"], 9), e["sensor_id"]))
    return entries
