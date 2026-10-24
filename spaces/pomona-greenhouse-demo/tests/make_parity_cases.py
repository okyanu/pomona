#!/usr/bin/env python3
"""Write the parity case files for the demo page's JavaScript.

Run with the model-router environment (it imports services/model-router/app):
  services/model-router/.venv/bin/python spaces/pomona-greenhouse-demo/tests/make_parity_cases.py

parity_cases.json   tomato rules alone: random and boundary inputs (some with vetoed_fields) and the
                    answers of app.tomato_reasoner.derive_tomato_risk.
chain_cases.json    the full demo chain (sensor quality -> sensor veto -> tomato rules) on packets with
                    impossible, missing, conflicting, unit-mismatched, non-numeric and badly timestamped
                    values. The expected answers are the sensor_quality, trust_gate and crop_risk blocks
                    of the real app.pipeline.evaluate_pipeline (audit writes and the clock patched out),
                    so the chain is not re-implemented here and cannot drift from the platform.
parity.test.cjs then runs the page's own JavaScript on the same inputs.
Both files are generated (gitignored); regenerate them when the rules change.
"""
import asyncio
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/model-router"))
from app import pipeline  # noqa: E402
from app.tomato_reasoner import derive_tomato_risk  # noqa: E402

HERE = Path(__file__).parent
rng = random.Random(1004)
systems = ["controlled_greenhouse", "hydroponic", "greenhouse_substrate", "hydroponic_greenhouse"]


def pick(lo, hi, digits):
    return rng.choice([None, round(rng.uniform(lo, hi), digits)])


# -- tomato rules alone --------------------------------------------------------------------------
cases = [{"system_type": rng.choice(systems), "crop": "tomato", "growth_stage": "flowering",
          "air_temperature_c": pick(-10, 65, 1), "humidity_pct": pick(-5, 105, 1), "ph": pick(3, 10, 2),
          "ec_ms_cm": pick(0, 11, 2), "substrate_temperature_c": pick(5, 40, 1),
          "substrate_moisture_pct": pick(0, 100, 1)} for _ in range(20000)]
for temp in (-5, 0, 10, 17, 20, 24, 28, 35, 60):  # VPD threshold and range boundaries
    for humidity in (0, 35, 60, 75, 80, 84.9, 85, 90, 100):
        cases.append({"system_type": "controlled_greenhouse", "crop": "tomato", "growth_stage": "fruiting",
                      "air_temperature_c": temp, "humidity_pct": humidity, "ph": 6.2, "ec_ms_cm": 2.4,
                      "substrate_temperature_c": 22, "substrate_moisture_pct": 45})
TOMATO_FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_temperature_c", "substrate_moisture_pct"]
for _ in range(1500):  # the sensor veto marks fields as already reported; the rules must skip them as missing
    case = {"system_type": rng.choice(systems), "crop": "tomato", "growth_stage": "flowering",
            "air_temperature_c": pick(-10, 65, 1), "humidity_pct": pick(-5, 105, 1), "ph": pick(3, 10, 2),
            "ec_ms_cm": pick(0, 11, 2), "substrate_temperature_c": pick(5, 40, 1),
            "substrate_moisture_pct": pick(0, 100, 1)}
    case["vetoed_fields"] = rng.sample(TOMATO_FIELDS + ["previous_ph", "timestamp"], rng.randint(0, 4))
    for field in case["vetoed_fields"]:
        if rng.random() < 0.5:
            case.pop(field, None)  # the veto removes the field from the packet
    cases.append(case)
expected = [derive_tomato_risk(case) for case in cases]
out = HERE / "parity_cases.json"
out.write_text(json.dumps({"cases": cases, "expected": expected}))
low_vpd = sum(1 for c, e in zip(cases, expected)
              if e["vpd_kpa"] is not None and e["vpd_kpa"] < 0.4 and (c["humidity_pct"] or 0) < 85)
print(f"{len(cases)} tomato cases ({low_vpd} reach fungal_pressure only through low VPD) -> {out.name}")

# -- sensor quality -> veto -> tomato chain --------------------------------------------------------
NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
chain_rng = random.Random(2711)
chain_systems = ["greenhouse_substrate", "greenhouse_substrate", "controlled_greenhouse", "hydroponic", "soil_field"]
NOMINAL = {"air_temperature_c": 24.0, "humidity_pct": 60.0, "ph": 6.2, "ec_ms_cm": 2.5,
           "substrate_temperature_c": 22.0, "substrate_moisture_pct": 45.0}
