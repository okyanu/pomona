#!/usr/bin/env python3
"""Build Pomona Water Irrigation Risk v0.1.5 label-lock training data."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from build_pomona_water_irrigation_realderived_dataset import split_records, write_jsonl
from build_pomona_water_irrigation_v0_1_3_balanced_dataset import balance_records
from build_pomona_water_irrigation_v0_1_4_edgefix_dataset import (
    CROPS,
    FIELDS,
    base_input,
    edge_curriculum_records,
    force_exact_output,
    make_record,
)


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.5-label-lock")


def set_sensor_anomaly_output(record: dict[str, Any], field: str) -> None:
    record["expected_output"] = {
        "irrigation_risk_labels": ["sensor_anomaly"],
        "missing_fields": [],
        "suspect_fields": [field],
        "safe_next_checks": ["validate moisture sensor range and units"],
        "blocked_actions": ["autonomous_irrigation_change"],
        "human_review_required": True,
        "rationale": "Moisture telemetry needs verification before irrigation action.",
    }


def sensor_anomaly_lock_records(repeats: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    counter = 1
    values = [-25.0, -10.0, -1.0, -0.1, 100.1, 101.0, 110.0, 125.0, 150.0]
    confusing_notes = [
        "Impossible moisture below 0 must always be sensor_anomaly.",
        "Impossible moisture above 100 must always be sensor_anomaly.",
        "Do not invent alternate label names for impossible moisture.",
        "Do not classify impossible moisture as low_moisture or high_moisture.",
        "The only valid risk label for this impossible moisture case is sensor_anomaly.",
    ]

    for index in range(repeats):
        for field in FIELDS:
            base = base_input(index, field)
            base["farm_context"]["crop"] = CROPS[(index + counter) % len(CROPS)]
            for value in values:
                item = deepcopy(base)
                item["sensor"][field] = value
                record = make_record(
                    f"water-v015-label-lock-{counter:05d}-sensor-anomaly",
                    item,
                    rng.choice(confusing_notes),
                )
                set_sensor_anomaly_output(record, field)
                records.append(record)
                counter += 1

            near_low = deepcopy(base)
            near_low["sensor"][field] = rng.choice([0.0, 0.1, 2.0, 5.0])
            normal_record = make_record(
                f"water-v015-label-lock-{counter:05d}-low-valid",
                near_low,
                "Valid in-range low moisture should stay low_moisture, not sensor_anomaly.",
            )
            force_exact_output(normal_record)
            records.append(normal_record)
            counter += 1

            near_high = deepcopy(base)
            near_high["sensor"][field] = rng.choice([95.0, 99.0, 100.0])
            high_record = make_record(
                f"water-v015-label-lock-{counter:05d}-high-valid",
                near_high,
                "Valid in-range high moisture should stay high_moisture, not sensor_anomaly.",
            )
            force_exact_output(high_record)
            records.append(high_record)
            counter += 1

    return records


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("irrigation_risk_labels") or []
    return labels[0] if labels else "normal"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=67)
    parser.add_argument("--edge-repeats", type=int, default=72)
    parser.add_argument("--lock-repeats", type=int, default=40)
    parser.add_argument("--target-per-bucket", type=int, default=520)
    args = parser.parse_args()

    records = edge_curriculum_records(args.edge_repeats, args.seed)
    records.extend(sensor_anomaly_lock_records(args.lock_repeats, args.seed))
    balanced = balance_records(records, args.seed, args.target_per_bucket)
    train, validation, test = split_records(balanced, args.seed)

    write_jsonl(args.output_dir / "all_records.jsonl", balanced)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)

    label_counts: dict[str, int] = defaultdict(int)
    for record in balanced:
        label_counts[bucket_key(record)] += 1
    summary = {
        "records": len(balanced),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "label_counts": dict(sorted(label_counts.items())),
        "model_scope": "v0.1.4 edge curriculum plus sensor_anomaly label-lock examples for impossible moisture values",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
