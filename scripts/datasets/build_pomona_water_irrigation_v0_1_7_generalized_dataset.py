#!/usr/bin/env python3
"""Build leakage-free generalized data for Water Irrigation Risk v0.1.7."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from build_pomona_water_irrigation_realderived_dataset import derive_output, write_jsonl
from build_pomona_water_irrigation_v0_1_4_edgefix_dataset import force_exact_output


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.7-generalized")
BUCKETS = (
    "normal",
    "low_moisture",
    "high_moisture",
    "missing_moisture",
    "stale_irrigation_data",
    "sensor_anomaly",
    "insufficient_context",
)
CROPS = ("tomato", "lettuce", "strawberry", "cucumber", "pepper")


def base_input(split: str, bucket: str, index: int, rng: random.Random) -> tuple[dict[str, Any], str]:
    field = "root_zone_moisture_pct" if index % 2 else "substrate_moisture_pct"
    system_type = "hydroponic" if field == "root_zone_moisture_pct" else "greenhouse_substrate"
    sensor: dict[str, Any] = {
        field: round(rng.uniform(35.0, 65.0), 2),
        "air_temperature_c": round(rng.uniform(16.5, 34.0), 1),
        "humidity_pct": round(rng.uniform(38.0, 92.0), 1),
        "timestamp": "2026-07-10T10:00:00Z",
        "telemetry_age_minutes": round(rng.uniform(2.0, 45.0), 1),
    }
    return {
        "farm_context": {
            "crop": CROPS[(index + len(split)) % len(CROPS)],
            "system_type": system_type,
            "zone_id": f"water-v017-{split}-{bucket}-{index:05d}",
        },
        "sensor": sensor,
        "expected_fields": [field],
    }, field


def apply_bucket(input_data: dict[str, Any], field: str, bucket: str, index: int, rng: random.Random) -> None:
    sensor = input_data["sensor"]
    if bucket == "normal":
        if index % 3 == 0:
            sensor[field] = round(rng.uniform(28.2, 32.0), 2)
        elif index % 3 == 1:
            sensor[field] = round(rng.uniform(74.0, 77.8), 2)
        else:
            sensor[field] = round(rng.uniform(33.0, 73.0), 2)
    elif bucket == "low_moisture":
        sensor[field] = round(rng.uniform(0.0, 27.95), 2)
    elif bucket == "high_moisture":
        sensor[field] = round(rng.uniform(78.0, 100.0), 2)
    elif bucket == "missing_moisture":
        if index % 2:
            sensor.pop(field)
        else:
            sensor[field] = None
    elif bucket == "stale_irrigation_data":
        sensor[field] = round(rng.uniform(31.0, 75.0), 2)
        sensor["timestamp"] = "stale" if index % 2 else "2026-07-08T06:00:00Z"
        sensor["telemetry_age_minutes"] = round(rng.uniform(90.0, 900.0), 1)
    elif bucket == "sensor_anomaly":
        sensor[field] = round(rng.uniform(-80.0, -0.05), 2) if index % 2 else round(rng.uniform(100.05, 180.0), 2)
    elif bucket == "insufficient_context":
        if index % 3 == 0:
            input_data["expected_fields"] = []
        elif index % 3 == 1:
            input_data["farm_context"]["system_type"] = ""
        else:
            input_data["expected_fields"] = []
            input_data["farm_context"]["system_type"] = ""
    else:
        raise ValueError(f"Unknown bucket: {bucket}")

    if bucket in {"low_moisture", "high_moisture"} and index % 6 == 0:
        sensor["timestamp"] = "stale"
        sensor["telemetry_age_minutes"] = round(rng.uniform(90.0, 500.0), 1)


def build_split(split: str, per_bucket: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for bucket in BUCKETS:
        for index in range(per_bucket):
            input_data, field = base_input(split, bucket, index, rng)
            apply_bucket(input_data, field, bucket, index, rng)
            record = {
                "id": f"water-v017-{split}-{bucket}-{index:05d}",
                "source_id": "pomona_generated_water_irrigation_v0_1_7_generalized",
                "input": input_data,
                "expected_output": derive_output(input_data),
                "notes": "Generalized threshold case with split-specific context and continuous values.",
            }
            force_exact_output(record)
            records.append(record)
    rng.shuffle(records)
    return records


def count_primary(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for record in records:
        labels = record["expected_output"].get("irrigation_risk_labels") or []
        counts[labels[0] if labels else "normal"] += 1
    return dict(sorted(counts.items()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--train-per-bucket", type=int, default=480)
    parser.add_argument("--validation-per-bucket", type=int, default=56)
    parser.add_argument("--test-per-bucket", type=int, default=56)
    args = parser.parse_args()

    train = build_split("train", args.train_per_bucket, seed=173)
    validation = build_split("validation", args.validation_per_bucket, seed=179)
    test = build_split("test", args.test_per_bucket, seed=181)
    all_records = train + validation + test

    write_jsonl(args.output_dir / "all_records.jsonl", all_records)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)
    summary = {
        "records": len(all_records),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "split_primary_label_counts": {
            "train": count_primary(train),
            "validation": count_primary(validation),
            "test": count_primary(test),
        },
        "design": "Independent split generation, continuous values, boundary ranges, stale age, and no resampled duplicates.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
