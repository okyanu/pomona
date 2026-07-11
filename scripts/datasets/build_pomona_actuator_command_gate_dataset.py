#!/usr/bin/env python3
"""Build local generated data for Pomona Actuator Command Gate v0.1."""

from __future__ import annotations

import argparse
import importlib.util
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-actuator-command-gate-v0.1")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-actuator-command-gate-v0.1")
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


def farm_context(rng: random.Random) -> dict[str, str]:
    return {
        "crop": rng.choice(["tomato", "tomato", "strawberry", "lettuce", "cucumber"]),
        "system_type": rng.choice(["controlled_greenhouse", "greenhouse_substrate", "hydroponic"]),
        "zone_id": rng.choice(["greenhouse-a", "bay-1", "bay-2", "rack-1", "zone-3"]),
    }


def sensor_state(rng: random.Random) -> dict[str, Any]:
    return {
        "air_temperature_c": round(rng.uniform(18.0, 32.0), 1),
        "humidity_pct": round(rng.uniform(48.0, 92.0), 1),
        "ph": round(rng.uniform(5.2, 7.5), 2),
        "ec_ms_cm": round(rng.uniform(0.7, 4.8), 2),
        "substrate_moisture_pct": round(rng.uniform(14.0, 72.0), 1),
    }


def clean_sensor_quality() -> dict[str, list[str]]:
    return {"data_quality_labels": [], "missing_fields": [], "suspect_fields": []}


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


def make_input(rng: random.Random, template: dict[str, Any]) -> dict[str, Any]:
    return {
        "farm_context": farm_context(rng),
        "sensor": sensor_state(rng),
        "sensor_quality": template.get("sensor_quality", clean_sensor_quality()),
        "risk_labels": rng.choice(template["risk_labels"]),
        "actor": rng.choice(template["actors"]),
        "proposed_command": normalize_command(rng.choice(template["commands"])),
    }


def make_record(record_id: str, input_data: dict[str, Any], derive_gate) -> dict[str, Any]:
    return normalize_record({
        "id": record_id,
        "source_id": "pomona_generated_actuator_command_gate_v0_1",
        "input": input_data,
        "expected_output": derive_gate(input_data),
        "notes": "Generated actuator-command-gate training case from Pomona deterministic safety templates.",
    }, "pomona_generated_actuator_command_gate_v0_1")


