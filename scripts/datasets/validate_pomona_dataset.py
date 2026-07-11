#!/usr/bin/env python3
"""Validate Pomona tomato risk JSONL seed and evaluation records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-tomato-risk-v0.1")

REQUIRED_INPUT_FIELDS = {
    "system_type",
    "crop",
    "growth_stage",
    "air_temperature_c",
    "humidity_pct",
    "co2_ppm",
    "light_lux",
    "light_ppfd",
    "ph",
    "ec_ms_cm",
    "tds_ppm",
    "water_temperature_c",
    "substrate_temperature_c",
    "substrate_moisture_pct",
    "actuator_states",
    "symptoms",
}

ALLOWED_RISK_LABELS = {
    "high_ph",
    "low_ph",
    "high_ec",
    "low_ec",
    "heat_stress",
    "cold_stress",
    "fungal_pressure",
    "nutrient_uptake_issue",
    "sensor_anomaly",
    "missing_critical_data",
    "water_level_risk",
    "actuator_conflict",
}

ALLOWED_BLOCKED_ACTIONS = {
    "direct_pesticide_dosage",
    "autonomous_fertigation_change",
    "direct_actuator_control",
    "definitive_disease_diagnosis",
    "unsafe_chemical_recommendation",
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_number}: record must be a JSON object")
            records.append(record)
    return records


def require_list(record_id: str, output: dict[str, Any], field: str) -> list[Any]:
    value = output.get(field)
    if not isinstance(value, list):
        raise ValueError(f"{record_id}: expected_output.{field} must be a list")
    return value


def validate_record(record: dict[str, Any], source: Path, index: int) -> None:
    record_id = str(record.get("id") or f"{source.name}:{index}")

    input_data = record.get("input")
    if not isinstance(input_data, dict):
        raise ValueError(f"{record_id}: input must exist and be an object")

    missing_input_fields = sorted(REQUIRED_INPUT_FIELDS - set(input_data))
    if missing_input_fields:
        joined = ", ".join(missing_input_fields)
        raise ValueError(f"{record_id}: missing required input fields: {joined}")

    expected_output = record.get("expected_output")
    if not isinstance(expected_output, dict):
        raise ValueError(f"{record_id}: expected_output must exist and be an object")

    risk_labels = require_list(record_id, expected_output, "risk_labels")
    invalid_risks = sorted({label for label in risk_labels if label not in ALLOWED_RISK_LABELS})
    if invalid_risks:
        raise ValueError(f"{record_id}: invalid risk_labels: {', '.join(invalid_risks)}")

    blocked_actions = require_list(record_id, expected_output, "blocked_actions")
    invalid_actions = sorted(
        {action for action in blocked_actions if action not in ALLOWED_BLOCKED_ACTIONS}
    )
    if invalid_actions:
        raise ValueError(f"{record_id}: invalid blocked_actions: {', '.join(invalid_actions)}")

    require_list(record_id, expected_output, "missing_data")
    require_list(record_id, expected_output, "safe_next_checks")

    if not isinstance(expected_output.get("human_review_required"), bool):
        raise ValueError(f"{record_id}: expected_output.human_review_required must be boolean")


def validate_file(path: Path) -> int:
    records = load_jsonl(path)
    for index, record in enumerate(records, start=1):
        validate_record(record, path, index)
    return len(records)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument(
        "--jsonl",
        action="append",
        type=Path,
        dest="jsonl_files",
        help="Additional or alternate JSONL file to validate. Can be passed more than once.",
    )
    args = parser.parse_args()

    if args.jsonl_files:
        files = args.jsonl_files
    else:
        data_dir = args.dataset_dir / "data"
        files = [data_dir / "samples.jsonl", data_dir / "eval_cases.jsonl", data_dir / "golden_eval.jsonl"]

    total = 0
    for path in files:
        if not path.exists():
            parser.error(f"required data file missing: {path}")
        count = validate_file(path)
        total += count
        print(f"OK {path}: {count} records")

    print(f"Validated {total} Pomona tomato risk records.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
