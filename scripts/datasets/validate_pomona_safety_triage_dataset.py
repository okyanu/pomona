#!/usr/bin/env python3
"""Validate Pomona safety-triage JSONL scaffold."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-safety-triage-v0.1")

ALLOWED_SAFETY_LABELS = {
    "safe_observation_only",
    "safe_manual_check",
    "missing_context",
    "human_review_required",
    "direct_actuator_control_request",
    "autonomous_fertigation_change",
    "pesticide_dosage_request",
    "unsafe_chemical_recommendation",
    "definitive_disease_diagnosis",
    "ignores_missing_data",
}

ALLOWED_BLOCKED_ACTIONS = {
    "direct_pesticide_dosage",
    "autonomous_fertigation_change",
    "direct_actuator_control",
    "definitive_disease_diagnosis",
    "unsafe_chemical_recommendation",
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

    require_keys(input_data, ["farm_context", "sensor", "risk_labels", "proposed_action", "actor"], f"{context}.input")
    if not isinstance(input_data["farm_context"], dict):
        raise ValueError(f"{context}.input.farm_context must be an object")
    if not isinstance(input_data["sensor"], dict):
        raise ValueError(f"{context}.input.sensor must be an object")
    if not isinstance(input_data["risk_labels"], list):
        raise ValueError(f"{context}.input.risk_labels must be a list")
    if not isinstance(input_data["proposed_action"], str) or not input_data["proposed_action"].strip():
        raise ValueError(f"{context}.input.proposed_action must be a non-empty string")

    require_keys(
        output,
        ["safety_labels", "blocked_actions", "safe_alternative", "human_review_required", "rationale"],
        f"{context}.expected_output",
    )
    safety_labels = output["safety_labels"]
    blocked_actions = output["blocked_actions"]
    if not isinstance(safety_labels, list):
        raise ValueError(f"{context}.expected_output.safety_labels must be a list")
    if not isinstance(blocked_actions, list):
        raise ValueError(f"{context}.expected_output.blocked_actions must be a list")
    unknown_safety = sorted(set(safety_labels) - ALLOWED_SAFETY_LABELS)
    unknown_blocked = sorted(set(blocked_actions) - ALLOWED_BLOCKED_ACTIONS)
    if unknown_safety:
        raise ValueError(f"{context}: unknown safety labels: {unknown_safety}")
    if unknown_blocked:
        raise ValueError(f"{context}: unknown blocked actions: {unknown_blocked}")
    if len(safety_labels) != len(set(safety_labels)):
        raise ValueError(f"{context}: duplicate safety labels")
    if len(blocked_actions) != len(set(blocked_actions)):
        raise ValueError(f"{context}: duplicate blocked actions")
    if not isinstance(output["safe_alternative"], str) or not output["safe_alternative"].strip():
        raise ValueError(f"{context}.expected_output.safe_alternative must be a non-empty string")
    if not isinstance(output["rationale"], str) or not output["rationale"].strip():
        raise ValueError(f"{context}.expected_output.rationale must be a non-empty string")
    if not isinstance(output["human_review_required"], bool):
        raise ValueError(f"{context}.expected_output.human_review_required must be boolean")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument(
        "--jsonl",
        action="append",
        type=Path,
        default=[],
        help="Additional JSONL files to validate, such as generated train/validation/test splits.",
    )
    args = parser.parse_args()

    total = 0
    paths = [args.dataset_dir / "data" / name for name in ("samples.jsonl", "eval_cases.jsonl")]
    paths.extend(args.jsonl)
    for path in paths:
        records = read_jsonl(path)
        for index, record in enumerate(records, start=1):
            validate_record(record, f"{path}:{index}")
        print(f"OK {path}: {len(records)} records")
        total += len(records)
    print(f"Validated {total} Pomona safety-triage records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
