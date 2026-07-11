#!/usr/bin/env python3
"""Build a local generated dataset for Pomona Sensor Quality Reasoner v0.1."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-sensor-quality-v0.1")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-sensor-quality-v0.1")


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
    return {
        "farm_context": {
            "crop": rng.choice(["tomato", "strawberry", "lettuce", "cucumber"]),
            "system_type": system_type,
            "zone_id": rng.choice(["greenhouse-a", "bay-2", "rack-1", "zone-3"]),
        },
        "sensor": {
            "air_temperature_c": round(rng.uniform(18.0, 29.0), 1),
            "humidity_pct": round(rng.uniform(45.0, 82.0), 1),
            "ph": round(rng.uniform(5.6, 6.8), 2),
            "ec_ms_cm": round(rng.uniform(1.0, 3.2), 2),
            "substrate_moisture_pct": round(rng.uniform(30.0, 65.0), 1),
            "timestamp": "2026-07-07T10:00:00Z",
        },
        "expected_fields": expected_fields,
    }


def make_record(
    record_id: str,
    input_data: dict[str, Any],
    labels: list[str],
    missing_fields: list[str],
    suspect_fields: list[str],
    checks: list[str],
    rationale: str,
) -> dict[str, Any]:
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
        "notes": "Generated sensor-quality training case from Pomona rule templates.",
    }


def generated_records(seed: int, count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        item = base_input(rng)
        sensor = item["sensor"]
        scenario = index % 15

        if scenario == 0:
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, [], [], [], ["continue routine monitoring"], "Critical sensor readings are present and inside plausible ranges."))
        elif scenario == 1:
            sensor["ph"] = None
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_ph"], ["ph"], [], ["restore or manually measure pH before risk or fertigation reasoning"], "pH is a required critical field and is missing."))
        elif scenario == 2:
            sensor["ec_ms_cm"] = None
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_ec"], ["ec_ms_cm"], [], ["restore or manually verify EC before nutrient reasoning"], "EC is a required critical field and is missing."))
        elif scenario == 3:
            sensor["air_temperature_c"] = None
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_temperature"], ["air_temperature_c"], [], ["restore or manually verify air temperature before stress reasoning"], "Air temperature is required and missing."))
        elif scenario == 4:
            sensor["humidity_pct"] = None
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_humidity"], ["humidity_pct"], [], ["restore or manually verify humidity before disease-pressure reasoning"], "Humidity is required and missing."))
        elif scenario == 5:
            sensor["substrate_moisture_pct"] = None
            if "substrate_moisture_pct" not in item["expected_fields"]:
                item["expected_fields"].append("substrate_moisture_pct")
            records.append(make_record(f"generated-sensor-quality-{index:05d}", item, ["missing_moisture"], ["substrate_moisture_pct"], [], ["restore or manually verify substrate moisture before irrigation reasoning"], "Substrate moisture is expected for this system and is missing."))
        elif scenario == 6:
            sensor["ph"] = rng.choice([2.9, 12.8, 14.0])
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
            sensor["timestamp"] = "2026-07-06T08:00:00Z"
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
