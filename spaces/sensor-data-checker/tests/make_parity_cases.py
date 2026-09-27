"""Generate parity cases: inputs plus the Python rules' outputs, for tests/parity.test.mjs.

Run with the deployed Python minor version (3.11; the service image is python:3.11-slim):
    python3.11 spaces/sensor-data-checker/tests/make_parity_cases.py
Writes tests/parity_cases.json (not committed; regenerate when the rules change).
"""
import importlib.util
import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("sq", ROOT / "services/model-router/app/sensor_quality.py")
sq = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sq)
rng = random.Random(1127)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def us(dt):
    delta = dt - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def derive_case(farm, sensor, expected, now=None, history=None):
    out = sq.derive_sensor_quality(farm, sensor, expected, now=now, history=history)
    return {"farm": farm, "sensor": sensor, "expected": expected, "history": history,
            "now_us": None if now is None else str(us(now)), "out": out}


def jl(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()] if Path(path).exists() else []


derive_cases = []
for path in [ROOT / "private/evaluation/sensor-quality-reviewed-bundle-2026-09-27/holdout.jsonl",
             ROOT / "datasets/processed/pomona-sensor-quality-v0.1.5/all_records.jsonl",
             ROOT / "datasets/processed/pomona-sensor-quality-v0.1/all_records.jsonl"]:
    for r in jl(path):
        i = r["input"]
        ct = i.get("current_time")
        now = sq.parse_timestamp(ct) if isinstance(ct, str) else None
        derive_cases.append(derive_case(i.get("farm_context"), i.get("sensor"), i.get("expected_fields"), now))

# Malformed containers.
for farm, sensor, expected in [([], {}, ["ph"]), ({"crop": "x", "system_type": "y"}, [], ["ph"]),
                               ({"crop": "x", "system_type": "y"}, {}, "ph"), ({"crop": "x", "system_type": "y"}, {}, ["ph", 3]),
                               ({"crop": [], "system_type": {}}, {"ph": 6}, ["ph"]), ({"crop": 0, "system_type": "y"}, {"ph": 6}, ["ph"])]:
    derive_cases.append(derive_case(farm, sensor, expected))

# Timestamp fuzz: valid forms, mutations and junk.
base_forms = ["2026-03-04T05:06:07+00:00", "2026-03-04T05:06:07Z", "2026-03-04 05:06:07.123456+05:30",
              "20260304T050607+0530", "2026-W10-3T05:06:07+01:00", "2026W103T050607Z", "2026-03-04T05+02",
              "2026-03-04T05:06:07,5-03:00", "2024-02-29T23:59:59.999999+00:00", "2026-03-04T05:06:07+05:30:15.25"]
alphabet = "0123456789-:+.,TZWz x"
stamps = set(base_forms)
for form in base_forms:
    for _ in range(250):
        s = list(form)
        for _ in range(rng.choice([1, 1, 2, 3])):
            op = rng.random()
            pos = rng.randrange(len(s) + 1)
            if op < 0.4 and s:
                s[min(pos, len(s) - 1)] = rng.choice(alphabet)
            elif op < 0.7 and s:
                del s[min(pos, len(s) - 1)]
            else:
                s.insert(pos, rng.choice(alphabet))
        stamps.add("".join(s))
stamps |= {"", "2026", "2026-03-04", "2026-03-04T", "2026-03-04T24:00:00+00:00", "2026-13-01T00:00:00+00:00",
           "2026-02-29T00:00:00+00:00", "2026-03-04T05:06:07+24:00", "2026-03-04T05:06:07+23:59", "0001-01-01T00:00:00+00:00",
           "9999-12-31T23:59:59+00:00", "2026-03-04T05:06:07＋00:00", "2026-03-04é05:06:07+00:00", "2020-W53-7T00:00:00+00:00",
           "2021-W53-1T00:00:00+00:00", "2026-03-04T05:06:07.+00:00", "2026-03-04T05:06:07 +00:00", "2026-03-04T05:06:07.5x+00:00"}
timestamp_cases = []
for s in sorted(stamps):
    parsed = sq.parse_timestamp(s)
    timestamp_cases.append({"text": s, "us": None if parsed is None else str(us(parsed))})

