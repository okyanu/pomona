#!/usr/bin/env python3
"""Validate Pomona actuator-command-gate JSONL scaffold and generated splits."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-actuator-command-gate-v0.1")

ALLOWED_DECISIONS = {"allowed", "blocked", "needs_human_approval"}

ALLOWED_GATE_LABELS = {
    "safe_observation_only",
    "safe_manual_check",
    "human_approval_required",
    "direct_actuator_control_request",
    "autonomous_fertigation_change",
    "irrigation_control_request",
    "climate_control_request",
    "chemical_application_request",
    "unsafe_chemical_recommendation",
    "definitive_disease_diagnosis",
    "missing_or_bad_sensor_data",
    "actuator_conflict",
    "out_of_policy_request",
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

    require_keys(
        input_data,
        ["farm_context", "sensor", "sensor_quality", "risk_labels", "actor", "proposed_command"],
        f"{context}.input",
    )
    if not isinstance(input_data["farm_context"], dict):
        raise ValueError(f"{context}.input.farm_context must be an object")
    if not isinstance(input_data["sensor"], dict):
        raise ValueError(f"{context}.input.sensor must be an object")
    if not isinstance(input_data["sensor_quality"], dict):
        raise ValueError(f"{context}.input.sensor_quality must be an object")
    if not isinstance(input_data["risk_labels"], list):
        raise ValueError(f"{context}.input.risk_labels must be a list")
    if not isinstance(input_data["proposed_command"], dict):
        raise ValueError(f"{context}.input.proposed_command must be an object")
    if not isinstance(input_data["actor"], str) or not input_data["actor"].strip():
        raise ValueError(f"{context}.input.actor must be a non-empty string")

    require_keys(
        output,
        ["decision", "gate_labels", "blocked_actions", "human_approval_required", "safe_alternatives", "rationale"],
        f"{context}.expected_output",
    )
    if output["decision"] not in ALLOWED_DECISIONS:
        raise ValueError(f"{context}: unknown decision: {output['decision']}")
    if not isinstance(output["gate_labels"], list):
        raise ValueError(f"{context}.expected_output.gate_labels must be a list")
    if not isinstance(output["blocked_actions"], list):
        raise ValueError(f"{context}.expected_output.blocked_actions must be a list")
    unknown_labels = sorted(set(output["gate_labels"]) - ALLOWED_GATE_LABELS)
    unknown_blocked = sorted(set(output["blocked_actions"]) - ALLOWED_BLOCKED_ACTIONS)
    if unknown_labels:
        raise ValueError(f"{context}: unknown gate labels: {unknown_labels}")
    if unknown_blocked:
        raise ValueError(f"{context}: unknown blocked actions: {unknown_blocked}")
    if len(output["gate_labels"]) != len(set(output["gate_labels"])):
        raise ValueError(f"{context}: duplicate gate labels")
    if len(output["blocked_actions"]) != len(set(output["blocked_actions"])):
        raise ValueError(f"{context}: duplicate blocked actions")
    if not isinstance(output["human_approval_required"], bool):
        raise ValueError(f"{context}.expected_output.human_approval_required must be boolean")
    if not isinstance(output["safe_alternatives"], list) or not output["safe_alternatives"]:
        raise ValueError(f"{context}.expected_output.safe_alternatives must be a non-empty list")
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
    print(f"Validated {total} Pomona actuator-command-gate records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
