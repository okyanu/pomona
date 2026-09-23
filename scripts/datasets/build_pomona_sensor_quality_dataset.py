#!/usr/bin/env python3
"""Build a local generated dataset for Pomona Sensor Quality Reasoner v0.1."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-sensor-quality-v0.1")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-sensor-quality-v0.1")

# Staleness gate in services/model-router/app/sensor_quality.py: age_seconds > 60 * 60.
STALE_THRESHOLD_SECONDS = 60 * 60


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def random_current_time(rng: random.Random) -> datetime:
    # Wide, varied date/time-of-day range so no single calendar date is a
    # shortcut for any label -- the model must learn the current_time minus
    # timestamp gap, not memorize a date string.
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return start + timedelta(days=rng.uniform(0, 330), seconds=rng.uniform(0, 86400))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def base_input(rng: random.Random) -> dict[str, Any]:
    system_type = rng.choice(["controlled_greenhouse", "greenhouse_substrate", "hydroponic", "soil_field"])
    expected_fields = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
    if system_type in {"greenhouse_substrate", "soil_field"}:
        expected_fields.append("substrate_moisture_pct")
    current_time = random_current_time(rng)
    fresh_timestamp = current_time - timedelta(seconds=rng.uniform(0, STALE_THRESHOLD_SECONDS * 0.75))
    return {
        "farm_context": {
            "crop": rng.choice(["tomato", "strawberry", "lettuce", "cucumber"]),
            "system_type": system_type,
            "zone_id": rng.choice(["greenhouse-a", "bay-2", "rack-1", "zone-3"]),
        },
        "sensor": {
            "air_temperature_c": round(rng.uniform(18.0, 29.0), 1),
            "humidity_pct": round(rng.uniform(45.0, 82.0), 1),
            "ph": round(rng.uniform(5.0, 7.5), 2),  # widened from 5.6-6.8: that narrow band left the model
            # brittle near its own edges (clean-holdout pH 5.55/6.59 -- inside 5.6-6.8 but near the boundary --
            # got misclassified as impossible_ph). Still well clear of the impossible_ph values (2.9, 12.8, 14.0).
            "ec_ms_cm": round(rng.uniform(1.0, 3.2), 2),
            "substrate_moisture_pct": round(rng.uniform(30.0, 65.0), 1),
            "timestamp": iso(fresh_timestamp),
        },
        "expected_fields": expected_fields,
        "current_time": iso(current_time),
    }


def make_record(
    record_id: str,
    input_data: dict[str, Any],
    labels: list[str],
    missing_fields: list[str],
    suspect_fields: list[str],
    checks: list[str],
    rationale: str,
    missing_value_form: str | None = None,
) -> dict[str, Any]:
    notes = "Generated sensor-quality training case from Pomona rule templates."
    if missing_value_form == "omitted":
        notes += " Missing field is truly omitted from the sensor object (no key)."
    elif missing_value_form == "null":
        notes += " Missing field is present with an explicit null value."
    return {
        "id": record_id,
        "source_id": "pomona_generated_sensor_quality_v0_1",
        "input": input_data,
        "expected_output": {
            "data_quality_labels": labels,
            "missing_fields": missing_fields,
            "suspect_fields": suspect_fields,
            "safe_next_checks": checks,
            "human_review_required": bool(labels or missing_fields or suspect_fields),
            "rationale": rationale,
        },
        "notes": notes,
    }


# Deployed boundary (services/model-router/app/sensor_quality.py):
# impossible_ph is `ph < 3.0 or ph > 11.0` -- 3.0 and 11.0 themselves are normal.
# Historically impossible_ph training only used three far-extreme constants
# (2.9, 12.8, 14.0), so the model never saw a graded boundary and both trained
# adapters ended up flagging plausible normal pH (e.g. 4.0, 9.0, 10.0) as
# impossible -- see private/SENSOR_QUALITY_PH_SWEEP_2026_09_07.md. These pools
# add near-boundary points on both sides of 3.0/11.0, not just far extremes.
IMPOSSIBLE_PH_POOL = [
    -10.0, -5.0, -1.0, 0.0, 1.0, 1.5, 2.0, 2.5, 2.8, 2.9, 2.95, 2.99,
    11.01, 11.05, 11.1, 11.3, 11.5, 12.0, 12.8, 14.0, 16.0, 20.0,
]
NEAR_BOUNDARY_NORMAL_PH_POOL = [
    3.0, 3.05, 3.1, 3.2, 3.5, 4.0, 4.5,
    9.0, 9.5, 10.0, 10.5, 10.8, 10.95, 11.0,
]
NEAR_BOUNDARY_NORMAL_PH_PROBABILITY = 0.4


def apply_missing_field(sensor: dict[str, Any], field: str, rng: random.Random) -> str:
    """Mark `field` missing, alternating between an explicit null value and a
    truly omitted key so training data demonstrates both forms the system
    prompt and the deployed rules fallback treat as equivalent ("null/missing").
    Historically only the null form was generated -- see
    docs/SENSOR_QUALITY_INPUT_CONTRACT.md and
    scripts/datasets/check_sensor_quality_omission_coverage.py.
    Returns the form used, for `make_record`'s notes.
    """
    if rng.random() < 0.5:
        sensor[field] = None
        return "null"
    del sensor[field]
    return "omitted"


def generated_records(seed: int, count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        item = base_input(rng)
        sensor = item["sensor"]
        scenario = index % 15

        if scenario == 0:
            if rng.random() < NEAR_BOUNDARY_NORMAL_PH_PROBABILITY:
                sensor["ph"] = rng.choice(NEAR_BOUNDARY_NORMAL_PH_POOL)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, [], [], [], ["continue routine monitoring"], "Critical sensor readings are present and inside plausible ranges."))
        elif scenario == 1:
            form = apply_missing_field(sensor, "ph", rng)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_ph"], ["ph"], [], ["restore or manually measure pH before risk or fertigation reasoning"], "pH is a required critical field and is missing.", missing_value_form=form))
        elif scenario == 2:
            form = apply_missing_field(sensor, "ec_ms_cm", rng)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_ec"], ["ec_ms_cm"], [], ["restore or manually verify EC before nutrient reasoning"], "EC is a required critical field and is missing.", missing_value_form=form))
        elif scenario == 3:
            form = apply_missing_field(sensor, "air_temperature_c", rng)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_temperature"], ["air_temperature_c"], [], ["restore or manually verify air temperature before stress reasoning"], "Air temperature is required and missing.", missing_value_form=form))
        elif scenario == 4:
            form = apply_missing_field(sensor, "humidity_pct", rng)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_humidity"], ["humidity_pct"], [], ["restore or manually verify humidity before disease-pressure reasoning"], "Humidity is required and missing.", missing_value_form=form))
        elif scenario == 5:
            if "substrate_moisture_pct" not in item["expected_fields"]:
                item["expected_fields"].append("substrate_moisture_pct")
            form = apply_missing_field(sensor, "substrate_moisture_pct", rng)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_moisture"], ["substrate_moisture_pct"], [], ["restore or manually verify substrate moisture before irrigation reasoning"], "Substrate moisture is expected for this system and is missing.", missing_value_form=form))
        elif scenario == 6:
            sensor["ph"] = rng.choice(IMPOSSIBLE_PH_POOL)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["impossible_ph"], [], ["ph"], ["inspect pH probe calibration and units before using this reading"], "pH is outside plausible agricultural sensor range."))
        elif scenario == 7:
            sensor["ec_ms_cm"] = rng.choice([-0.2, -1.0, 15.5])
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["impossible_ec"], [], ["ec_ms_cm"], ["inspect EC sensor units, sample availability, and calibration"], "EC is outside plausible sensor range."))
        elif scenario == 8:
            sensor["humidity_pct"] = rng.choice([-5.0, 125.0, 180.0])
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["impossible_humidity"], [], ["humidity_pct"], ["validate humidity sensor range and compare with a backup reading"], "Humidity percentage is outside the 0 to 100 range."))
        elif scenario == 9:
            sensor["air_temperature_c"] = rng.choice([-18.0, 68.0, 92.0])
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["impossible_temperature"], [], ["air_temperature_c"], ["compare air temperature against a backup sensor and check units"], "Air temperature is outside plausible greenhouse sensor range."))
        elif scenario == 10:
            current_time = datetime.strptime(item["current_time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            stale_timestamp = current_time - timedelta(seconds=rng.uniform(STALE_THRESHOLD_SECONDS * 1.2, STALE_THRESHOLD_SECONDS * 72))
            sensor["timestamp"] = iso(stale_timestamp)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["stale_reading"], [], ["timestamp"], ["confirm the latest telemetry timestamp before using this packet"], "Sensor timestamp is stale relative to current operation."))
        elif scenario == 11:
            sensor["temperature_f"] = sensor["air_temperature_c"]
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["unit_mismatch"], [], ["air_temperature_c", "temperature_f"], ["verify temperature units and sensor mapping before comparing thresholds"], "Celsius and Fahrenheit fields are inconsistent or ambiguously mapped."))
        elif scenario == 12:
            sensor["backup_air_temperature_c"] = round(float(sensor["air_temperature_c"]) + rng.uniform(10.0, 18.0), 1)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["conflicting_readings"], [], ["air_temperature_c", "backup_air_temperature_c"], ["compare primary and backup temperature probes before using the value"], "Primary and backup temperature readings disagree significantly."))
        elif scenario == 13:
            sensor["ph"] = round(rng.uniform(7.05, 7.15), 2)
            sensor["previous_ph"] = round(sensor["ph"] - rng.uniform(0.8, 1.2), 2)
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["sensor_drift_possible"], [], ["ph", "previous_ph"], ["repeat pH measurement and inspect probe drift before threshold reasoning"], "pH changed abruptly compared with the previous reading."))
        else:
            item["expected_fields"] = []
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["insufficient_context"], [], [], ["provide expected fields and farm system context before quality classification"], "Expected sensor fields are not defined for this packet."))
    return records


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("data_quality_labels") or []
    return labels[0] if labels else "normal"


def split_records(records: list[dict[str, Any]], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        buckets[bucket_key(record)].append(record)
    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for bucket in buckets.values():
        rng.shuffle(bucket)
        test_count = round(len(bucket) * 0.1)
        validation_count = round(len(bucket) * 0.1)
        test.extend(bucket[:test_count])
        validation.extend(bucket[test_count : test_count + validation_count])
        train.extend(bucket[test_count + validation_count :])
    rng.shuffle(train)
    rng.shuffle(validation)
    rng.shuffle(test)
    return train, validation, test


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--records", type=int, default=2100)
    parser.add_argument("--seed", type=int, default=44)
    args = parser.parse_args()

    seed_records = read_jsonl(args.dataset_dir / "data" / "samples.jsonl") + read_jsonl(args.dataset_dir / "data" / "eval_cases.jsonl")
    records = seed_records + generated_records(args.seed, args.records)
    train, validation, test = split_records(records, args.seed)

    write_jsonl(args.output_dir / "all_records.jsonl", records)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)

    label_counts: dict[str, int] = defaultdict(int)
    for record in records:
        labels = record["expected_output"]["data_quality_labels"]
        label_counts[labels[0] if labels else "normal"] += 1
    summary = {
        "records": len(records),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "label_counts": dict(sorted(label_counts.items())),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
