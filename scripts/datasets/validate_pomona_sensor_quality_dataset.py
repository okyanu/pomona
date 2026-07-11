#!/usr/bin/env python3
"""Validate Pomona sensor-quality JSONL scaffold and generated splits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-sensor-quality-v0.1")

ALLOWED_LABELS = {
    "missing_ph",
    "missing_ec",
    "missing_temperature",
    "missing_humidity",
    "missing_moisture",
    "impossible_ph",
    "impossible_ec",
    "impossible_temperature",
    "impossible_humidity",
    "stale_reading",
    "unit_mismatch",
    "sensor_drift_possible",
    "conflicting_readings",
    "insufficient_context",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{lineno}: record must be an object")
            records.append(value)
    return records


def require_keys(value: dict[str, Any], keys: list[str], context: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValueError(f"{context}: missing required keys: {missing}")


def validate_record(record: dict[str, Any], context: str) -> None:
    require_keys(record, ["id", "input", "expected_output"], context)
    input_data = record["input"]
    output = record["expected_output"]
    if not isinstance(input_data, dict):
        raise ValueError(f"{context}: input must be an object")
    if not isinstance(output, dict):
        raise ValueError(f"{context}: expected_output must be an object")

    require_keys(input_data, ["farm_context", "sensor", "expected_fields"], f"{context}.input")
    if not isinstance(input_data["farm_context"], dict):
        raise ValueError(f"{context}.input.farm_context must be an object")
    if not isinstance(input_data["sensor"], dict):
        raise ValueError(f"{context}.input.sensor must be an object")
    if not isinstance(input_data["expected_fields"], list):
        raise ValueError(f"{context}.input.expected_fields must be a list")

    require_keys(
        output,
        ["data_quality_labels", "missing_fields", "suspect_fields", "safe_next_checks", "human_review_required", "rationale"],
        f"{context}.expected_output",
    )
    labels = output["data_quality_labels"]
    if not isinstance(labels, list):
        raise ValueError(f"{context}.expected_output.data_quality_labels must be a list")
    unknown_labels = sorted(set(labels) - ALLOWED_LABELS)
    if unknown_labels:
        raise ValueError(f"{context}: unknown data quality labels: {unknown_labels}")
    if len(labels) != len(set(labels)):
        raise ValueError(f"{context}: duplicate data quality labels")

    for key in ("missing_fields", "suspect_fields", "safe_next_checks"):
        if not isinstance(output[key], list):
            raise ValueError(f"{context}.expected_output.{key} must be a list")
    if not isinstance(output["human_review_required"], bool):
        raise ValueError(f"{context}.expected_output.human_review_required must be boolean")
    if not isinstance(output["rationale"], str) or not output["rationale"].strip():
        raise ValueError(f"{context}.expected_output.rationale must be a non-empty string")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--jsonl", action="append", type=Path, default=[])
    args = parser.parse_args()

    paths = [args.dataset_dir / "data" / name for name in ("samples.jsonl", "eval_cases.jsonl")]
    paths.extend(args.jsonl)
    total = 0
    for path in paths:
        records = read_jsonl(path)
        for index, record in enumerate(records, start=1):
            validate_record(record, f"{path}:{index}")
        print(f"OK {path}: {len(records)} records")
        total += len(records)
    print(f"Validated {total} Pomona sensor-quality records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
