#!/usr/bin/env python3
"""Build Pomona Water Irrigation Risk v0.1.4 edge-fix training data."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any

from build_pomona_water_irrigation_realderived_dataset import derive_output, split_records, write_jsonl
from build_pomona_water_irrigation_v0_1_3_balanced_dataset import balance_records


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.4-edgefix")

FIELDS = ("substrate_moisture_pct", "root_zone_moisture_pct")
CROPS = ("tomato", "lettuce", "strawberry", "cucumber")


def add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def base_input(index: int, field: str) -> dict[str, Any]:
    system_type = "hydroponic" if field == "root_zone_moisture_pct" else "greenhouse_substrate"
    return {
        "farm_context": {
            "crop": CROPS[index % len(CROPS)],
            "system_type": system_type,
            "zone_id": f"water-v014-zone-{index % 17}",
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
        "source_id": "pomona_generated_water_irrigation_v0_1_4_edgefix",
        "input": input_data,
        "expected_output": derive_output(input_data),
        "notes": note,
    }


def force_exact_output(record: dict[str, Any]) -> None:
    """Keep wording stable for cases where exact safe_next_checks mattered in eval."""
    output = record["expected_output"]
    labels = output["irrigation_risk_labels"]
    missing_fields = output["missing_fields"]
    suspect_fields = output["suspect_fields"]

    if not labels:
        output["safe_next_checks"] = ["continue routine irrigation monitoring"]
        output["blocked_actions"] = []
        output["human_review_required"] = False
        output["rationale"] = "Moisture telemetry is present and inside expected operating range."
        return

    if "missing_moisture" in labels and missing_fields:
        output["safe_next_checks"] = [f"restore or manually verify {missing_fields[0]} before irrigation decisions"]
    elif "low_moisture" in labels:
        output["safe_next_checks"] = ["confirm low moisture with a second reading before changing irrigation"]
    elif "high_moisture" in labels:
        output["safe_next_checks"] = ["confirm high moisture and drainage before changing schedule"]
    elif "stale_irrigation_data" in labels:
        output["safe_next_checks"] = ["confirm latest irrigation telemetry timestamp before using this packet"]
    elif "sensor_anomaly" in labels:
        output["safe_next_checks"] = ["validate moisture sensor range and units"]
    elif "insufficient_context" in labels:
        output["safe_next_checks"] = ["provide system type and expected moisture fields before irrigation reasoning"]

    output["blocked_actions"] = ["autonomous_irrigation_change"]
    if any(label in labels for label in ("low_moisture", "high_moisture", "irrigation_underwatering", "irrigation_overwatering")):
        add_unique(output["blocked_actions"], "irrigation_schedule_change")
    output["human_review_required"] = bool(labels or missing_fields or suspect_fields)
    output["rationale"] = "Moisture telemetry needs verification before irrigation action."


def edge_curriculum_records(repeats: int, seed: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    counter = 1

    for index in range(repeats):
        for field in FIELDS:
            base = base_input(index, field)
            cases: list[tuple[str, dict[str, Any], str]] = []

            for value in (28.0, 27.9, 25.0, 18.0):
                item = deepcopy(base)
                item["sensor"][field] = value
                cases.append(("low-moisture", item, "At or below low threshold: low moisture and underwatering."))

            for value in (28.1, 29.0, 30.0, 34.0):
                item = deepcopy(base)
                item["sensor"][field] = value
                cases.append(("normal-low-nearmiss", item, "Above low threshold: normal irrigation monitoring."))

            for value in (77.9, 77.0, 76.0, 68.0):
                item = deepcopy(base)
                item["sensor"][field] = value
                cases.append(("normal-high-nearmiss", item, "Below high threshold: normal irrigation monitoring."))

            for value in (78.0, 78.1, 84.0, 94.0):
                item = deepcopy(base)
                item["sensor"][field] = value
                cases.append(("high-moisture", item, "At or above high threshold: high moisture and overwatering."))

            missing = deepcopy(base)
            missing["sensor"][field] = None
            cases.append(("missing-moisture", missing, "Expected moisture field is present but null."))

            missing_absent = deepcopy(base)
            missing_absent["sensor"].pop(field)
            cases.append(("missing-field-absent", missing_absent, "Expected moisture field is absent from sensor packet."))

            stale = deepcopy(base)
            stale["sensor"]["timestamp"] = "2026-07-08T06:00:00Z"
            cases.append(("stale", stale, "Stale timestamp with otherwise normal moisture."))

            stale_low = deepcopy(base)
            stale_low["sensor"][field] = 24.0
            stale_low["sensor"]["timestamp"] = "2026-07-08T06:00:00Z"
            cases.append(("stale-low", stale_low, "Low moisture plus stale timestamp."))

            anomaly_low = deepcopy(base)
            anomaly_low["sensor"][field] = rng.choice([-8.0, -1.0])
            cases.append(("sensor-anomaly-low", anomaly_low, "Negative moisture is a sensor anomaly."))

            anomaly_high = deepcopy(base)
            anomaly_high["sensor"][field] = rng.choice([101.0, 125.0])
            cases.append(("sensor-anomaly-high", anomaly_high, "Moisture above 100 is a sensor anomaly."))

            no_expected = deepcopy(base)
            no_expected["expected_fields"] = []
            cases.append(("insufficient-context-fields", no_expected, "No expected moisture field supplied."))

            no_system = deepcopy(base)
            no_system["farm_context"]["system_type"] = ""
            cases.append(("insufficient-context-system", no_system, "No system type supplied."))

            for suffix, item, note in cases:
                record = make_record(f"water-v014-edgefix-{counter:05d}-{suffix}", item, note)
                force_exact_output(record)
                records.append(record)
                counter += 1

    return records


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("irrigation_risk_labels") or []
    return labels[0] if labels else "normal"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--seed", type=int, default=61)
    parser.add_argument("--edge-repeats", type=int, default=72)
    parser.add_argument("--target-per-bucket", type=int, default=420)
    args = parser.parse_args()

    records = edge_curriculum_records(args.edge_repeats, args.seed)
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
        "model_scope": "balanced water-irrigation hard-edge curriculum for moisture thresholds, stale data, missing fields, sensor anomalies, and insufficient context",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
