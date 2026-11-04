"""Generate parity cases for persistent.js: inputs plus the Python code's outputs, for tests/persistent.test.mjs.

Run with the deployed Python minor version (3.11; the service image is python:3.11-slim; the checks avoid sum() of
floats, whose result changed in 3.12, so the answers do not depend on the minor version):
    python3.11 spaces/sensor-data-checker/tests/make_persistent_cases.py
Writes tests/persistent_cases.json (not committed; regenerate when the rules change).

Python code under test (loaded by path, stdlib only, never reimplemented here):
    services/core/app/trusted_baseline.py        stream_baseline
    services/model-router/app/sensor_quality.py  derive_sensor_quality, apply_persistent_checks
    services/model-router/app/trust_gate.py      apply_sensor_veto

Groups:
    format     Python's number formatting and rounding (f"{x:g}", :+.1f, :.0%, round(x, 6), timedelta, isoformat)
    baseline   stream_baseline on streams at 30 s to 1 h cadence, with vetoes, calibrations, lapses, odd values
    checks     apply_persistent_checks on a reference (built by stream_baseline or written by hand) at the boundary
               of every check, positive and negative: level drift, persistent and adaptive stuck, step, noise
    derive     derive_sensor_quality with a stream_baseline (the default check, the review flag, malformed inputs)
    streams    whole streams through the checker's per-reading flow (reference from the earlier readings, less the
               fields the veto removed): the inputs are CSV-like packets, the answers come from the Python
               functions above run in the same order checker.js runs them
"""
import importlib.util
import json
import math
import random
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sq = load("sq", "services/model-router/app/sensor_quality.py")
tb = load("tb", "services/core/app/trusted_baseline.py")
tg = load("tg", "services/model-router/app/trust_gate.py")
rng = random.Random(20261105)
EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
T0 = datetime(2026, 3, 1, 6, 0, tzinfo=timezone.utc)
FARM = {"crop": "watercress", "system_type": "hydroponic"}
ROUTINE = "continue routine monitoring"
FUTURE_CHECK = "verify device clock: sample timestamp is more than 60 seconds in the future"


def us(dt):
    delta = dt - EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def from_us(value):
    return EPOCH + timedelta(microseconds=value)


def iso(dt, style=0):
    """One timestamp in a few spellings that all mean the same instant."""
    if style == 1:
        return dt.isoformat().replace("+00:00", "Z")
    if style == 2:
        return dt.astimezone(timezone(timedelta(hours=4))).isoformat()
    return dt.isoformat()


# ---- format --------------------------------------------------------------------------------------------------------
format_cases = []
tricky = [0.0, -0.0, 0.5, -0.5, 1.5, 2.5, 0.25, 0.75, 1.25, -0.25, -1.25, 0.05, 0.15, 0.35, 0.045, 12.5, 100.5, 0.125,
          0.0078125, 0.0234375, 0.03125, 0.09375, 123456.5, 123455.5, 1234565.0, 1234575.0, 999999.5, 9999995.0, 99999.95,
          0.0001, 0.00012345675, 0.0000999999, 0.00009999995, 1e-5, 1.5e-5, 1e6, 1e15, 1e16, 1e22, 1.7976931348623157e308,
          5e-324, 2.2250738585072014e-308, 7.55, 6.875, 6.85, 6.5, 14.9, 3.0, 11.0, 12.0, -3.04, -3.05, -0.04, -0.05, -0.06,
          1 / 3, 2 / 3, 0.1 + 0.2, 4503599627370497.5, 3.4999999999999996, 0.30000000000000004]
for _ in range(500):
    tricky.append(rng.choice([rng.uniform(-20, 20), rng.uniform(-1, 1) * 10 ** rng.randrange(-8, 10),
                              rng.randrange(-5000, 5000) / rng.choice([2, 4, 8, 16, 32, 64, 128, 256, 20, 40, 1000, 10])]))
for x in tricky:
    format_cases.append({"kind": "g", "x": x, "out": f"{x:g}"})
    format_cases.append({"kind": "fixed1s", "x": x, "out": f"{x:+.1f}"})
    format_cases.append({"kind": "fixed1", "x": x, "out": f"{x:.1f}"})
    format_cases.append({"kind": "pct0", "x": x, "out": f"{x:.0%}"})
    format_cases.append({"kind": "round6", "x": x, "out": round(x, 6)})
    format_cases.append({"kind": "round4", "x": x, "out": round(x, 4)})
for share in [k / n for n in (16, 32, 40, 64, 160, 200, 8, 3, 7, 15, 17) for k in range(0, n + 1)]:
    format_cases.append({"kind": "round4", "x": share, "out": round(share, 4)})
    format_cases.append({"kind": "pct0", "x": share, "out": f"{share:.0%}"})