# Ranges wide enough to cross every sensor-quality limit and every tomato threshold.
RANGES = {"air_temperature_c": (-15, 70, 1), "humidity_pct": (-5, 105, 1), "ph": (2, 13, 2),
          "ec_ms_cm": (-1, 13, 2), "substrate_temperature_c": (-15, 65, 1), "substrate_moisture_pct": (-5, 105, 1)}
JUNK = ["abc", "", True, False, "nan", "inf", "--", [], {}]  # numeric strings like "6.5" are left out: the tomato rules compare numbers
stamp = lambda dt: dt.isoformat().replace("+00:00", "Z")  # noqa: E731


def timestamp_variant(r):
    kind = r.choice(["fresh"] * 14 + ["offset"] * 2 + ["stale", "stale", "future", "future", "missing", "none", "invalid", "naive", "number"])
    if kind == "fresh":
        return stamp(NOW - timedelta(seconds=r.uniform(0, 3500)))
    if kind == "stale":
        return stamp(NOW - timedelta(seconds=r.choice([3601, 3700, 7200, 86400, r.uniform(3600, 400000)])))
    if kind == "future":
        return stamp(NOW + timedelta(seconds=r.choice([30, 60, 60.5, 61, 300, 3600])))
    if kind == "invalid":
        return r.choice(["yesterday", "2026-13-40T00:00:00Z", "2026-10-06", "0001-01-01T00:00:00+01:00"])
    if kind == "naive":
        return "2026-10-06T08:55:00"
    if kind == "offset":
        return (NOW - timedelta(seconds=r.uniform(0, 3000))).astimezone(timezone(timedelta(hours=r.choice([-7, 2, 5.5])))).isoformat()
    if kind == "number":
        return r.choice([1791277200, 0, 1.5])
    return kind  # "missing" / "none" are handled by the caller


def random_sensor():
    sensor = {}
    for field, (lo, hi, digits) in RANGES.items():
        draw = chain_rng.random()
        if draw < 0.04:
            continue  # key absent
        if draw < 0.08:
            sensor[field] = None
        elif draw < 0.10:
            sensor[field] = chain_rng.choice(JUNK)
        elif draw < 0.50:
            sensor[field] = round(NOMINAL[field] + chain_rng.uniform(-3, 3), digits)  # near nominal
        else:
            sensor[field] = round(chain_rng.uniform(lo, hi), digits)
    if chain_rng.random() < 0.15:
        base = sensor.get("air_temperature_c")
        base = base if isinstance(base, float) else 24.0
        sensor["backup_air_temperature_c"] = round(base + chain_rng.choice([0.5, -7.9, 8, -8, 12, 30]), 1)
    if chain_rng.random() < 0.10:
        base = sensor.get("ph")
        base = base if isinstance(base, float) else 6.2
        sensor["previous_ph"] = round(base + chain_rng.choice([0.1, -0.79, 0.8, -0.8, 2]), 2)
    if chain_rng.random() < 0.08:
        sensor["temperature_f"] = chain_rng.choice([75.2, 24, "abc", None])
    if chain_rng.random() < 0.05:
        sensor["water_temperature_c"] = chain_rng.choice([-127, 85, 22.5, 55.0, 0.0, 50.0])
    ts = timestamp_variant(chain_rng)
    if ts == "none":
        sensor["timestamp"] = None
    elif ts != "missing":
        sensor["timestamp"] = ts
    return sensor


def nominal(**overrides):
    sensor = {**NOMINAL, "timestamp": stamp(NOW - timedelta(minutes=2))}
    for key, value in overrides.items():
        if value is KeyError:
            sensor.pop(key, None)
        else:
            sensor[key] = value
    return sensor


packets = []
for _ in range(2500):
    packets.append((chain_rng.choice(chain_systems), random_sensor()))