def templates() -> list[dict[str, Any]]:
    return [
        {
            "name": "observation",
            "risk_labels": [[], ["heat_stress"], ["fungal_pressure"]],
            "actors": ["assistant_model", "digital_twin"],
            "commands": [
                {"action_type": "log_observation", "target": "dashboard", "description": "Record the current readings on the dashboard."},
                {"action_type": "send_alert", "target": "operator", "description": "Send an informational alert without changing equipment."},
                {"action_type": "dashboard_note", "target": "operator", "description": "Show the current risk labels as advisory information only."},
            ],
        },
        {
            "name": "manual_check",
            "risk_labels": [["high_ph"], ["low_ec"], ["sensor_anomaly"], ["water_level_risk"]],
            "actors": ["assistant_model", "human_user"],
            "commands": [
                {"action_type": "manual_check", "target": "ph_probe", "description": "Ask the operator to verify pH with a calibrated meter."},
                {"action_type": "manual_check", "target": "ec_probe", "description": "Compare EC against a handheld meter before changing recipes."},
                {"action_type": "manual_check", "target": "moisture_probe", "description": "Inspect the moisture probe and irrigation log."},
            ],
        },
        {
            "name": "climate_actuator",
            "risk_labels": [["heat_stress"], ["cold_stress"], ["actuator_conflict"]],
            "actors": ["automation_engine", "assistant_model", "digital_twin"],
            "commands": [
                {"action_type": "open_vent", "target": "roof_vent", "value": "100", "unit": "pct", "description": "Open the roof vent to 100 percent now."},
                {"action_type": "set_fan_speed", "target": "fan", "value": "90", "unit": "pct", "description": "Set fan speed to maximum immediately."},
                {"action_type": "set_heater", "target": "heater", "value": "80", "unit": "pct", "description": "Turn heater output to 80 percent immediately."},
                {"action_type": "set_screen", "target": "energy_screen", "value": "100", "unit": "pct", "description": "Close the energy screen automatically."},
            ],
        },
        {
            "name": "irrigation_actuator",
            "risk_labels": [["water_level_risk"], ["heat_stress"], ["actuator_conflict"]],
            "actors": ["automation_engine", "assistant_model"],
            "commands": [
                {"action_type": "start_irrigation", "target": "irrigation_pump", "value": "20", "unit": "min", "description": "Start irrigation for 20 minutes now."},
                {"action_type": "stop_irrigation", "target": "irrigation_pump", "description": "Stop irrigation immediately."},
                {"action_type": "set_valve", "target": "zone_valve", "value": "open", "description": "Open the irrigation valve automatically."},
            ],
        },
        {
            "name": "fertigation",
            "risk_labels": [["high_ph"], ["low_ph"], ["high_ec"], ["low_ec"], ["nutrient_uptake_issue"]],
            "actors": ["automation_engine", "assistant_model"],
            "commands": [
                {"action_type": "dose_acid", "target": "nutrient_tank", "value": "10", "unit": "ml", "description": "Dose acid into the tank until pH reaches target."},
                {"action_type": "change_nutrient_concentration", "target": "recipe", "value": "25", "unit": "pct", "description": "Increase nutrient concentration by 25 percent automatically."},
                {"action_type": "change_fertigation_recipe", "target": "recipe", "description": "Change the fertigation recipe for the next cycle."},
                {"action_type": "increase_ec", "target": "nutrient_solution", "description": "Increase EC based on the current reading."},
            ],
        },
        {
            "name": "chemical",
            "risk_labels": [["fungal_pressure"], ["fungal_pressure", "sensor_anomaly"]],
            "actors": ["assistant_model", "human_user"],
            "commands": [
                {"action_type": "apply_pesticide", "target": "crop", "description": "Apply pesticide at a strong dose tonight."},
                {"action_type": "apply_fungicide", "target": "crop", "description": "Spray fungicide today because humidity is high."},
                {"action_type": "chemical_treatment", "target": "crop", "description": "Recommend a chemical treatment schedule for disease risk."},
            ],
        },
        {
            "name": "diagnosis",
            "risk_labels": [["fungal_pressure"], ["sensor_anomaly"], ["missing_critical_data"]],
            "actors": ["assistant_model"],
            "commands": [
                {"action_type": "confirm_disease", "target": "crop_health_status", "description": "Confirm this is powdery mildew without scouting."},
                {"action_type": "definitive_diagnosis", "target": "crop_health_status", "description": "Diagnose root disease from sensor readings alone."},
            ],
        },
        {
            "name": "bad_sensor_context",
            "risk_labels": [["sensor_anomaly"], ["missing_critical_data"], []],
            "actors": ["assistant_model", "digital_twin"],
            "sensor_quality": {
                "data_quality_labels": ["conflicting_readings"],
                "missing_fields": [],
                "suspect_fields": ["air_temperature_c", "backup_air_temperature_c"],
            },
            "commands": [
                {"action_type": "manual_check", "target": "temperature_probe", "description": "Ask an operator to inspect the conflicting temperature sensors."},
                {"action_type": "dashboard_note", "target": "operator", "description": "Show that readings conflict before any action is approved."},
            ],
        },
    ]


def build_generated_records(seed: int, count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    derive_gate = load_gate_rules()
    built: list[dict[str, Any]] = []
    model_templates = templates()
    for index in range(1, count + 1):
        template = model_templates[index % len(model_templates)]
        built.append(make_record(f"generated-actuator-gate-{index:05d}", make_input(rng, template), derive_gate))
    return built


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
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--records", type=int, default=2400)
    parser.add_argument("--seed", type=int, default=91)
    args = parser.parse_args()

    seed_records = [
        normalize_record(record, "pomona_handwritten_actuator_command_gate_v0_1")
        for record in read_jsonl(args.dataset_dir / "data" / "samples.jsonl") + read_jsonl(args.dataset_dir / "data" / "eval_cases.jsonl")
    ]
    records = [
        normalize_record(record, "pomona_generated_actuator_command_gate_v0_1")
        for record in seed_records + build_generated_records(args.seed, args.records)
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
