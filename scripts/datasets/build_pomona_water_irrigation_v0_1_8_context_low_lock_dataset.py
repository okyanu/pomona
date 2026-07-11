#!/usr/bin/env python3
"""Build v0.1.8 with focused context, low-moisture, and label-lock training."""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any

from build_pomona_water_irrigation_realderived_dataset import derive_output, write_jsonl
from build_pomona_water_irrigation_v0_1_4_edgefix_dataset import force_exact_output
from build_pomona_water_irrigation_v0_1_7_generalized_dataset import build_split, count_primary


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.8-context-low-lock")


def priority_input(kind: str, index: int, rng: random.Random) -> tuple[dict[str, Any], str]:
    field = "root_zone_moisture_pct" if index % 2 else "substrate_moisture_pct"
    system_type = "hydroponic" if field == "root_zone_moisture_pct" else "greenhouse_substrate"
    input_data = {
        "farm_context": {
            "crop": ("tomato", "lettuce", "strawberry", "cucumber")[index % 4],
            "system_type": system_type,
            "zone_id": f"water-v018-priority-{kind}-{index:05d}",
        },
        "sensor": {
            field: round(rng.uniform(35.0, 65.0), 2),
            "air_temperature_c": round(rng.uniform(17.0, 33.0), 1),
            "humidity_pct": round(rng.uniform(42.0, 90.0), 1),
            "timestamp": "2026-07-10T10:00:00Z",
            "telemetry_age_minutes": round(rng.uniform(2.0, 40.0), 1),
        },
        "expected_fields": [field],
    }
    return input_data, field


def make_priority_record(kind: str, index: int, rng: random.Random) -> dict[str, Any]:
    input_data, field = priority_input(kind, index, rng)
    if kind == "missing_system_type":
        input_data["farm_context"]["system_type"] = ""
    elif kind == "low_moisture":
        if index % 3 == 0:
            input_data["sensor"][field] = round(rng.uniform(26.5, 28.0), 2)
        else:
            input_data["sensor"][field] = round(rng.uniform(0.0, 26.49), 2)
    elif kind == "normal_low_boundary":
        input_data["sensor"][field] = round(rng.uniform(28.01, 33.0), 2)
    else:
        raise ValueError(f"Unknown priority kind: {kind}")

    record = {
        "id": f"water-v018-priority-{kind}-{index:05d}",
        "source_id": "pomona_generated_water_irrigation_v0_1_8_context_low_lock",
        "input": input_data,
        "expected_output": derive_output(input_data),
        "notes": "Focused external-holdout correction with strict allowed-label and blocked-action pairing.",
    }
    force_exact_output(record)
    return record


def priority_records(seed: int, context_count: int, low_count: int, normal_count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records = [make_priority_record("missing_system_type", index, rng) for index in range(context_count)]
    records.extend(make_priority_record("low_moisture", index, rng) for index in range(low_count))
    records.extend(make_priority_record("normal_low_boundary", index, rng) for index in range(normal_count))
    rng.shuffle(records)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--context-priority", type=int, default=480)
    parser.add_argument("--low-priority", type=int, default=480)
    parser.add_argument("--normal-priority", type=int, default=240)
    args = parser.parse_args()

    train = build_split("train", per_bucket=480, seed=191)
    validation = build_split("validation", per_bucket=56, seed=193)
    test = build_split("test", per_bucket=56, seed=197)
    focused = priority_records(199, args.context_priority, args.low_priority, args.normal_priority)
    train.extend(focused)
    random.Random(199).shuffle(train)
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
        "focused_train_records": len(focused),
        "focused_counts": {
            "missing_system_type": args.context_priority,
            "low_moisture": args.low_priority,
            "normal_low_boundary": args.normal_priority,
        },
        "split_primary_label_counts": {
            "train": count_primary(train),
            "validation": count_primary(validation),
            "test": count_primary(test),
        },
        "design": "Leakage-free v0.1.7 base plus train-only context, low-moisture, normal-boundary, and allowed-label lock curriculum.",
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