for system in ("greenhouse_substrate", "controlled_greenhouse"):
    # One field at a time across every sensor-quality limit and tomato threshold.
    boundaries = {
        "ph": [2.99, 3.0, 3.5, 3.51, 5.3, 5.31, 7.2, 8.99, 9.0, 11.0, 11.01],
        "ec_ms_cm": [-0.01, 0, 0.009, 0.01, 0.05, 0.8, 4.5, 10, 10.01, 12, 12.01],
        "air_temperature_c": [-10.01, -10, -5.01, -5, 16, 30, 60, 60.01, 65, 65.01],
        "humidity_pct": [-0.1, 0, 84.9, 85, 100, 100.1],
        "substrate_temperature_c": [-10.01, -10, 16, 30, 60, 60.01],
        "substrate_moisture_pct": [9.9, 10, 85, 85.1],
    }
    for field, values in boundaries.items():
        for value in values:
            packets.append((system, nominal(**{field: value})))
    for field in NOMINAL:
        packets.append((system, nominal(**{field: None})))
        packets.append((system, nominal(**{field: KeyError})))
        for junk in ("abc", True, "nan"):
            packets.append((system, nominal(**{field: junk})))
    packets.append((system, nominal(ph=None, ec_ms_cm=None, air_temperature_c=None, humidity_pct=None, substrate_moisture_pct=None)))
    packets.append((system, nominal(ph=14, ec_ms_cm=13, air_temperature_c=80, humidity_pct=120, substrate_moisture_pct=50)))
    for backup in (16.0, 16.1, 32.0, 24.0):  # conflicting backup temperature at the 8 C limit
        packets.append((system, nominal(backup_air_temperature_c=backup)))
    for previous in (6.2, 5.4, 5.41, 7.0, 7.01):  # pH jump at the 0.8 limit
        packets.append((system, nominal(previous_ph=previous)))
    packets.append((system, nominal(ph=13, previous_ph=6.2)))
    for fahrenheit in (75.2, "abc", None):  # unit mismatch / non-numeric / null
        packets.append((system, nominal(temperature_f=fahrenheit)))
    packets.append((system, nominal(air_temperature_c=KeyError, temperature_f=75.2)))
    for seconds in (-60, -3599, -3600, -3600.000001, -3601, -86400, 0, 30, 60, 60.000001, 61, 3600):  # age = -offset from now
        packets.append((system, nominal(timestamp=stamp(NOW + timedelta(seconds=seconds)))))
    for text in ("2026-10-06T08:59:00+00:00", "2026-10-06T10:59:00+02:00", "2026-10-06T08:59:00", "yesterday", "", None, 12345, True):
        packets.append((system, nominal(timestamp=text)))
    packets.append((system, nominal(timestamp=KeyError)))
    packets.append((system, nominal(timestamp="2026-10-06T08:59:00.123456Z")))


def python_chain(system_type, sensor):
    """The Python chain, run through the platform pipeline itself (water/nutrient/safety outputs are ignored)."""
    fields = [f for f in pipeline.DEFAULT_EXPECTED_FIELDS
              if system_type == "greenhouse_substrate" or f != "substrate_moisture_pct"]
    farm = {"crop": "tomato", "system_type": system_type, "growth_stage": "vegetative"}
    result = asyncio.run(pipeline.evaluate_pipeline(farm, sensor, fields, None, "parity", "rules_only"))
    quality = {key: result["sensor_quality"][key] for key in (
        "data_quality_labels", "missing_fields", "suspect_fields", "safe_next_checks", "human_review_required", "rationale")}
    return farm, {"sensor_quality": quality, "trust_gate": result["trust_gate"], "crop_risk": result["crop_risk"]}


pipeline.write_pipeline_audit = lambda record: None
pipeline._now = lambda: NOW
chain_in, chain_out = [], []
for system_type, sensor in packets:
    farm, answer = python_chain(system_type, sensor)
    chain_in.append({"farm": farm, "sensor": sensor})
    chain_out.append(answer)
out = HERE / "chain_cases.json"
out.write_text(json.dumps({"now": stamp(NOW), "cases": chain_in, "expected": chain_out}))
verdicts = {}
for answer in chain_out:
    verdict = answer["trust_gate"]["trust_verdict"]
    verdicts[verdict] = verdicts.get(verdict, 0) + 1
labels = sorted({label for answer in chain_out for label in answer["sensor_quality"]["data_quality_labels"]})
print(f"{len(chain_in)} chain cases {dict(sorted(verdicts.items()))}; sensor-quality labels seen: {', '.join(labels)} -> {out.name}")
