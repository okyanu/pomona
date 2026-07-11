#!/usr/bin/env python3
"""Build Pomona Water Irrigation Risk v0.1.3 balanced training data."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from build_pomona_water_irrigation_v0_1_2_hardcases_dataset import hardcase_records
from build_pomona_water_irrigation_realderived_dataset import generated_records, split_records, write_jsonl


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.3-balancedfix")


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("irrigation_risk_labels") or []
    return labels[0] if labels else "normal"


def balance_records(records: list[dict[str, Any]], seed: int, target_per_bucket: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        buckets[bucket_key(record)].append(record)

    balanced: list[dict[str, Any]] = []
    for key, bucket in sorted(buckets.items()):
        rng.shuffle(bucket)
        if len(bucket) >= target_per_bucket:
            selected = bucket[:target_per_bucket]
        else:
            selected = list(bucket)
            while len(selected) < target_per_bucket:
                clone = json.loads(json.dumps(rng.choice(bucket)))
                clone["id"] = f"{clone['id']}-dup-{len(selected):04d}"
                selected.append(clone)
        balanced.extend(selected)
    rng.shuffle(balanced)
    return balanced


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=57)
    parser.add_argument("--generated-records", type=int, default=1800)
    parser.add_argument("--hardcase-repeats", type=int, default=160)
    parser.add_argument("--target-per-bucket", type=int, default=360)
    args = parser.parse_args()

    records = generated_records(args.seed, args.generated_records) + hardcase_records(args.hardcase_repeats)
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
        "model_scope": "balanced moisture risk dataset; normal bucket capped to avoid normal collapse",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
