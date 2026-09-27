#!/usr/bin/env python3
"""Build the Pomona Sensor Quality Reasoner v0.1.5 training dataset.

v0.1.4 failed its 123-case holdout gate because the training inputs had
shortcuts and gaps, not because of the recipe (see
private/pomona_trained_data/pomona-sensor-quality-v0.1.4-candidate-not-approved-lora-report.json):

- every sensor packet carried a moisture key, so "no moisture key" was learned
  as "missing_moisture";
- every timestamp ended in "Z";
- no non-numeric values, future timestamps, exact range edges or multi-problem
  packets existed at all.

This builder varies packet shape and timestamp spelling, adds those cases, and
labels every record with the deployed deterministic contract
(`services/model-router/app/sensor_quality.derive_sensor_quality`) so targets
cannot drift from the rules. Invalid-value tokens and edge offsets are chosen
to differ from the holdout's own (True/"broken"/"NaN"/"Infinity"/{} and
2.999/11.001, 3601 s, 61 s); the bundle builder still removes any exact
identity/time-stripped overlap.
"""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import random
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[2]
RULES_PATH = REPO_ROOT / "services/model-router/app/sensor_quality.py"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "datasets/processed/pomona-sensor-quality-v0.1.5"

CORE_FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
MOISTURE_FIELDS = ["soil_moisture_pct", "substrate_moisture_pct"]
MOISTURE_SYSTEMS = {"greenhouse_substrate", "soil_field", "soil_pot"}
SYSTEMS = ["controlled_greenhouse", "greenhouse_substrate", "hydroponic", "hydroponic_dwc", "soil_field", "soil_pot"]
CROPS = ["tomato", "strawberry", "lettuce", "cucumber", "watercress", "basil", "pepper"]
ZONES = ["greenhouse-a", "bay-2", "rack-1", "zone-3", "cress-hydro-a", "bed-7", "north-row"]
# Deliberately disjoint from the holdout's invalid tokens.
INVALID_TOKENS = [False, "err", "n/a", "--", "offline", [], "nan", "12,5", "", "ph?"]
NUMERIC_STRINGS = ["6.2", "1.85", "24", "61.0"]  # parse as numbers under the contract
RANGES = {  # (low, high) plausible bounds from the contract; values outside are impossible
    "ph": (3.0, 11.0), "ec_ms_cm": (0.0, 12.0), "air_temperature_c": (-10.0, 65.0), "humidity_pct": (0.0, 100.0),
}
EDGE_OFFSETS = [0.0, 0.002, 0.01, 0.05, 0.3, 1.0, 4.0]


