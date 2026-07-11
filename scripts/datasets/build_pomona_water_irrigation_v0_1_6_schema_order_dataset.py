#!/usr/bin/env python3
"""Build Water Irrigation Risk v0.1.6 schema-order training data.

The v0.1.5 model was safe but sometimes omitted irrigation_risk_labels and
missing_fields for stale and sensor-anomaly packets. This builder keeps an
honest balanced validation/test split, while adding extra train-only examples
for those two output-completion cases.
"""

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
from build_pomona_water_irrigation_v0_1_4_edgefix_dataset import edge_curriculum_records
from build_pomona_water_irrigation_v0_1_5_label_lock_dataset import sensor_anomaly_lock_records


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.6-schema-order")
PRIORITY_LABELS = ("sensor_anomaly", "stale_irrigation_data")


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("irrigation_risk_labels") or []
    return labels[0] if labels else "normal"


def priority_training_records(seed: int, per_label: int) -> list[dict[str, Any]]:
    """Create distinct, train-only examples for fields skipped by v0.1.5."""
    rng = random.Random(seed)
    candidates = edge_curriculum_records(repeats=120, seed=seed)
    candidates.extend(sensor_anomaly_lock_records(repeats=60, seed=seed))
    by_label: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in candidates:
        label = bucket_key(record)
        if label in PRIORITY_LABELS:
            by_label[label].append(record)

    records: list[dict[str, Any]] = []
    for label in PRIORITY_LABELS:
        bucket = by_label[label]
        if not bucket:
            raise ValueError(f"No priority examples generated for {label}")
        rng.shuffle(bucket)
        for index in range(per_label):
            item = deepcopy(bucket[index % len(bucket)])
            item["id"] = f"water-v016-schema-order-{label}-{index + 1:05d}"
            item["source_id"] = "pomona_generated_water_irrigation_v0_1_6_schema_order"
            item["notes"] = (
                "Schema-completion curriculum: always emit irrigation_risk_labels "
                "and missing_fields for this stale or sensor-anomaly packet."
            )
            records.append(item)
    rng.shuffle(records)
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=71)
    parser.add_argument("--edge-repeats", type=int, default=72)
    parser.add_argument("--lock-repeats", type=int, default=40)
    parser.add_argument("--target-per-bucket", type=int, default=520)
    parser.add_argument("--priority-per-label", type=int, default=480)
    args = parser.parse_args()

    baseline_records = edge_curriculum_records(args.edge_repeats, args.seed)
    baseline_records.extend(sensor_anomaly_lock_records(args.lock_repeats, args.seed))
    balanced = balance_records(baseline_records, args.seed, args.target_per_bucket)
    train, validation, test = split_records(balanced, args.seed)

    priority_records = priority_training_records(args.seed, args.priority_per_label)
    train.extend(priority_records)
    random.Random(args.seed).shuffle(train)

    all_records = train + validation + test
    write_jsonl(args.output_dir / "all_records.jsonl", all_records)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)

    split_counts = {
        "train": defaultdict(int),
        "validation": defaultdict(int),
        "test": defaultdict(int),
    }
    for split_name, records in (("train", train), ("validation", validation), ("test", test)):
        for record in records:
            split_counts[split_name][bucket_key(record)] += 1

    summary = {
        "records": len(all_records),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "baseline_records": len(balanced),
        "train_only_priority_records": len(priority_records),
        "priority_labels": list(PRIORITY_LABELS),
        "split_label_counts": {
            split_name: dict(sorted(counts.items())) for split_name, counts in split_counts.items()
        },
        "model_scope": (
            "v0.1.5 label-lock baseline with train-only stale/sensor-anomaly "
            "schema-completion curriculum; validation and test remain balanced"
        ),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
