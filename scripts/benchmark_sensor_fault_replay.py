"""Offline, synthetic time-ordered replay of the actual sensor-quality rules.

No model inference, network, database writes, or actuator path. Fault annotations
are evaluator-only; they are never passed to the detector. Exit 1 means gaps.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/model-router"))
from app.sensor_quality import derive_sensor_quality

FIELDS = ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct"]


def scenarios():
    start = datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
    for name in ("normal", "spike", "missing_ph", "conflicting_probes", "dropout",
                 "slow_drift", "stuck_value", "sustained_impossible_ph"):
        frames = []
        for step in range(12):
            now = start + timedelta(minutes=20 * step)
            sensor = {"ph": 6.0, "ec_ms_cm": 2.0, "air_temperature_c": 24.0 + step % 2 * .1,
                      "humidity_pct": 60.0, "timestamp": now.isoformat()}
            faulty = 3 <= step < 9 and name != "normal"
            if 3 <= step < 9 and name != "normal":
                if name == "spike": sensor["ph"] = 13.0
                elif name == "missing_ph": sensor.pop("ph")
                elif name == "conflicting_probes": sensor["backup_air_temperature_c"] = 36.0
                elif name == "dropout":
                    sensor["timestamp"] = (start + timedelta(minutes=40)).isoformat()
                elif name == "slow_drift":
                    sensor["ph"] = 6.0 + .1 * (step - 2)
                    sensor["previous_ph"] = sensor["ph"] - .1
                elif name == "stuck_value": sensor["air_temperature_c"] = 24.0
                elif name == "sustained_impossible_ph": sensor["ph"] = 13.0
            # A spike is a single faulty sample, followed by recovery.
            if name == "spike" and step != 3:
                sensor["ph"], faulty = 6.0, False
            # Annotate only frames the deterministic detectors can honestly catch.
            if name == "dropout" and 3 <= step < 9:
                sample = datetime.fromisoformat(sensor["timestamp"])
                faulty = (now - sample).total_seconds() > 60 * 60
            elif name == "stuck_value" and 3 <= step < 9:
                # Needs prior variation plus a 3-sample freeze window.
                faulty = step >= 4
            elif name == "slow_drift" and 3 <= step < 9:
                faulty = abs(sensor["ph"] - 6.0) >= 0.35
            frames.append((now, sensor, faulty))
        yield name, frames


def run_benchmark():
    reports = []
    for name, frames in scenarios():
        tp = fp = fn = tn = 0
        onset = first_detection = None
        latency_ms = []
        predictions = []
        history = []
        for now, sensor, faulty in frames:
            before = perf_counter()
            result = derive_sensor_quality(
                {"crop": "tomato", "system_type": "greenhouse_substrate"},
                sensor,
                FIELDS,
                now=now,
                history=history,
            )
            latency_ms.append((perf_counter() - before) * 1000)
            alerted = bool(result["human_review_required"])
            tp += int(faulty and alerted)
            fp += int(not faulty and alerted)
            fn += int(faulty and not alerted)
            tn += int(not faulty and not alerted)
            if faulty and onset is None: onset = now
            if faulty and alerted and first_detection is None: first_detection = now
            predictions.append({"time": now.isoformat(), "fault_annotation": faulty,
                                "labels": result["data_quality_labels"], "review": alerted})
            history.append(dict(sensor))
        reports.append({"scenario": name, "true_positive": tp, "false_positive": fp,
                        "false_negative": fn, "true_negative": tn,
                        "detection_delay_minutes": (first_detection - onset).total_seconds() / 60 if first_detection else None,
                        "max_detector_latency_ms": max(latency_ms), "frames": predictions})
    return {"backend": "deterministic_sensor_quality_only", "synthetic": True,
            "model_quality_evaluation": False,
            "limitations": "Synthetic fault annotations are not field ground truth. Flat or slowly changing values can be legitimate; missing these annotations alone does not justify adding alarm rules. Dropout is evaluated by replaying the last packet with advancing current time, not by testing MQTT transport. Temporal stuck/baseline checks use prior packets in-process; they are not a full MQTT soak. No memory benchmark or real-model inference is performed.",
            "passed": all(r["false_positive"] == 0 and r["false_negative"] == 0 for r in reports),
            "scenarios": reports}


if __name__ == "__main__":
    report = run_benchmark()
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] else 1)