for seconds in [0.0, 1.0, 4.0 * 1.0000005, 4.0 * 1.0000015, 4.0 * 0.1234565, 300.0, 4.0 * 75.0, 4.0 * 74.9999999, 4.0 * 12345.678901,
                -1.5e-6, 2.5e-6, 3.5e-6, 0.0000005, 0.0000015, 1.4999999e-6, 4.0 * 17.0000005, 4.0 * 3600.1234565, 1e9, 4.0 * 1e7 + 0.5e-6]:
    format_cases.append({"kind": "timedelta", "x": seconds, "out": str(timedelta(seconds=seconds) // timedelta(microseconds=1))})
for _ in range(300):
    seconds = rng.choice([4.0 * rng.randrange(0, 4_000_000_000) / 1e6, rng.uniform(0, 1e6), 4.0 * rng.randrange(0, 1000) + rng.random() * 1e-5])
    format_cases.append({"kind": "timedelta", "x": seconds, "out": str(timedelta(seconds=seconds) // timedelta(microseconds=1))})
for value in [0, 1, -1, 999_999, 1_000_000, 1_000_001, 3_000_000_001, 10 ** 15 + 7, 2 ** 53 + 1, 2 ** 53 + 3, 10 ** 17 + 1, 10 ** 17 + 3,
              -(10 ** 17 + 1), 252_455_615_999_999_999, 4_000_000_000_000_001, 8_999_999_999_999_999]:
    format_cases.append({"kind": "total_seconds", "x": str(value), "out": timedelta(microseconds=value).total_seconds()})
for _ in range(200):
    value = rng.randrange(0, 2 * 10 ** rng.randrange(6, 18))
    format_cases.append({"kind": "total_seconds", "x": str(value), "out": timedelta(microseconds=value).total_seconds()})
for value in [0, 1, 999_999, 1_000_000, 86_399_999_999, 86_400_000_000, -1, -86_400_000_000, 1_772_344_800_000_000, 1_772_344_800_123_456,
              -62_135_596_800_000_000, 253_402_300_799_999_999, 951_782_400_000_000, 4_107_542_400_000_000, 68_169_600_000_000]:
    format_cases.append({"kind": "isoformat", "x": str(value), "out": from_us(value).isoformat()})
for _ in range(300):
    value = rng.randrange(-62_135_596_800_000_000, 253_402_300_800_000_000)
    format_cases.append({"kind": "isoformat", "x": str(value), "out": from_us(value).isoformat()})

# ---- streams of readings ---------------------------------------------------------------------------------------------
FIELD_BASE = {"ph": 6.2, "ec_ms_cm": 1.8, "air_temperature_c": 22.0, "humidity_pct": 65.0, "soil_moisture_pct": 48.0,
              "substrate_temperature_c": 20.0}
FIELD_NOISE = {"ph": 0.03, "ec_ms_cm": 0.05, "air_temperature_c": 0.1, "humidity_pct": 1.0, "soil_moisture_pct": 0.3,
               "substrate_temperature_c": 0.05}
FIELD_DIGITS = {"ph": 2, "ec_ms_cm": 2, "air_temperature_c": 1, "humidity_pct": 1, "soil_moisture_pct": 1, "substrate_temperature_c": 1}
FAULTS = ["normal", "stuck_ph", "stuck_ec", "stuck_air", "stuck_hum", "stuck_moist", "stuck_subt", "step_hum", "step_air", "step_moist",
          "step_subt", "step_ph", "drift_ph", "drift_ec", "noisy_ph", "noisy_air", "noisy_hum", "noisy_moist", "noisy_subt",
          "ramp_air", "rewet", "oor", "missing", "veto_ph", "all"]


def make_stream(fault, n, cadence, r, field_set=None, start=T0, style=0, span=None):
    """Packets (dicts of strings and numbers as a CSV or JSON would give them), oldest first."""
    fields = field_set or list(FIELD_BASE)
    packets = []
    f0 = r.randrange(max(2, n // 3), max(3, n - 2))
    f1 = n if r.random() < 0.6 else min(n, f0 + r.randrange(2, max(3, n // 3)))
    if span:
        f0, f1 = span
    held = {}
    for k in range(n):
        t = start + timedelta(seconds=cadence * k)
        packet = {"timestamp": iso(t, style)}
        for f in fields:
            wobble = r.uniform(-1, 1) * FIELD_NOISE[f]
            value = FIELD_BASE[f] + wobble + (0.0003 * k if f == "air_temperature_c" else 0)
            if f == "soil_moisture_pct":
                value -= 0.002 * k
            packet[f] = round(value, FIELD_DIGITS[f])
        active = f0 <= k < f1
        minutes = cadence * (k - f0) / 60
        if active:
            def stuck(f):
                held.setdefault(f, packet[f])
                packet[f] = held[f]
            if fault == "stuck_ph": stuck("ph")
            elif fault == "stuck_ec": stuck("ec_ms_cm")
            elif fault == "stuck_air": stuck("air_temperature_c")
            elif fault == "stuck_hum": stuck("humidity_pct")
            elif fault == "stuck_moist": stuck("soil_moisture_pct")
            elif fault == "stuck_subt": stuck("substrate_temperature_c")
            elif fault == "step_hum": packet["humidity_pct"] = round(packet["humidity_pct"] + r.choice([9.0, 14.0, 22.0, -18.0]), 1)
            elif fault == "step_air": packet["air_temperature_c"] = round(packet["air_temperature_c"] + r.choice([2.5, 4.0, 7.0, -6.0]), 1)
            elif fault == "step_moist": packet["soil_moisture_pct"] = round(packet["soil_moisture_pct"] + r.choice([5.0, 12.0, -14.0, 30.0]), 1)
            elif fault == "step_subt": packet["substrate_temperature_c"] = round(packet["substrate_temperature_c"] + r.choice([1.0, 2.0, -2.5]), 1)
            elif fault == "step_ph": packet["ph"] = round(packet["ph"] + r.choice([0.5, 0.9, -1.2]), 2)
            elif fault == "drift_ph": packet["ph"] = round(packet["ph"] + 0.02 * minutes, 2)
            elif fault == "drift_ec": packet["ec_ms_cm"] = round(packet["ec_ms_cm"] + 0.012 * minutes, 2)
            elif fault.startswith("noisy_"):
                f = {"ph": "ph", "air": "air_temperature_c", "hum": "humidity_pct", "moist": "soil_moisture_pct",
                     "subt": "substrate_temperature_c"}[fault[6:]]
                packet[f] = round(packet[f] + (1 if k % 2 else -1) * r.choice([0.6, 1.0, 1.4]) * {
                    "ph": 0.9, "air_temperature_c": 5.0, "humidity_pct": 14.0, "soil_moisture_pct": 3.5, "substrate_temperature_c": 1.2}[f],
                    FIELD_DIGITS[f])
            elif fault == "ramp_air": packet["air_temperature_c"] = round(packet["air_temperature_c"] + 0.4 * (k - f0), 1)
            elif fault == "rewet":
                packet["soil_moisture_pct"] = 6.0 + (k % 3) * 0.1 if k < (f0 + f1) // 2 else 55.0
            elif fault == "oor" and r.random() < 0.3:
                f = r.choice(["ph", "ec_ms_cm", "humidity_pct", "air_temperature_c", "substrate_temperature_c"])
                packet[f] = {"ph": r.choice([14.9, 2.0, 0.0]), "ec_ms_cm": r.choice([-1.0, 13.0, 25.0]), "humidity_pct": r.choice([104.2, -3.0]),
                             "air_temperature_c": r.choice([-127.0, 85.0]), "substrate_temperature_c": r.choice([-127.0, 85.0])}[f]
            elif fault == "missing" and r.random() < 0.3:
                f = r.choice(fields)
                packet[f] = r.choice([None, "", "err", "NaN", True, " 7.1 "])
            elif fault == "veto_ph":
                packet["ph"] = r.choice([14.9, "err", None]) if r.random() < 0.6 else packet["ph"]
            elif fault == "all":
                for f in fields:
                    if r.random() < 0.1:
                        packet[f] = round(packet[f] * r.choice([0.5, 1.5, 0.0]), 2)
        packets.append(packet)
    # Spell some numbers as text, as a CSV would; keep the rest numbers.
    if r.random() < 0.5:
        for packet in packets:
            for f in fields:
                if isinstance(packet.get(f), float) and r.random() < 0.9:
                    packet[f] = f"{packet[f]:.{FIELD_DIGITS[f]}f}"
    return packets


CADENCES = [30, 30, 60, 300, 300, 300, 900, 3600]


def pick_length(cadence, fault, r):
    if fault == "stuck_subt":
        return r.randrange(110, 150) if cadence == 300 else r.randrange(40, 70)
    if cadence == 30:
        return r.randrange(250, 420)
    if cadence == 60:
        return r.randrange(120, 260)
    if cadence == 300:
        return r.randrange(70, 190)
    return r.randrange(40, 90)


# ---- baseline ----------------------------------------------------------------------------------------------------------
BASELINE_NUMERIC = list(tb.BASELINE_FIELDS)


def prior_from(packets, r, veto_rate):
    """Stored readings as Core hands them to stream_baseline: floats only, plus the fields the pipeline vetoed."""
    prior = []
    for packet in packets:
        entry = {"timestamp": packet["timestamp"]}
        for f in BASELINE_NUMERIC:
            value = packet.get(f)
            if isinstance(value, str):
                value = sq.numeric(value)
            if value is not None or f in packet:
                entry[f] = value
        if r.random() < veto_rate:
            entry["vetoed_fields"] = r.sample(BASELINE_NUMERIC + ["previous_ph", "timestamp"], r.randrange(0, 4))
        prior.append(entry)
    return prior


baseline_cases = []
for n in range(420):
    r = random.Random(1000 + n)
    cadence = r.choice(CADENCES)
    fault = r.choice(FAULTS)
    length = r.randrange(3, 60) if r.random() < 0.3 else pick_length(cadence, fault, r)
    packets = make_stream(fault, length, cadence, r, style=r.randrange(3))
    prior = prior_from(packets, r, r.choice([0.0, 0.05, 0.3]))
    if r.random() < 0.15 and prior:  # unreadable / odd values and times
        for _ in range(r.randrange(1, 4)):
            entry = r.choice(prior)
            entry[r.choice(["timestamp", "ph", "air_temperature_c", "soil_moisture_pct"])] = r.choice(
                [None, "bad", "6.5", True, 7, 0, -0.0, 0.0, "2026-03-01T06:00:00", "2026-03-01", 12, float(r.randrange(5, 8))])
    if r.random() < 0.1:  # ties and signed zeros
        for entry in prior:
            for f in ("ph", "ec_ms_cm"):
                if entry.get(f) is not None and r.random() < 0.5:
                    entry[f] = r.choice([0.0, -0.0, 1.0, 0.0078125 * r.randrange(0, 4)])
    if r.random() < 0.1:  # dyadic values: spread and shares land exactly half-way when rounded
        for entry in prior:
            for f in BASELINE_NUMERIC:
                if entry.get(f) is not None:
                    entry[f] = r.randrange(0, 64) / 128
    last = from_us(us(T0) + 1_000_000 * cadence * length)
    now = r.choice([last, last, last + timedelta(hours=r.choice([1, 3, 30])), T0 + timedelta(seconds=cadence * r.randrange(0, length + 1)), None])
    calibrations = []
    for _ in range(r.choice([0, 0, 0, 1, 2])):
        calibrations.append({"measurement": r.choice(["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct", "soil_moisture_pct", "other"]),
                             "performed_at": iso(T0 + timedelta(seconds=cadence * r.randrange(0, length + 1)), r.randrange(3))})
    params = {"window_s": r.choice([tb.DEFAULT_WINDOW_S, tb.DEFAULT_WINDOW_S, 600, 1800, 7200.5, 0]),
              "min_n": r.choice([tb.DEFAULT_MIN_N, tb.DEFAULT_MIN_N, 1, 2, 3, 30]),
              "max_age_s": r.choice([None, None, None, 0, 600, 7200, 86400])}
    now_text = None if now is None else iso(now, r.randrange(3))
    out = tb.stream_baseline(prior, calibrations, now_text, **params)
    baseline_cases.append({"prior": prior, "calibrations": calibrations, "now": now_text, **params, "out": out})

# Times far from the epoch (outside the range JS keeps as plain Numbers) and streams that cross it.
for n in range(24):
    r = random.Random(3000 + n)
    cadence = r.choice([30, 300, 3600])
    length = r.randrange(10, 80)
    first = r.choice([datetime(1, 1, 2, tzinfo=timezone.utc), datetime(9999, 12, 31, tzinfo=timezone.utc) - timedelta(seconds=cadence * length + 5),
                      datetime(2300, 1, 1, tzinfo=timezone.utc), datetime(1800, 6, 1, tzinfo=timezone.utc)])
    packets = make_stream(r.choice(["normal", "stuck_ph", "drift_ph", "step_hum"]), length, cadence, r, start=first, style=r.randrange(2))
    prior = prior_from(packets, r, 0.1)
    if n % 3 == 0:  # a stream that crosses from the far past to now
        modern = prior_from(make_stream("normal", length, cadence, r, start=T0), r, 0.0)
        prior = prior + modern
    last = sq.parse_timestamp(prior[-1]["timestamp"])
    now_text = iso(last, 0)
    out = tb.stream_baseline(prior, [], now_text)
    baseline_cases.append({"prior": prior, "calibrations": [], "now": now_text, "window_s": tb.DEFAULT_WINDOW_S, "min_n": tb.DEFAULT_MIN_N,
                           "max_age_s": None, "out": out})

# ---- checks --------------------------------------------------------------------------------------------------------------
CHECK_KINDS = {
    "drift": re.compile(r"^verify \w+ with a meter: "),
    "stuck_persistent": re.compile(r"^inspect \w+: the same value for \d+ minutes"),
    "stuck_adaptive": re.compile(r"^inspect \w+: the same value for \d+ minutes, though this probe normally changes"),
    "step": re.compile(r"^compare \w+ with .*: it moved"),
    "noise": re.compile(r"^inspect \w+: readings jump between samples; check probe shielding, wiring and averaging"),
}
checks_cases = []


def add_check_case(sensor, history, baseline, pre=None):
    pre = pre or ([], [], [])
    labels, suspect, checks = list(pre[0]), list(pre[1]), list(pre[2])
    sq.apply_persistent_checks(sensor, history, baseline, labels, suspect, checks)
    checks_cases.append({"sensor": sensor, "history": history, "baseline": baseline, "pre": [pre[0], pre[1], pre[2]],
                         "out": {"labels": labels, "suspect": suspect, "checks": checks}})


# (a) References built by stream_baseline from streams with every fault, judged at the next reading.
for n in range(900):
    r = random.Random(5000 + n)
    cadence = r.choice(CADENCES)
    fault = r.choice(FAULTS)
    length = pick_length(cadence, fault, r)
    packets = make_stream(fault, length + 1, cadence, r, style=r.randrange(3))
    prior = prior_from(packets[:-1], r, r.choice([0.0, 0.0, 0.2]))
    sensor = packets[-1]
    history = packets[max(0, length - 11):length]
    if r.random() < 0.05:
        history.insert(0, None)
    stamp = sq.parse_timestamp(sensor["timestamp"])
    baseline = tb.stream_baseline(prior, [], stamp)
    add_check_case(sensor, history, baseline, r.choice([None, None, (["stuck_value"], ["ph"], ["x"])]))

# (b) Hand-written references at the edge of each check.
STAMP = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)


def stats(**kw):
    base = {"median": 6.2, "n": 100, "window_s": 7200, "spread": 0.05, "last_change_at": iso(STAMP - timedelta(minutes=3)),
            "last_value": 6.2, "last_at": iso(STAMP - timedelta(seconds=30))}
    base.update(kw)
    return base


for n in range(1500):
    r = random.Random(9000 + n)
    kind = r.choice(["drift", "drift", "stuck", "adaptive", "step", "step", "noise_ref", "odd"])
    field = r.choice(list(FIELD_BASE) + ["substrate_moisture_pct", "water_temperature_c"])
    cadence = r.choice([30, 60, 300, 900])
    sensor = {"timestamp": iso(STAMP, r.randrange(3))}
    if kind == "drift":
        field = r.choice(["ph", "ec_ms_cm", "ph", "air_temperature_c"])
        thr = {"ph": 0.35, "ec_ms_cm": 0.4}.get(field, 0.35)
        median = r.choice([6.5, 6.2, 1.8, 7.0, 0.0, 12.0, 3.0, r.uniform(3, 11)])
        spread = r.choice([0.0, 0.05, 0.1, 0.12, 0.2, 1.0 / 3.0, 0.0078125, 0.3, 0.5, None, -0.1, 0.1 + 0.2])
        lag = r.choice([None, None, 0.02, 0.0, 0.2, -0.01, 0.3])
        edge = max(thr, 3.0 * (spread or 0.0))
        for_lag = max(thr, 3.0 * lag) if lag is not None and lag >= 0 else edge
        target = r.choice([edge, for_lag, thr, 0.0, edge * 0.999999, edge * 1.000001, 0.99 * edge, 2 * edge])
        sensor[field] = median + r.choice([-1, 1]) * target
        if r.random() < 0.15:
            sensor[field] = r.choice([14.9, 2.99, 3.0, 11.0, 11.0001, 12.0, 12.01, -0.1, "6.9", None, True, "x", float(median)])
        st = stats(median=median, spread=spread, change_share=r.choice([0.5, 0.7, 0.69999, 1.0, 0.0]), change_steps=r.choice([14, 15, 200]),
                   longest_run_s=r.choice([0.0, 60.0, 3600.0]))
        if lag is not None:
            st["spread_lag"] = lag
        if r.random() < 0.1:
            st[r.choice(["median", "spread", "spread_lag", "change_share"])] = r.choice([None, "bad", "0.1", True, -1, 1e300])
        baseline = {field: st}
    elif kind in ("stuck", "adaptive"):
        field = r.choice(["air_temperature_c", "humidity_pct", "substrate_temperature_c", "water_temperature_c", "ph", "ec_ms_cm", "soil_moisture_pct"])
        value = round(r.uniform(1, 30), 2)
        sensor[field] = r.choice([value, str(value)])
        previous_value = r.choice([value, value, value + 1e-10, value + 1e-8, value + 0.1, None])
        limits = {"air_temperature_c": 45 * 60, "humidity_pct": 30 * 60, "substrate_temperature_c": 6 * 3600, "water_temperature_c": 3 * 3600}
        if kind == "adaptive" or field in ("ph", "ec_ms_cm"):
            share = r.choice([0.7, 0.69999, 0.695, 0.9, 1.0, 0.3, 0.03125, 0.0])
            longest = r.choice([0.0, 30.0, 74.999999, 75.0, 75.000001, 300.0, 1234.5678915, 3600.0, 1.0000005])
            limit_s = max(300.0, 4.0 * longest)
            st = stats(change_share=share, change_steps=r.choice([14, 15, 16, 200]), longest_run_s=longest)
        else:
            limit_s = limits.get(field, 600)
            st = stats()
        held = r.choice([limit_s - 1e-6, limit_s, limit_s + 1e-6, limit_s + 1, limit_s * 0.5, limit_s * 2, 59.0, 30.0, 0.0, -5.0])
        st["last_change_at"] = iso(STAMP - timedelta(seconds=held), r.randrange(3))
        if r.random() < 0.08:
            st["last_change_at"] = r.choice([None, "bad", "2026-03-01T06:00:00", 5])
        if r.random() < 0.08:
            st["longest_run_s"] = r.choice([None, -1.0, "x", True])
        baseline = {field: st}
        history = [{"timestamp": iso(STAMP - timedelta(seconds=cadence * (k + 1))), field: previous_value} for k in range(r.choice([1, 1, 2, 3, 5]))][::-1]
        if r.random() < 0.3 and len(history) > 1:  # an older reading that differs: the run is shorter than the history
            history[0][field] = value + 1
        if r.random() < 0.1:
            history = [None, {"x": 1}]
        add_check_case(sensor, history, baseline)
        continue
    elif kind == "step":
        field = r.choice(list(tb.BASELINE_FIELDS))
        lim = sq.STEP_LIMITS.get(field)
        smallest, speed = (lim[0], lim[1]) if lim else (3.0, 1.0)
        minutes = r.choice([0.0, 0.5, 1.0, 5.0, 10.0, 30.0, 2.0, 0.25, 1.7, 4.0 / 3.0, 100.0, -3.0])
        allowed = max(smallest, speed * max(minutes, 0.0))
        last_value = r.choice([0.0, 5.0, 14.9, 15.0, 15.1, 40.0, 60.0, 20.5, 0.05, round(r.uniform(0, 80), 2), -0.0])
        delta = r.choice([allowed, allowed + 1e-9, allowed - 1e-9, allowed * 1.5, -allowed, -allowed * 1.1, 40.0, -40.0, 0.25, 0.75, 1.25, 0.05, 0.0])
        sensor[field] = last_value + delta
        if r.random() < 0.1:
            sensor[field] = str(round(sensor[field], 2))
        st = stats(last_value=last_value, last_at=iso(STAMP - timedelta(minutes=minutes), r.randrange(3)))
        if r.random() < 0.08:
            st[r.choice(["last_value", "last_at"])] = r.choice([None, "bad", "2026-03-01T06:00:00", True])
        baseline = {field: st}
        if r.random() < 0.3:  # steps and noise side by side
            baseline["other"] = {"median": 1.0}
    elif kind == "noise_ref":
        field = r.choice(list(sq.NOISE_STEP_LIMIT_5MIN))
        length = r.randrange(3, 14)
        limit5 = sq.NOISE_STEP_LIMIT_5MIN[field]
        floor = sq.NOISE_STEP_FLOOR[field]
        limit = max(floor, limit5 * math.sqrt(cadence / 300.0))
        mode = r.choice(["noise", "noise", "ramp", "flat", "edge", "mixed"])
        values, level = [], FIELD_BASE.get(field, 40.0)
        for k in range(length):
            if mode == "noise":
                step = r.choice([0.8, 1.0, 1.2, 0.5, 2.0]) * limit * (1 if k % 2 else -1)
            elif mode == "ramp":
                step = r.choice([0.9, 1.1, 1.5]) * limit
            elif mode == "flat":
                step = r.choice([0.0, 0.01, 0.1]) * limit
            elif mode == "edge":
                step = limit * (1 if k % 2 else -1) * r.choice([1.0, 0.999999, 1.000001])
            else:
                step = r.choice([-1, 1]) * r.choice([0.2, 1.0, 1.3]) * limit
            level = level + step
            values.append(round(level, r.choice([1, 2, 3, 6])))
        stamps = [STAMP - timedelta(seconds=cadence * (length - 1 - k)) for k in range(length)]
        if r.random() < 0.15:  # duplicate / missing / reversed times
            idx = r.randrange(length)
            stamps[idx] = r.choice([stamps[max(0, idx - 1)], stamps[min(length - 1, idx + 1)]])
        series = [{"timestamp": iso(t), field: v} for t, v in zip(stamps, values)]
        if r.random() < 0.1:
            series[r.randrange(length)]["timestamp"] = r.choice([None, "bad", "2026-03-01T06:00:00"])
        if r.random() < 0.1:
            series[r.randrange(length)][field] = r.choice([None, "err", True, "5.5"])
        sensor, history = series[-1], series[:-1]
        sensor[field] = sensor.get(field)
        add_check_case(sensor, history, {field: stats(median=values[-1], spread=100.0)})
        continue
    else:  # odd shapes
        baseline = r.choice([None, [], "x", 5, {}, {"ph": None}, {"ph": []}, {"ph": "x"}, {"ph": {}}, {"ph": {"median": None}},
                             {"nothing": {"median": 1}}, {"ph": stats(), "ec_ms_cm": stats(median=1.8)}])
        sensor["ph"] = r.choice([6.2, 9.0, None, "x"])
        sensor["ec_ms_cm"] = 1.8
    history = [{"timestamp": iso(STAMP - timedelta(seconds=cadence)), field: sensor.get(field)}] if r.random() < 0.7 else []
    add_check_case(sensor, history, baseline)

# ---- derive ---------------------------------------------------------------------------------------------------------------
derive_cases = []


def add_derive(farm, sensor, expected, now, history, baseline):
    out = sq.derive_sensor_quality(farm, sensor, expected, now=now, history=history, stream_baseline=baseline)
    derive_cases.append({"farm": farm, "sensor": sensor, "expected": expected, "now_us": None if now is None else str(us(now)),
                         "history": history, "baseline": baseline, "out": out})


for n in range(700):
    r = random.Random(13000 + n)
    cadence = r.choice(CADENCES)
    fault = r.choice(FAULTS)
    length = pick_length(cadence, fault, r)
    packets = make_stream(fault, length + 1, cadence, r, style=r.randrange(3))
    prior = prior_from(packets[:-1], r, 0.1)
    sensor, history = packets[-1], packets[max(0, length - 11):length]
    stamp = sq.parse_timestamp(sensor["timestamp"])
    baseline = tb.stream_baseline(prior, [], stamp)
    expected = r.choice([["ph", "ec_ms_cm"], list(FIELD_BASE), ["ph", "air_temperature_c", "humidity_pct"], ["ph", "foo"], [], ["soil_moisture_pct"]])
    farm = r.choice([FARM, FARM, FARM, {"crop": "", "system_type": "x"}, {}, [], None])
    sensor_in = r.choice([sensor, sensor, sensor, [], None, {}])
    history_in = r.choice([history, history, history, None, [], "x", [1], [None]])
    expected_in = r.choice([expected, expected, expected, "ph", [1], None])
    now = r.choice([stamp, stamp + timedelta(hours=2), None])
    add_derive(farm, sensor_in, expected_in, now, history_in, r.choice([baseline, baseline, baseline, {}, None, "x"]))

# ---- streams ---------------------------------------------------------------------------------------------------------------
HISTORY = 11
streams = []


def check_stream(packets, ctx, expected, now, scan_limit):
    """The checker's per-reading flow, run on the Python functions (checker.js: checkLog/evaluatePacket)."""
    stored = []
    results = []
    for i, packet in enumerate(packets):
        history = packets[max(0, i - HISTORY):i]
        sampled = sq.parse_timestamp(packet.get("timestamp"))
        latest = i == len(packets) - 1
        reference = None
        if sampled is not None:
            prior = sorted((e for e in stored[-scan_limit:] if e["timestamp"] < sampled), key=lambda e: e["timestamp"])
            reference = tb.stream_baseline(prior, [], sampled)
        out = sq.derive_sensor_quality(ctx, packet, expected, now=now if latest else sampled, history=history, stream_baseline=reference)
        if not latest and sampled is not None and now is not None and (sampled - now).total_seconds() > 60:
            if "insufficient_context" not in out["data_quality_labels"]:
                out["data_quality_labels"].append("insufficient_context")
            if "timestamp" not in out["suspect_fields"]:
                out["suspect_fields"].append("timestamp")
            out["safe_next_checks"] = [c for c in out["safe_next_checks"] if c != ROUTINE]
            out["safe_next_checks"].append(FUTURE_CHECK)
            out["human_review_required"] = True
            out["rationale"] = "Sensor packet needs verification before downstream risk or action reasoning."
        results.append(out)
        if sampled is not None:
            gate = tg.apply_sensor_veto(packet, history, out, expected)[2]
            entry = {"timestamp": sampled, "vetoed_fields": gate["vetoed_fields"]}
            for f in tb.BASELINE_FIELDS:
                entry[f] = sq.numeric(packet.get(f))
            stored.append(entry)
    return results


def add_stream(packets, scan_limit=tb.DEFAULT_SCAN_LIMIT, expected=None, now=None, note=""):
    expected = expected if expected is not None else sorted({f for p in packets for f in p if f in FIELD_BASE})
    if now is None:
        last = sq.parse_timestamp(packets[-1].get("timestamp")) or T0
        now = last + timedelta(seconds=rng.choice([0, 30, 600]))
    out = check_stream(packets, FARM, expected, now, scan_limit)
    streams.append({"packets": packets, "ctx": FARM, "expected": expected, "now_us": str(us(now)), "scan_limit": scan_limit, "note": note,
                    "out": out})


for n in range(5 * len(FAULTS)):
    r = random.Random(17000 + n)
    cadence = [30, 300, 60, 300, 900, 3600, 30, 300][(n + n // 5) % 8]
    fault = FAULTS[n // 5]
    length = pick_length(cadence, fault, r)
    if cadence == 30:
        length = min(length, 300)
    packets = make_stream(fault, length, cadence, r, style=r.randrange(3))
    if n % 5 == 0:  # fewer fields: a device that reports only some probes
        keep = r.sample(list(FIELD_BASE), r.randrange(1, 5))
        packets = [{k: v for k, v in p.items() if k == "timestamp" or k in keep} for p in packets]
    add_stream(packets, note=f"{fault}@{cadence}s")

# Long freezes at the fast cadence (45 and 30 minutes are 90 and 60 readings at 30 s).
for n, (fault, cadence, length, span) in enumerate([("stuck_air", 30, 260, (60, 260)), ("stuck_hum", 30, 200, (40, 200)),
                                                    ("stuck_air", 30, 260, (60, 150)), ("stuck_hum", 60, 140, (30, 140)),
                                                    ("stuck_air", 60, 120, (20, 120)), ("stuck_hum", 30, 200, (40, 90))]):
    r = random.Random(18000 + n)
    add_stream(make_stream(fault, length, cadence, r, style=n % 3, span=span), note=f"{fault}@{cadence}s")

# Timestamps: duplicates, going backwards, unreadable, naive, future, long gaps.
for n in range(20):
    r = random.Random(19000 + n)
    cadence = r.choice([30, 300])
    fault = r.choice(["normal", "stuck_ph", "step_hum", "drift_ph", "noisy_ph", "stuck_air"])
    packets = make_stream(fault, r.randrange(60, 160), cadence, r, style=r.randrange(3))
    for _ in range(r.randrange(2, 8)):
        i = r.randrange(1, len(packets))
        how = r.choice(["dup", "back", "bad", "naive", "none", "future", "gap", "swap"])
        if how == "dup":
            packets[i]["timestamp"] = packets[i - 1]["timestamp"]
        elif how == "back":
            packets[i]["timestamp"] = iso(T0 - timedelta(hours=1, seconds=i))
        elif how == "bad":
            packets[i]["timestamp"] = r.choice(["", "bad", "2026-13-01T00:00:00Z"])
        elif how == "naive":
            packets[i]["timestamp"] = "2026-03-01T06:00:00"
        elif how == "none":
            packets[i].pop("timestamp")
        elif how == "future":
            packets[i]["timestamp"] = iso(T0 + timedelta(days=2, seconds=i))
        elif how == "gap":
            for p in packets[i:]:
                t = sq.parse_timestamp(p.get("timestamp"))
                if t is not None:
                    p["timestamp"] = iso(t + timedelta(hours=r.choice([1, 5, 30])))
        else:
            j = r.randrange(len(packets))
            packets[i], packets[j] = packets[j], packets[i]
    add_stream(packets, note="timestamp trouble")

# The scan limit: only the newest readings (by arrival) feed the reference.
for n in range(8):
    r = random.Random(21000 + n)
    fault = r.choice(["normal", "drift_ph", "stuck_ph", "step_air", "stuck_hum"])
    packets = make_stream(fault, r.randrange(60, 120), r.choice([30, 300]), r, style=r.randrange(3))
    add_stream(packets, scan_limit=r.choice([10, 25, 40]), note="scan limit")

# Edge-of-range streams: out-of-range readings that were trusted before, ties, signed zeros, dyadic values.
for n in range(10):
    r = random.Random(23000 + n)
    packets = make_stream(r.choice(["normal", "oor", "missing", "all"]), r.randrange(40, 90), r.choice([30, 300]), r, style=0)
    for p in packets:
        for f in ("ph", "ec_ms_cm", "humidity_pct"):
            if f in p and isinstance(p[f], (int, float)) and r.random() < 0.4:
                p[f] = r.choice([0.0, -0.0, 0.0078125 * r.randrange(0, 5), 7.0, 7, p[f]])
    add_stream(packets, note="edge values")

# ---- coverage ----------------------------------------------------------------------------------------------------------------
def kind_of(check):
    if CHECK_KINDS["stuck_adaptive"].match(check):
        return "stuck_adaptive"
    for name, pattern in CHECK_KINDS.items():
        if name != "stuck_adaptive" and pattern.match(check):
            return name
    return None


fired = {k: 0 for k in CHECK_KINDS}
quiet = {k: 0 for k in CHECK_KINDS}
for case in checks_cases:
    seen = {kind_of(c) for c in case["out"]["checks"]}
    for k in CHECK_KINDS:
        (fired if k in seen else quiet)[k] += 1
stream_fired = {k: 0 for k in CHECK_KINDS}
labelled = {}
for case in streams:
    for out in case["out"]:
        for k in {kind_of(c) for c in out["safe_next_checks"]}:
            if k:
                stream_fired[k] += 1
        for label in out["data_quality_labels"]:
            labelled[label] = labelled.get(label, 0) + 1
by_cadence = {}
for case in streams:
    m = re.search(r"@(\d+)s$", case["note"])
    if m:
        for out in case["out"]:
            for k in {kind_of(c) for c in out["safe_next_checks"]} - {None}:
                by_cadence.setdefault(int(m.group(1)), {}).setdefault(k, 0)
                by_cadence[int(m.group(1))][k] += 1
for k in CHECK_KINDS:
    assert by_cadence.get(30, {}).get(k, 0) > 0 and by_cadence.get(300, {}).get(k, 0) > 0, ("cadence coverage", k, by_cadence)
for k in CHECK_KINDS:
    assert fired[k] >= 20 and quiet[k] >= 20, (k, fired[k], quiet[k])
    assert stream_fired[k] >= 5, (k, stream_fired[k])
baseline_stats = sum(len(c["out"]) for c in baseline_cases)
assert baseline_stats > 400 and any("spread_lag" in s for c in baseline_cases for s in c["out"].values())
assert any("change_share" in s for c in baseline_cases for s in c["out"].values())

out = {"python": sys.version.split()[0], "format": format_cases, "baseline": baseline_cases, "checks": checks_cases,
       "derive": derive_cases, "streams": streams}
path = Path(__file__).with_name("persistent_cases.json")
path.write_text(json.dumps(out))
packets_total = sum(len(s["packets"]) for s in streams)
print(f"python {out['python']}: format={len(format_cases)} baseline={len(baseline_cases)} checks={len(checks_cases)} "
      f"derive={len(derive_cases)} streams={len(streams)} ({packets_total} readings)")
print("  checks fired/quiet in direct cases:", {k: f"{fired[k]}/{quiet[k]}" for k in CHECK_KINDS})
print("  checks fired across streams:", stream_fired)
print("  ... by cadence (readings carrying the check):", {c: by_cadence[c] for c in sorted(by_cadence)})
