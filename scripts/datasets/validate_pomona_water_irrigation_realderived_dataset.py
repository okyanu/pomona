#!/usr/bin/env python3
"""Validate Pomona water-irrigation v0.1.1 simplified JSONL."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.1-realderived")

ALLOWED_LABELS = {
    "missing_moisture",
    "low_moisture",
    "high_moisture",
    "irrigation_underwatering",
    "irrigation_overwatering",
    "stale_irrigation_data",
    "sensor_anomaly",
    "insufficient_context",
}

ALLOWED_BLOCKED_ACTIONS = {
    "autonomous_irrigation_change",
    "irrigation_schedule_change",
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


def validate_record(record: dict[str, Any], context: str) -> None:
    for key in ("id", "input", "expected_output"):
        if key not in record:
            raise ValueError(f"{context}: missing {key}")
    input_data = record["input"]
    output = record["expected_output"]
    if not isinstance(input_data.get("farm_context"), dict):
        raise ValueError(f"{context}.input.farm_context must be object")
    if not isinstance(input_data.get("sensor"), dict):
        raise ValueError(f"{context}.input.sensor must be object")
    if not isinstance(input_data.get("expected_fields"), list):
        raise ValueError(f"{context}.input.expected_fields must be list")

    labels = output.get("irrigation_risk_labels")
    blocked = output.get("blocked_actions")
    if not isinstance(labels, list):
        raise ValueError(f"{context}.expected_output.irrigation_risk_labels must be list")
    if not isinstance(blocked, list):
        raise ValueError(f"{context}.expected_output.blocked_actions must be list")
    unknown_labels = sorted(set(labels) - ALLOWED_LABELS)
    if unknown_labels:
        raise ValueError(f"{context}: unknown labels: {unknown_labels}")
    unknown_blocked = sorted(set(blocked) - ALLOWED_BLOCKED_ACTIONS)
    if unknown_blocked:
        raise ValueError(f"{context}: unknown blocked actions: {unknown_blocked}")
    for key in ("missing_fields", "suspect_fields", "safe_next_checks"):
        if not isinstance(output.get(key), list):
            raise ValueError(f"{context}.expected_output.{key} must be list")
    if not isinstance(output.get("human_review_required"), bool):
        raise ValueError(f"{context}.expected_output.human_review_required must be boolean")
    if not isinstance(output.get("rationale"), str) or not output["rationale"].strip():
        raise ValueError(f"{context}.expected_output.rationale must be non-empty string")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--jsonl", action="append", type=Path, default=[])
    args = parser.parse_args()

    paths = args.jsonl or [args.data_dir / name for name in ("train.jsonl", "validation.jsonl", "test.jsonl")]
    total = 0
    for path in paths:
        records = read_jsonl(path)
        for index, record in enumerate(records, start=1):
            validate_record(record, f"{path}:{index}")
        print(f"OK {path}: {len(records)} records")
        total += len(records)
    print(f"Validated {total} Pomona water-irrigation v0.1.1 records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