def load_rules():
    spec = importlib.util.spec_from_file_location("pomona_sensor_quality_rules", RULES_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fmt_time(dt: datetime, rng: random.Random) -> str:
    """Spell one instant in any of several valid timezone-aware ISO forms."""
    dt = dt.astimezone(timezone.utc).replace(microsecond=rng.choice([0, 0, rng.randrange(1_000_000)]))
    style = rng.random()
    if style < 0.35:
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + (f".{dt.microsecond:06d}" if dt.microsecond else "") + "Z"
    if style < 0.75:
        return dt.isoformat()  # +00:00
    offset = timedelta(hours=rng.choice([-5, 1, 3, 4, 5.5, 9]))
    return dt.astimezone(timezone(offset)).isoformat()


def base_packet(rng: random.Random) -> tuple[dict[str, Any], datetime]:
    system = rng.choice(SYSTEMS)
    moisture = rng.choice(MOISTURE_FIELDS)
    expected = list(CORE_FIELDS)
    rng.shuffle(expected)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(days=rng.uniform(0, 540), seconds=rng.uniform(0, 86400))
    sensor: dict[str, Any] = {
        "air_temperature_c": round(rng.uniform(12.0, 34.0), rng.choice([1, 2])),
        "humidity_pct": round(rng.uniform(35.0, 92.0), rng.choice([1, 2])),
        "ph": round(rng.uniform(5.0, 7.8), rng.choice([2, 3])),
        "ec_ms_cm": round(rng.uniform(0.3, 3.6), rng.choice([2, 3])),
        "timestamp": now - timedelta(seconds=rng.uniform(0, 3000)),
    }
    if system in MOISTURE_SYSTEMS and rng.random() < 0.7:
        expected.append(moisture)
        sensor[moisture] = round(rng.uniform(20.0, 70.0), 1)
    elif rng.random() < 0.3:
        # Extra, unrequired moisture reading: presence alone must not matter.
        sensor[moisture] = round(rng.uniform(20.0, 70.0), 1)
    if rng.random() < 0.15:
        sensor["water_temperature_c"] = round(rng.uniform(10.0, 26.0), 1)
    item = {
        "farm_context": {"crop": rng.choice(CROPS), "system_type": system, "zone_id": rng.choice(ZONES)},
        "sensor": sensor,
        "expected_fields": expected,
        "current_time": now,
    }
    return item, now


# --- perturbations: each edits the packet in place and returns a short tag ---------------

def _num(value, default):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def p_missing(item, rng):
    field = rng.choice(item["expected_fields"] or CORE_FIELDS)
    if rng.random() < 0.5:
        item["sensor"][field] = None
    else:
        item["sensor"].pop(field, None)
    return f"missing:{field}"


def p_impossible(item, rng):
    field = rng.choice(list(RANGES))
    low, high = RANGES[field]
    offset = rng.choice([0.01, 0.02, 0.1, 0.5, 2.0, 10.0, 50.0])
    item["sensor"][field] = round(low - offset if rng.random() < 0.5 else high + offset, 3)
    return f"impossible:{field}"


def p_edge_normal(item, rng):
    field = rng.choice(list(RANGES))
    low, high = RANGES[field]
    offset = rng.choice(EDGE_OFFSETS)
    value = low + offset if rng.random() < 0.5 else high - offset
    item["sensor"][field] = int(value) if offset == 0.0 and rng.random() < 0.5 else round(value, 3)
    return f"edge_normal:{field}"


def p_invalid(item, rng):
    field = rng.choice(item["expected_fields"] + ["ph", "ec_ms_cm"])
    item["sensor"][field] = copy.deepcopy(rng.choice(INVALID_TOKENS))
    return f"invalid:{field}"


def p_numeric_string(item, rng):
    field = rng.choice(["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct"])
    item["sensor"][field] = rng.choice(NUMERIC_STRINGS)
    return f"numeric_string:{field}"


def p_stale(item, rng):
    age = rng.choice([3600.5, 3602, 3630, 3700, 5400, 7200, 86400, 3 * 86400])
    item["sensor"]["timestamp"] = item["current_time"] - timedelta(seconds=age)
    return "stale"


def p_almost_stale(item, rng):
    item["sensor"]["timestamp"] = item["current_time"] - timedelta(seconds=rng.choice([3599, 3595, 3500, 3300]))
    return "almost_stale"


def p_future(item, rng):
    item["sensor"]["timestamp"] = item["current_time"] + timedelta(seconds=rng.choice([62, 75, 90, 300, 3600, 86400]))
    return "future"


def p_slight_future(item, rng):
    item["sensor"]["timestamp"] = item["current_time"] + timedelta(seconds=rng.choice([1, 10, 30, 58]))
    return "slight_future"


def p_bad_timestamp(item, rng):
    choice = rng.choice(["drop", "none", "garbage", "naive", "date_only"])
    ts = item["sensor"].get("timestamp")
    if not isinstance(ts, datetime):
        ts = item["current_time"] - timedelta(seconds=rng.uniform(0, 3000))
    if choice == "drop":
        item["sensor"].pop("timestamp")
    elif choice == "none":
        item["sensor"]["timestamp"] = None
    elif choice == "garbage":
        item["sensor"]["timestamp"] = rng.choice(["yesterday", "not-a-time", "0"])
    elif choice == "naive":
        item["sensor"]["timestamp"] = ts.replace(tzinfo=None).isoformat()
    else:
        item["sensor"]["timestamp"] = ts.date().isoformat()
    return f"bad_timestamp:{choice}"


def p_unit(item, rng):
    celsius = _num(item["sensor"].get("air_temperature_c"), 24.0)
    item["sensor"].setdefault("air_temperature_c", celsius)
    item["sensor"]["temperature_f"] = round(celsius * 1.8 + 32, 1)
    return "unit_mismatch"


def p_conflict(item, rng):
    base = _num(item["sensor"].get("air_temperature_c"), None)
    if base is None:
        base = item["sensor"]["air_temperature_c"] = 24.0
    delta = rng.choice([7.5, 7.9, 8.1, 9.0, 12.0, 20.0]) * rng.choice([1, -1])
    item["sensor"]["backup_air_temperature_c"] = round(base + delta, 2)
    return "conflict"


def p_drift(item, rng):
    ph = round(rng.uniform(5.5, 7.5), 2)
    item["sensor"]["ph"] = ph
    item["sensor"]["previous_ph"] = round(ph + rng.choice([0.5, 0.75, 0.85, 1.0, 1.5]) * rng.choice([1, -1]), 2)
    return "drift"


def p_context(item, rng):
    choice = rng.choice(["empty_expected", "no_crop", "no_system", "empty_context", "unsupported_field"])
    if choice == "empty_expected":
        item["expected_fields"] = []
    elif choice == "no_crop":
        item["farm_context"].pop("crop")
    elif choice == "no_system":
        item["farm_context"]["system_type"] = ""
    elif choice == "empty_context":
        item["farm_context"] = {}
    else:
        item["expected_fields"].append(rng.choice(["co2_ppm", "light_lux", "dissolved_oxygen_mg_l"]))
    return f"context:{choice}"


PERTURBATIONS: dict[str, Callable] = {
    "missing": p_missing, "impossible": p_impossible, "edge_normal": p_edge_normal, "invalid": p_invalid,
    "numeric_string": p_numeric_string, "stale": p_stale, "almost_stale": p_almost_stale, "future": p_future,
    "slight_future": p_slight_future, "bad_timestamp": p_bad_timestamp, "unit_mismatch": p_unit,
    "conflict": p_conflict, "drift": p_drift, "context": p_context,
}
# Scenario mix: (name, weight). "combo" applies 2-3 distinct perturbations.
SCENARIOS = [("normal", 14), ("missing", 12), ("impossible", 8), ("edge_normal", 8), ("invalid", 8),
             ("numeric_string", 2), ("stale", 5), ("almost_stale", 3), ("future", 5), ("slight_future", 2),
             ("bad_timestamp", 4), ("unit_mismatch", 3), ("conflict", 4), ("drift", 4), ("context", 4), ("combo", 14)]


def finalize(item: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    out = copy.deepcopy(item)
    now = out["current_time"]
    out["current_time"] = fmt_time(now, rng)
    if isinstance(out["sensor"].get("timestamp"), datetime):
        out["sensor"]["timestamp"] = fmt_time(out["sensor"]["timestamp"], rng)
    return out


def label(rules, item: dict[str, Any]) -> dict[str, Any]:
    now = datetime.fromisoformat(item["current_time"].replace("Z", "+00:00"))
    return rules.derive_sensor_quality(item["farm_context"], item["sensor"], item["expected_fields"], now=now)


def generate(seed: int, count: int) -> list[dict[str, Any]]:
    rules = load_rules()
    rng = random.Random(seed)
    names = [name for name, _ in SCENARIOS]
    weights = [weight for _, weight in SCENARIOS]
    records, seen = [], set()
    while len(records) < count:
        item, _ = base_packet(rng)
        scenario = rng.choices(names, weights)[0]
        if scenario == "combo":
            tags = [PERTURBATIONS[name](item, rng) for name in rng.sample(list(PERTURBATIONS), rng.choice([2, 2, 3]))]
        elif scenario == "normal":
            tags = []
        else:
            tags = [PERTURBATIONS[scenario](item, rng)]
        final = finalize(item, rng)
        key = json.dumps(final, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        records.append({
            "id": f"sq015-{len(records) + 1:05d}",
            "source_id": "pomona_generated_sensor_quality_v0_1_5",
            "scenario": scenario,
            "perturbations": tags,
            "input": final,
            "expected_output": label(rules, final),
            "notes": "Generated v0.1.5 case; expected_output produced by the deterministic sensor-quality contract.",
        })
    return records


def split(records: list[dict[str, Any]], seed: int):
    rng = random.Random(seed)
    buckets: dict[str, list] = defaultdict(list)
    for record in records:
        buckets[record["scenario"]].append(record)
    train, validation, test = [], [], []
    for name in sorted(buckets):
        bucket = buckets[name]
        rng.shuffle(bucket)
        n = round(len(bucket) * 0.1)
        test += bucket[:n]
        validation += bucket[n:2 * n]
        train += bucket[2 * n:]
    for part in (train, validation, test):
        rng.shuffle(part)
    return train, validation, test


def coverage(records: list[dict[str, Any]]) -> dict[str, int]:
    def has(pred):
        return sum(1 for r in records if pred(r))
    labels = lambda r: r["expected_output"]["data_quality_labels"]  # noqa: E731
    return {
        "normal": has(lambda r: not labels(r)),
        "normal_without_moisture_key": has(lambda r: not labels(r) and not any(f in r["input"]["sensor"] for f in MOISTURE_FIELDS)),
        "timestamp_not_Z": has(lambda r: not str(r["input"]["current_time"]).endswith("Z")),
        "non_numeric_value": has(lambda r: any(p.startswith("invalid:") for p in r["perturbations"])),
        "future_timestamp": has(lambda r: "future" in r["perturbations"]),
        "exact_edge_value": has(lambda r: any(r["input"]["sensor"].get(f) in b for f, b in RANGES.items()
                                              if not isinstance(r["input"]["sensor"].get(f), (bool, list, dict)))),
        "multi_label": has(lambda r: len(labels(r)) >= 2),
        "omitted_required_key": has(lambda r: any(f not in r["input"]["sensor"] for f in r["input"]["expected_fields"])),
        "explicit_null": has(lambda r: any(v is None for v in r["input"]["sensor"].values())),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--records", type=int, default=2600)
    parser.add_argument("--seed", type=int, default=515)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise SystemExit(f"{args.output_dir} exists; choose a new output directory")

    records = generate(args.seed, args.records)
    train, validation, test = split(records, args.seed)
    args.output_dir.mkdir(parents=True)
    for name, rows in (("all_records", records), ("train", train), ("validation", validation), ("test", test)):
        with (args.output_dir / f"{name}.jsonl").open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
    summary = {
        "records": len(records), "train": len(train), "validation": len(validation), "test": len(test),
        "scenarios": dict(sorted(Counter(r["scenario"] for r in records).items())),
        "first_labels": dict(sorted(Counter((r["expected_output"]["data_quality_labels"] or ["normal"])[0] for r in records).items())),
        "train_coverage": coverage(train),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
