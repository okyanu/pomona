#!/usr/bin/env python3
"""Build Pomona Water Irrigation Risk v0.1.2 hardcase training data."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from build_pomona_water_irrigation_realderived_dataset import derive_output, split_records, write_jsonl


DEFAULT_BASE_JSONL = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.1-realderived/all_records.jsonl")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.2-hardcases")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def base_input(index: int) -> dict[str, Any]:
    field = "substrate_moisture_pct" if index % 2 else "root_zone_moisture_pct"
    system_type = "greenhouse_substrate" if field == "substrate_moisture_pct" else "hydroponic"
    return {
        "farm_context": {
            "crop": ["tomato", "lettuce", "strawberry", "cucumber"][index % 4],
            "system_type": system_type,
            "zone_id": f"water-v012-hardcase-{index % 11}",
        },
        "sensor": {
            field: 48.0,
            "air_temperature_c": 24.0,
            "humidity_pct": 68.0,
            "timestamp": "2026-07-09T10:00:00Z",
        },
        "expected_fields": [field],
    }


def make_record(record_id: str, input_data: dict[str, Any], note: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "source_id": "pomona_generated_water_irrigation_v0_1_2_hardcases",
        "input": input_data,
        "expected_output": derive_output(input_data),
        "notes": note,
    }


def hardcase_records(repeats: int) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    counter = 1
    for index in range(repeats):
        base = base_input(index)
        field = base["expected_fields"][0]

        cases: list[tuple[str, dict[str, Any], str]] = []

        stale = deepcopy(base)
        stale["sensor"]["timestamp"] = "2026-07-08T06:00:00Z"
        cases.append(("stale", stale, "Stale timestamp with otherwise normal moisture."))

        normal_recent = deepcopy(base)
        normal_recent["sensor"][field] = 48.0
        cases.append(("normal-recent", normal_recent, "Recent normal moisture should stay normal."))

        missing = deepcopy(base)
        missing["sensor"][field] = None
        cases.append(("missing-moisture", missing, "Expected moisture field is explicitly missing."))

        low_edge = deepcopy(base)
        low_edge["sensor"][field] = 28.0
        cases.append(("low-edge", low_edge, "Boundary low moisture should classify as low/underwatering."))

        just_above_low = deepcopy(base)
        just_above_low["sensor"][field] = 29.0
        cases.append(("just-above-low", just_above_low, "Near-miss low moisture should stay normal."))

        high_edge = deepcopy(base)
        high_edge["sensor"][field] = 78.0
        cases.append(("high-edge", high_edge, "Boundary high moisture should classify as high/overwatering."))

        just_below_high = deepcopy(base)
        just_below_high["sensor"][field] = 77.0
        cases.append(("just-below-high", just_below_high, "Near-miss high moisture should stay normal."))

        impossible_low = deepcopy(base)
        impossible_low["sensor"][field] = -1.0
        cases.append(("impossible-low", impossible_low, "Negative moisture is a sensor anomaly."))

        impossible_high = deepcopy(base)
        impossible_high["sensor"][field] = 101.0
        cases.append(("impossible-high", impossible_high, "Moisture above 100 is a sensor anomaly."))

        no_expected = deepcopy(base)
        no_expected["expected_fields"] = []
        cases.append(("insufficient-context", no_expected, "Missing expected fields means insufficient context."))

        for suffix, item, note in cases:
            records.append(make_record(f"water-v012-hardcase-{counter:05d}-{suffix}", item, note))
            counter += 1
    return records


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("irrigation_risk_labels") or []
    return labels[0] if labels else "normal"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-jsonl", type=Path, default=DEFAULT_BASE_JSONL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--hardcase-repeats", type=int, default=120)
    parser.add_argument("--seed", type=int, default=53)
    args = parser.parse_args()

    records = read_jsonl(args.base_jsonl) + hardcase_records(args.hardcase_repeats)
    train, validation, test = split_records(records, args.seed)

    write_jsonl(args.output_dir / "all_records.jsonl", records)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)

    label_counts: dict[str, int] = defaultdict(int)
    for record in records:
        label_counts[bucket_key(record)] += 1
    summary = {
        "records": len(records),
        "base_records": len(read_jsonl(args.base_jsonl)),
        "hardcase_records": len(records) - len(read_jsonl(args.base_jsonl)),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "label_counts": dict(sorted(label_counts.items())),
        "model_scope": "moisture risk only; stale/anomaly/boundary hardcases added",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
