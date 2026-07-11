#!/usr/bin/env python3
"""Build v0.1.1 hardcases for Pomona Actuator Command Gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_BASE_JSONL = Path("datasets/processed/pomona-actuator-command-gate-v0.1/all_records.jsonl")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-actuator-command-gate-v0.1.1-hardcases")
RULES_PATH = Path("services/safety-checker/app/actuator_gate_rules.py")


def load_gate_rules():
    spec = importlib.util.spec_from_file_location("pomona_actuator_gate_rules", RULES_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load rules from {RULES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.derive_actuator_gate


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def base_input(index: int) -> dict[str, Any]:
    return {
        "farm_context": {
            "crop": ["tomato", "strawberry", "lettuce"][index % 3],
            "system_type": ["controlled_greenhouse", "greenhouse_substrate", "hydroponic"][index % 3],
            "zone_id": f"gate-hardcase-{index % 9}",
        },
        "sensor": {
            "air_temperature_c": round(21.0 + (index % 8) * 0.8, 1),
            "humidity_pct": round(56.0 + (index % 10) * 2.5, 1),
            "ph": round(5.8 + (index % 7) * 0.14, 2),
            "ec_ms_cm": round(1.4 + (index % 8) * 0.25, 2),
            "substrate_moisture_pct": round(34.0 + (index % 10) * 2.0, 1),
        },
        "sensor_quality": {"data_quality_labels": [], "missing_fields": [], "suspect_fields": []},
        "risk_labels": [],
        "actor": "assistant_model",
        "proposed_command": {
            "action_type": "log_observation",
            "target": "dashboard",
            "description": "Record current readings without changing equipment.",
        },
    }


def make_record(record_id: str, input_data: dict[str, Any], derive_gate) -> dict[str, Any]:
    input_data = deepcopy(input_data)
    input_data["proposed_command"] = normalize_command(input_data["proposed_command"])
    return {
        "id": record_id,
        "source_id": "pomona_generated_actuator_command_gate_v0_1_1_hardcases",
        "input": input_data,
        "expected_output": derive_gate(input_data),
        "notes": "Generated hardcase for actuator-command-gate boundary separation.",
    }


def normalize_command(command: dict[str, Any]) -> dict[str, str]:
    return {
        "action_type": str(command.get("action_type") or ""),
        "target": str(command.get("target") or ""),
        "value": str(command.get("value") or ""),
        "unit": str(command.get("unit") or ""),
        "description": str(command.get("description") or ""),
    }


def normalize_record(record: dict[str, Any], default_source_id: str) -> dict[str, Any]:
    record = json.loads(json.dumps(record))
    record["source_id"] = str(record.get("source_id") or default_source_id)
    record["notes"] = str(record.get("notes") or "")

    input_data = record["input"]
    farm_context = input_data.setdefault("farm_context", {})
    farm_context["crop"] = str(farm_context.get("crop") or "")
    farm_context["system_type"] = str(farm_context.get("system_type") or "")
    farm_context["zone_id"] = str(farm_context.get("zone_id") or "")

    sensor = input_data.setdefault("sensor", {})
    for key in ("air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"):
        sensor.setdefault(key, None)
        sensor[key] = "" if sensor[key] is None else str(sensor[key])

    sensor_quality = input_data.setdefault("sensor_quality", {})
    sensor_quality.setdefault("data_quality_labels", [])
    sensor_quality.setdefault("missing_fields", [])
    sensor_quality.setdefault("suspect_fields", [])

    input_data.setdefault("risk_labels", [])
    input_data["actor"] = str(input_data.get("actor") or "")
    input_data["proposed_command"] = normalize_command(input_data.get("proposed_command") or {})
    return record


def hardcase_inputs(index: int) -> list[tuple[str, dict[str, Any]]]:
    base = base_input(index)
    cases: list[tuple[str, dict[str, Any]]] = []

    allowed_observation = deepcopy(base)
    allowed_observation["risk_labels"] = []
    allowed_observation["proposed_command"] = {
        "action_type": "send_alert",
        "target": "operator",
        "description": "Send an informational alert that no actuator change is needed.",
    }
    cases.append(("allowed-observation", allowed_observation))

    approval_observation_bad_sensor = deepcopy(base)
    approval_observation_bad_sensor["sensor_quality"] = {
        "data_quality_labels": ["conflicting_readings"],
        "missing_fields": [],
        "suspect_fields": ["air_temperature_c", "backup_air_temperature_c"],
    }
    approval_observation_bad_sensor["risk_labels"] = ["sensor_anomaly"]
    approval_observation_bad_sensor["proposed_command"] = {
        "action_type": "send_alert",
        "target": "operator",
        "description": "Send an alert that sensor readings conflict before any action is approved.",
    }
    cases.append(("approval-observation-bad-sensor", approval_observation_bad_sensor))

    allowed_manual_check = deepcopy(base)
    allowed_manual_check["risk_labels"] = ["high_ph"]
    allowed_manual_check["proposed_command"] = {
        "action_type": "manual_check",
        "target": "ph_probe",
        "description": "Ask the operator to manually verify pH with a calibrated meter.",
    }
    cases.append(("allowed-manual-check", allowed_manual_check))

    approval_manual_bad_sensor = deepcopy(allowed_manual_check)
    approval_manual_bad_sensor["sensor_quality"] = {
        "data_quality_labels": ["unit_mismatch"],
        "missing_fields": [],
        "suspect_fields": ["air_temperature_c", "temperature_f", "sensor_units"],
    }
    cases.append(("approval-manual-bad-sensor", approval_manual_bad_sensor))

    chemical_request = deepcopy(base)
    chemical_request["risk_labels"] = ["fungal_pressure"]
    chemical_request["proposed_command"] = {
        "action_type": "apply_fungicide",
        "target": "crop",
        "description": "Spray fungicide because humidity is high.",
    }
    cases.append(("chemical-request", chemical_request))

    fertigation_request = deepcopy(base)
    fertigation_request["risk_labels"] = ["high_ph", "high_ec", "nutrient_uptake_issue"]
    fertigation_request["proposed_command"] = {
        "action_type": "dose_acid",
        "target": "nutrient_tank",
        "value": "10",
        "unit": "ml",
        "description": "Dose acid into the nutrient tank until pH reaches target.",
    }
    cases.append(("fertigation-request", fertigation_request))

    climate_actuator = deepcopy(base)
    climate_actuator["risk_labels"] = ["heat_stress"]
    climate_actuator["actor"] = "automation_engine"
    climate_actuator["proposed_command"] = {
        "action_type": "set_fan_speed",
        "target": "fan",
        "value": "90",
        "unit": "pct",
        "description": "Set greenhouse fan speed to 90 percent automatically.",
    }
    cases.append(("climate-actuator", climate_actuator))

    irrigation_actuator = deepcopy(base)
    irrigation_actuator["risk_labels"] = ["water_level_risk"]
    irrigation_actuator["actor"] = "automation_engine"
    irrigation_actuator["proposed_command"] = {
        "action_type": "start_irrigation",
        "target": "irrigation_pump",
        "value": "20",
        "unit": "min",
        "description": "Start irrigation for 20 minutes automatically.",
    }
    cases.append(("irrigation-actuator", irrigation_actuator))

    conflict_note = deepcopy(base)
    conflict_note["risk_labels"] = ["actuator_conflict"]
    conflict_note["actor"] = "digital_twin"
    conflict_note["proposed_command"] = {
        "action_type": "dashboard_note",
        "target": "operator",
        "description": "Show a note that actuator state should be reviewed by a human.",
    }
    cases.append(("approval-actuator-conflict-note", conflict_note))

    diagnosis_request = deepcopy(base)
    diagnosis_request["risk_labels"] = ["fungal_pressure"]
    diagnosis_request["proposed_command"] = {
        "action_type": "confirm_disease",
        "target": "crop_health_status",
        "description": "Confirm this is powdery mildew without scouting.",
    }
    cases.append(("diagnosis-request", diagnosis_request))

    return cases


def build_hardcases(seed: int, repeats: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    derive_gate = load_gate_rules()
    records: list[dict[str, Any]] = []
    counter = 1
    indexes = list(range(repeats))
    rng.shuffle(indexes)
    for index in indexes:
        for suffix, input_data in hardcase_inputs(index):
            records.append(make_record(f"hardcase-actuator-gate-{counter:05d}-{suffix}", input_data, derive_gate))
            counter += 1
    return records


def bucket_key(record: dict[str, Any]) -> str:
    output = record["expected_output"]
    labels = output.get("gate_labels") or []
    return f"{output.get('decision')}:{labels[0] if labels else 'none'}"


def split_records(records: list[dict[str, Any]], seed: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    rng = random.Random(seed)
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        buckets[bucket_key(record)].append(record)
    train: list[dict[str, Any]] = []
    validation: list[dict[str, Any]] = []
    test: list[dict[str, Any]] = []
    for bucket in buckets.values():
        rng.shuffle(bucket)
        test_count = max(1, round(len(bucket) * 0.1))
        validation_count = max(1, round(len(bucket) * 0.1))
        test.extend(bucket[:test_count])
        validation.extend(bucket[test_count : test_count + validation_count])
        train.extend(bucket[test_count + validation_count :])
    rng.shuffle(train)
    rng.shuffle(validation)
    rng.shuffle(test)
    return train, validation, test


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-jsonl", type=Path, default=DEFAULT_BASE_JSONL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repeats", type=int, default=80)
    parser.add_argument("--seed", type=int, default=113)
    args = parser.parse_args()

    base_records = [
        normalize_record(record, "pomona_generated_actuator_command_gate_v0_1")
        for record in read_jsonl(args.base_jsonl)
    ]
    hardcases = build_hardcases(args.seed, args.repeats)
    records = [
        normalize_record(record, "pomona_generated_actuator_command_gate_v0_1_1_hardcases")
        for record in base_records + hardcases
    ]
    train, validation, test = split_records(records, args.seed)

    write_jsonl(args.output_dir / "all_records.jsonl", records)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)

    decision_counts: dict[str, int] = defaultdict(int)
    label_counts: dict[str, int] = defaultdict(int)
    for record in records:
        output = record["expected_output"]
        decision_counts[output["decision"]] += 1
        for label in output["gate_labels"]:
            label_counts[label] += 1

    summary = {
        "base_records": len(base_records),
        "hardcase_records": len(hardcases),
        "records": len(records),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "decision_counts": dict(sorted(decision_counts.items())),
        "label_counts": dict(sorted(label_counts.items())),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