# Numeric fuzz.
numeric_texts = ["6.5", " 6.5 ", "6.5\n", "+6.5", "-0", "1e3", "1E-2", ".5", "5.", "1_000", "1__0", "_1", "1_", "0x10",
                 "inf", "-Infinity", "NaN", "nan", "", " ", "6,5", "6.5.1", "１２", "1e", "e5", "1.5e+3", "0001",
                 "1_0.5_5", "1e1_0", "--1", "+-1", "\t7\t", "1.7976931348623157e309", " 7"]
numeric_cases = [{"value": v, "out": sq.numeric(v)} for v in numeric_texts]
numeric_cases += [{"value": v, "out": sq.numeric(v)} for v in [True, False, None, 0, 1.5, -3, [], {}, [1]]]

# Temporal: random series ending in each pattern (up to 12 values = 11 history + current).
temporal_cases = []
fields = ["air_temperature_c", "humidity_pct", "soil_moisture_pct", "ph", "ec_ms_cm", "water_temperature_c"]
for n in range(1500):
    length = rng.randrange(1, 13)
    start_value = rng.choice([6.0, 1.8, 22.0, 60.0])
    series = [round(start_value + rng.choice([0, 0, 0.01, 0.1, 0.3, 0.5, 1.0]) * rng.choice([-1, 1]) * k, 3)
              for k in range(length + 1)]
    pattern = rng.random()
    if pattern < 0.25:  # frozen tail
        tail = rng.randrange(2, 8)
        series[-tail:] = [series[-min(tail, len(series))]] * len(series[-tail:])
    elif pattern < 0.45:  # quantized probe flicker (DS18B20 0.0625 C steps), sometimes frozen
        series = [17.25 + 0.0625 * rng.choice([0, 0, 1]) for _ in series]
        if rng.random() < 0.5:
            tail = rng.randrange(1, 8)
            series[-tail:] = [17.25] * len(series[-tail:])
    elif pattern < 0.65:  # noisy start, tiny-variance tail
        series = [round(20 + rng.uniform(-0.4, 0.4), 3) for _ in series]
        tail = rng.randrange(3, 9)
        amp = rng.choice([0.0, 0.01, 0.02, 0.04, 0.06, 0.3])
        series[-tail:] = [round(20 + rng.uniform(-amp, amp), 3) for _ in series[-tail:]]
    field = rng.choice(fields)
    if rng.random() < 0.15:
        series[0] = rng.choice([14.9, -1.0, 13.0])  # impossible first value (drift-baseline anchor)
    packets = [{field: v, "timestamp": "2026-01-01T00:00:00+00:00"} for v in series]
    if rng.random() < 0.1:
        packets[rng.randrange(len(packets))][field] = rng.choice(["broken", None, True])
    history, sensor = packets[:-1], packets[-1]
    if rng.random() < 0.05:
        history.insert(0, None)
    temporal_cases.append(derive_case({"crop": "tomato", "system_type": "hydroponic"}, sensor, [field], None, history))

# Probe error codes and edges on water/substrate temperature.
for field in ("water_temperature_c", "substrate_temperature_c"):
    for value in (-127.0, 85.0, -10.0, -10.01, 0.0, -0.01, 50.0, 50.01, 60.0, 60.01, 18.5, "85"):
        derive_cases.append(derive_case({"crop": "tomato", "system_type": "hydroponic"},
                                        {field: value, "timestamp": "2026-01-01T00:00:00+00:00"}, [field]))

# Time boundaries around stale/future limits.
now = datetime(2026, 5, 6, 7, 8, 9, tzinfo=timezone.utc)
for delta_us in [-3_600_000_001, -3_600_000_000, -3_599_999_999, 0, 60_000_000, 60_000_001, 59_999_999]:
    ts = (now + timedelta(microseconds=delta_us)).isoformat()
    derive_cases.append(derive_case({"crop": "tomato", "system_type": "hydroponic"},
                                    {"ph": 6.1, "timestamp": ts}, ["ph"], now))

out = {"python": sys.version.split()[0], "derive": derive_cases + temporal_cases,
       "timestamps": timestamp_cases, "numeric": numeric_cases}
path = Path(__file__).with_name("parity_cases.json")
path.write_text(json.dumps(out))
print(f"python {out['python']}: derive={len(out['derive'])} timestamps={len(timestamp_cases)} numeric={len(numeric_cases)}")
