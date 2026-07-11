#!/usr/bin/env python3
"""Validate Pomona water-irrigation risk JSONL scaffold and generated splits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-water-irrigation-risk-v0.1")

ALLOWED_LABELS = {
    "missing_water_level",
    "missing_moisture",
    "low_water_level",
    "high_water_level",
    "low_moisture",
    "high_moisture",
    "irrigation_underwatering",
    "irrigation_overwatering",
    "pump_flow_anomaly",
    "valve_state_conflict",
    "stale_irrigation_data",
    "sensor_anomaly",
    "insufficient_context",
}

ALLOWED_BLOCKED_ACTIONS = {
    "autonomous_irrigation_change",
    "direct_pump_control",
    "direct_valve_control",
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
        [
            "irrigation_risk_labels",
            "missing_fields",
            "suspect_fields",
            "safe_next_checks",
            "blocked_actions",
            "human_review_required",
            "rationale",
        ],
        f"{context}.expected_output",
    )
    labels = output["irrigation_risk_labels"]
    if not isinstance(labels, list):
        raise ValueError(f"{context}.expected_output.irrigation_risk_labels must be a list")
    unknown_labels = sorted(set(labels) - ALLOWED_LABELS)
    if unknown_labels:
        raise ValueError(f"{context}: unknown irrigation risk labels: {unknown_labels}")
    if len(labels) != len(set(labels)):
        raise ValueError(f"{context}: duplicate irrigation risk labels")

    blocked = output["blocked_actions"]
    if not isinstance(blocked, list):
        raise ValueError(f"{context}.expected_output.blocked_actions must be a list")
    unknown_blocked = sorted(set(blocked) - ALLOWED_BLOCKED_ACTIONS)
    if unknown_blocked:
        raise ValueError(f"{context}: unknown blocked actions: {unknown_blocked}")
    if len(blocked) != len(set(blocked)):
        raise ValueError(f"{context}: duplicate blocked actions")

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
    print(f"Validated {total} Pomona water-irrigation risk records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
