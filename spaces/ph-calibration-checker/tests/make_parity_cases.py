#!/usr/bin/env python3
"""Write parity_cases.json: random and edge-case calibrations with the Python answers.

References: devices/esp32-cress-logger/tools/ph_calibrate.py (evaluate) and
services/core/app/probe_health.py (fit_calibration, assess_probe); both are standard library only.
  python3 spaces/ph-calibration-checker/tests/make_parity_cases.py
"""
import importlib.util
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


calibrate = load("ph_calibrate", "devices/esp32-cress-logger/tools/ph_calibrate.py")
health = load("probe_health", "services/core/app/probe_health.py")

rng = random.Random(1005)
T0 = datetime(2026, 10, 1, tzinfo=timezone.utc)


def volts():
    return round(rng.choice([rng.uniform(0.0, 4.5), rng.uniform(1.0, 3.3), rng.uniform(2.2, 2.8)]), rng.choice([2, 3, 4]))


evaluate_cases = []
for _ in range(6000):
    v7, v4 = volts(), volts()
    shape = rng.random()
    if shape < 0.08:
        v4 = v7                                         # identical buffers
    elif shape < 0.30:
        v4 = round(v7 + rng.choice([-1, 1]) * rng.uniform(0.3, 0.7), 3)   # a believable ~180 mV/pH board
    elif shape < 0.36:
        v4 = round(v7 + rng.choice([-1, 1]) * rng.uniform(0.0, 0.03), 3)  # buffers nearly the same
    v10 = rng.choice([None, round(v7 - (v4 - v7) + rng.uniform(-0.2, 0.2), 3), volts()])
    expected_mv = rng.choice([0.0, 59.16, 180.0, 250.0])
    expected_sign = rng.choice([-1, 0, 1])
    evaluate_cases.append({"v7": v7, "v4": v4, "v10": v10, "expected_mv": expected_mv, "expected_sign": expected_sign,
                           "expected": calibrate.evaluate(v7, v4, v10, expected_mv, expected_sign)})


def entry(v7, v4, days):
    fit = health.fit_calibration([SimpleNamespace(reference=7.0, raw=v7), SimpleNamespace(reference=4.0, raw=v4)])
    return {"performed_at": (T0 + timedelta(days=days)).isoformat(), **fit}


trend_cases = []
while len(trend_cases) < 4000:
    first_v7 = round(rng.uniform(2.2, 2.8), 3)
    first_mv = rng.uniform(100, 260)
    sign = rng.choice([-1, 1])
    first_v4 = round(first_v7 - sign * 3 * first_mv / 1000, 4)
    keep = rng.choice([1.0, 0.97, 0.92, 0.88, 0.83, 0.78, 0.6, rng.uniform(0.3, 1.2)])
    shift = rng.choice([0.0, 0.0, 0.03, 0.099, 0.1, 0.12, -0.15])
    latest_v7 = round(first_v7 + shift, 4)
    latest_v4 = round(latest_v7 - sign * 3 * first_mv * keep / 1000, 4)
    a, b = entry(first_v7, first_v4, 0), entry(latest_v7, latest_v4, 30)
    if not health.ABS_MIN_MV_PER_PH <= b["sensitivity_mv_per_ph"] <= health.ABS_MAX_MV_PER_PH:
        continue  # an implausible latest calibration is reported as a failure, not as a trend
    result = health.assess_probe([a, b])
    trend_cases.append({"first": {"v7": first_v7, "v4": first_v4}, "latest": {"v7": latest_v7, "v4": latest_v4},
                        "expected": {"status": result["status"], "reasons": result["reasons"],
                                     "sensitivity_vs_first_pct": result["sensitivity_vs_first_pct"],
                                     "v_at_ph7_shift_v": result["v_at_ph7_shift_v"]}})

out = Path(__file__).with_name("parity_cases.json")
out.write_text(json.dumps({"evaluate": evaluate_cases, "trend": trend_cases}))
statuses = {}
for case in trend_cases:
    statuses[case["expected"]["status"]] = statuses.get(case["expected"]["status"], 0) + 1
print(f"{len(evaluate_cases)} calibrations, {len(trend_cases)} trends {statuses} -> {out.name}")
