"""Offline chronological replay of the real advisory simulator versus persistence.

No fitting, network, actuators, or parameter selection on the evaluation block.
Input: one farm/zone JSONL stream with timestamp, state and optional scenario.
Scenarios must have been recorded at forecast origin, not reconstructed later.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from typing import Any

from .main import GreenhouseState, ScenarioRequest, simulate

FIELDS = ("air_temperature_c", "humidity_pct", "soil_moisture_pct",
          "substrate_moisture_pct", "root_zone_moisture_pct")


def replay(records: list[dict[str, Any]], *, split_index: int, horizons=(1, 2, 4),
           step_minutes: int = 15, parameter_version: str = "linear-v0-defaults") -> dict:
    if not 0 < split_index < len(records) - 1:
        raise ValueError("Need nonempty earlier calibration block and at least two held-out rows")
    if not horizons or any(type(h) is not int or not 1 <= h <= 48 for h in horizons):
        raise ValueError("Horizons must be integer steps in 1..48")
    if type(step_minutes) is not int or not 1 <= step_minutes <= 1440:
        raise ValueError("Invalid step_minutes")
    scopes = {(r.get("farm_id"), r.get("zone_id")) for r in records}
    if len(scopes) != 1 or any(not x for x in next(iter(scopes))):
        raise ValueError("Replay requires exactly one explicit farm/zone")
    times = [datetime.fromisoformat(r["timestamp"].replace("Z", "+00:00")) for r in records]
    if any(t.tzinfo is None for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("Timestamps must be aware, strictly increasing and unique")
    for r in records:
        for f in FIELDS:
            value = r["state"].get(f)
            if value is not None and (type(value) not in (float, int) or not math.isfinite(value)):
                raise ValueError("Measurements must be finite numbers, not booleans")
        GreenhouseState.model_validate(r["state"])
    lookup = {t: r for t, r in zip(times, records)}
    results = {}; rejected_origins = 0
    for h in sorted(set(horizons)):
        errors = {f: {"twin": [], "persistence": []} for f in FIELDS}
        missing_targets = 0
        for origin in range(split_index, len(records)):
            row = records[origin]
            target = lookup.get(times[origin] + timedelta(minutes=step_minutes * h))
            if target is None:
                missing_targets += 1; continue
            bad = lambda r: r.get("quality", "unknown") != "valid" or bool(
                (r.get("sensor_quality") or {}).get("human_review_required") or
                (r.get("sensor_quality") or {}).get("data_quality_labels"))
            if bad(row) or bad(target):
                rejected_origins += 1; continue
            # Keep the scenario's end horizon fixed across scoring horizons.
            output = simulate(ScenarioRequest(state=row["state"], scenario=row.get("scenario", {}),
                sensor_quality=row.get("sensor_quality"), horizon_steps=max(horizons),
                step_minutes=step_minutes, parameter_version=parameter_version))
            prediction = output.trajectory[h-1]
            for f in FIELDS:
                actual, initial = target["state"].get(f), row["state"].get(f)
                if actual is not None and initial is not None:
                    errors[f]["twin"].append(prediction[f] - actual)
                    errors[f]["persistence"].append(initial - actual)
        metrics = {}
        for f, models in errors.items():
            if not models["twin"]: continue
            metrics[f] = {name: {"n": len(e), "mae": sum(abs(x) for x in e)/len(e),
                         "rmse": math.sqrt(sum(x*x for x in e)/len(e)), "bias": sum(e)/len(e)}
                         for name, e in models.items()}
        results[str(h * step_minutes)] = {"variables": metrics, "missing_target_pairs": missing_targets}
    digest = hashlib.sha256(json.dumps(records, sort_keys=True, allow_nan=False).encode()).hexdigest()
    return {"dataset_sha256": digest, "parameter_version": parameter_version,
            "calibration_rows_reserved": split_index, "evaluation_rows": len(records)-split_index,
            "evaluation_start": times[split_index].isoformat(), "metrics_by_horizon_minutes": results,
            "rejected_quality_pairs": rejected_origins, "parameters_fitted": False,
            "field_validated": False, "notes": ["No gap filling; exact timestamp targets only",
              "Zero-scenario linear twin equals persistence; a tie is not evidence of improvement",
              "Caller must preserve origin-time scenario provenance; no future-derived scenarios",
              "This runner reserves an earlier block but does not calibrate parameters"]}
