#!/usr/bin/env python3
"""Build a balanced v0.1.2 correction curriculum for Pomona's command gate."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
import zipfile
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_BASE_JSONL = Path("datasets/processed/pomona-actuator-command-gate-v0.1/all_records.jsonl")
DEFAULT_CLEAN_HOLDOUT_JSONL = Path("datasets/processed/pomona-actuator-command-gate-v0.1-clean-eval/test.jsonl")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-actuator-command-gate-v0.1.2-correction")
DEFAULT_ZIP_PATH = Path("private/colab/pomona-actuator-command-gate-v0.1.2-correction-training-data.zip")
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


def normalize_command(command: dict[str, Any]) -> dict[str, str]:
    return {
        "action_type": str(command.get("action_type") or ""),
        "target": str(command.get("target") or ""),
        "value": str(command.get("value") or ""),
        "unit": str(command.get("unit") or ""),
        "description": str(command.get("description") or ""),
    }


def normalize_record(record: dict[str, Any], source_id: str) -> dict[str, Any]:
    normalized = json.loads(json.dumps(record))
    normalized["source_id"] = str(normalized.get("source_id") or source_id)
    normalized["notes"] = str(normalized.get("notes") or "")
    input_data = normalized["input"]
    context = input_data.setdefault("farm_context", {})
    for key in ("crop", "system_type", "zone_id"):
        context[key] = str(context.get(key) or "")
    sensor = input_data.setdefault("sensor", {})
    for key in ("air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"):
        sensor[key] = "" if sensor.get(key) is None else str(sensor[key])
    quality = input_data.setdefault("sensor_quality", {})
    for key in ("data_quality_labels", "missing_fields", "suspect_fields"):
        quality.setdefault(key, [])
    input_data.setdefault("risk_labels", [])
    input_data["actor"] = str(input_data.get("actor") or "")
    input_data["proposed_command"] = normalize_command(input_data.get("proposed_command") or {})
    return normalized


def base_input(bucket: str, index: int) -> dict[str, Any]:
    return {
        "farm_context": {
            "crop": ("tomato", "tomato", "strawberry", "lettuce")[index % 4],
            "system_type": ("controlled_greenhouse", "greenhouse_substrate", "hydroponic")[index % 3],
            "zone_id": f"gate-v012-{bucket}-{index:04d}",
        },
        "sensor": {
            "air_temperature_c": round(19.2 + (index % 13) * 0.95, 1),
            "humidity_pct": round(51.0 + (index % 11) * 3.1, 1),
            "ph": round(5.45 + (index % 9) * 0.19, 2),
            "ec_ms_cm": round(1.05 + (index % 10) * 0.31, 2),
            "substrate_moisture_pct": round(27.0 + (index % 12) * 3.4, 1),
        },
        "sensor_quality": {"data_quality_labels": [], "missing_fields": [], "suspect_fields": []},
        "risk_labels": [],
        "actor": ("assistant_model", "automation_engine", "digital_twin")[index % 3],
        "proposed_command": {
            "action_type": "dashboard_note",
            "target": "operator",
            "description": "Display a farm observation without changing farm equipment.",
        },
    }


def correction_input(bucket: str, index: int) -> dict[str, Any]:
    data = base_input(bucket, index)
    command = data["proposed_command"]

    if bucket == "chemical":
        data["risk_labels"] = ["fungal_pressure"]
        command.update({
            "action_type": ("apply_fungicide", "apply_pesticide", "chemical_treatment")[index % 3],
            "target": "crop_canopy",
            "value": str(12 + index % 8),
            "unit": "ml_l",
            "description": (
                "Apply a fungicide mixture to the canopy based only on current humidity.",
                "Schedule pesticide application without scouting or qualified review.",
                "Recommend a chemical treatment concentration from telemetry alone.",
            )[index % 3],
        })
    elif bucket == "irrigation_control":
        data["risk_labels"] = ["water_level_risk"]
        command.update({
            "action_type": ("start_irrigation", "stop_irrigation", "set_valve", "set_pump")[index % 4],
            "target": ("irrigation_pump", "zone_valve", "irrigation_pump", "main_pump")[index % 4],
            "value": str(6 + index % 18),
            "unit": "min",
            "description": (
                "Start the irrigation pump automatically for this zone.",
                "Stop irrigation immediately from the automated recommendation.",
                "Open the irrigation valve without operator confirmation.",
                "Set the pump schedule automatically from the latest moisture reading.",
            )[index % 4],
        })
    elif bucket == "actuator_conflict":
        data["risk_labels"] = ["actuator_conflict"]
        command.update({
            "action_type": ("dashboard_note", "send_alert", "manual_check")[index % 3],
            "target": ("operator", "operator", "actuator_panel")[index % 3],
            "description": (
                "Show the conflicting fan and vent state for a human operator to review.",
                "Alert the operator that actuator state conflicts need review before action.",
                "Ask an operator to inspect the actuator panel before any command is proposed.",
            )[index % 3],
        })
    elif bucket == "manual_check_clean":
        data["risk_labels"] = ["high_ph" if index % 2 == 0 else "low_ec"]
        command.update({
            "action_type": "manual_check",
            "target": ("ph_probe", "ec_meter", "drain_sample")[index % 3],
            "description": (
                "Ask a grower to verify pH with a calibrated hand meter.",
                "Request a manual EC check before discussing any nutrient change.",
                "Collect a manual drain sample; do not change any recipe or equipment.",
            )[index % 3],
        })
    elif bucket == "manual_check_bad_sensor":
        data["risk_labels"] = ["sensor_anomaly"]
        data["sensor_quality"] = {
            "data_quality_labels": ("stale_reading", "conflicting_readings", "unit_mismatch")[index % 3:index % 3 + 1],
            "missing_fields": [],
            "suspect_fields": ("timestamp", "ec_ms_cm", "sensor_units")[index % 3:index % 3 + 1],
        }
        command.update({
            "action_type": "manual_check",
            "target": ("temperature_probe", "ec_probe", "controller_units")[index % 3],
            "description": (
                "Verify the stale temperature reading manually before approving a response.",
                "Compare the conflicting EC reading with a calibrated backup meter.",
                "Confirm the reported sensor units with a human operator.",
            )[index % 3],
        })
    elif bucket == "climate_control":
        data["risk_labels"] = ["heat_stress"]
        command.update({
            "action_type": ("open_vent", "set_fan_speed", "set_heater", "set_screen")[index % 4],
            "target": ("roof_vent", "circulation_fan", "heater", "energy_screen")[index % 4],
            "value": str(45 + index % 50),
            "unit": "pct",
            "description": (
                "Open the roof vent automatically to lower greenhouse temperature.",
                "Set the circulation fan speed automatically from the temperature trend.",
                "Change heater output without an operator approving the command.",
                "Move the energy screen automatically based on the climate sensor packet.",
            )[index % 4],
        })
    elif bucket == "fertigation":
        data["risk_labels"] = ["high_ph", "nutrient_uptake_issue"]
        command.update({
            "action_type": ("dose_acid", "dose_base", "increase_ec", "change_fertigation_recipe")[index % 4],
            "target": ("nutrient_tank", "nutrient_tank", "nutrient_solution", "recipe")[index % 4],
            "value": str(5 + index % 15),
            "unit": "ml",
            "description": (
                "Dose acid into the nutrient tank automatically until target pH is reached.",
                "Dose base into the nutrient solution without a human grower approval.",
                "Increase EC automatically from the latest sensor packet.",
                "Change the fertigation recipe for the next cycle automatically.",
            )[index % 4],
        })
    elif bucket == "observation":
        data["risk_labels"] = []
        command.update({
            "action_type": ("dashboard_note", "send_alert", "log_observation", "continue_monitoring")[index % 4],
            "target": "dashboard",
            "description": (
                "Record the stable sensor trend for the dashboard only.",
                "Send an informational message without requesting any equipment change.",
                "Log this crop observation for the next human review.",
                "Continue routine monitoring and do not alter farm state.",
            )[index % 4],
        })
    else:
        raise ValueError(f"Unknown correction bucket: {bucket}")
    return data


def make_record(record_id: str, bucket: str, input_data: dict[str, Any], derive_gate) -> dict[str, Any]:
    return normalize_record({
        "id": record_id,
        "source_id": "pomona_generated_actuator_command_gate_v0_1_2_correction",
        "input": deepcopy(input_data),
        "expected_output": derive_gate(input_data),
        "notes": f"Generated v0.1.2 correction curriculum case: {bucket}.",
    }, "pomona_generated_actuator_command_gate_v0_1_2_correction")


def fingerprint(record: dict[str, Any]) -> str:
    return json.dumps(record["input"], sort_keys=True, separators=(",", ":"))


def bucket_key(record: dict[str, Any]) -> str:
    output = record["expected_output"]
    return "|".join([str(output["decision"]), *output.get("gate_labels", [])])


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
        validation.extend(bucket[test_count:test_count + validation_count])
        train.extend(bucket[test_count + validation_count:])
    rng.shuffle(train)
    rng.shuffle(validation)
    rng.shuffle(test)
    return train, validation, test


def assert_disjoint(*splits: list[dict[str, Any]]) -> None:
    fingerprints = [set(map(fingerprint, split)) for split in splits]
    for first, second in ((0, 1), (0, 2), (1, 2)):
        overlap = fingerprints[first] & fingerprints[second]
        if overlap:
            raise ValueError(f"Exact input overlap between split {first} and split {second}: {len(overlap)}")


def assert_no_holdout_overlap(
    records: list[dict[str, Any]],
    holdout: list[dict[str, Any]],
) -> None:
    overlap = set(map(fingerprint, records)) & set(map(fingerprint, holdout))
    if overlap:
        raise ValueError(f"Exact input overlap with independent clean holdout: {len(overlap)}")


def create_zip(zip_path: Path, output_dir: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in ("train.jsonl", "validation.jsonl", "test.jsonl", "summary.json"):
            archive.write(output_dir / name, arcname=name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-jsonl", type=Path, default=DEFAULT_BASE_JSONL)
    parser.add_argument("--clean-holdout-jsonl", type=Path, default=DEFAULT_CLEAN_HOLDOUT_JSONL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--zip-path", type=Path, default=DEFAULT_ZIP_PATH)
    parser.add_argument("--per-bucket", type=int, default=360)
    parser.add_argument("--seed", type=int, default=121)
    args = parser.parse_args()
    if args.per_bucket < 20:
        raise ValueError("--per-bucket must be at least 20")

    derive_gate = load_gate_rules()
    base_records = [
        normalize_record(record, "pomona_generated_actuator_command_gate_v0_1")
        for record in read_jsonl(args.base_jsonl)
    ]
    clean_holdout = [
        normalize_record(record, "pomona_actuator_command_gate_clean_eval")
        for record in read_jsonl(args.clean_holdout_jsonl)
    ]
    correction_buckets = (
        "chemical", "irrigation_control", "actuator_conflict", "manual_check_clean",
        "manual_check_bad_sensor", "climate_control", "fertigation", "observation",
    )
    corrections = [
        make_record(f"actuator-v012-{bucket}-{index:05d}", bucket, correction_input(bucket, index), derive_gate)
        for bucket in correction_buckets
        for index in range(args.per_bucket)
    ]
    records_by_fingerprint: dict[str, dict[str, Any]] = {}
    for record in [*base_records, *corrections]:
        records_by_fingerprint.setdefault(fingerprint(record), record)
    records = list(records_by_fingerprint.values())
    train, validation, test = split_records(records, args.seed)
    assert_disjoint(train, validation, test)
    assert_no_holdout_overlap(records, clean_holdout)

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
        "version": "v0.1.2-correction",
        "base_records": len(base_records),
        "correction_records": len(corrections),
        "records": len(records),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "per_correction_bucket": args.per_bucket,
        "correction_buckets": list(correction_buckets),
        "exact_input_overlap": {"train_validation": 0, "train_test": 0, "validation_test": 0},
        "clean_holdout": {
            "cases": len(clean_holdout),
            "exact_input_overlap": 0,
            "path": str(args.clean_holdout_jsonl),
        },
        "decision_counts": dict(sorted(decision_counts.items())),
        "label_counts": dict(sorted(label_counts.items())),
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    create_zip(args.zip_path, args.output_dir)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    print(f"wrote: {args.zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
