#!/usr/bin/env python3
"""Build a local generated dataset for Pomona Water Irrigation Risk Reasoner v0.1."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-water-irrigation-risk-v0.1")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def add_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)


def base_input(rng: random.Random) -> dict[str, Any]:
    system_type = rng.choice(["greenhouse_substrate", "hydroponic", "soil_field"])
    moisture_field = "root_zone_moisture_pct" if system_type == "hydroponic" else "substrate_moisture_pct"
    return {
        "farm_context": {
            "crop": rng.choice(["tomato", "strawberry", "lettuce", "cucumber"]),
            "system_type": system_type,
            "zone_id": rng.choice(["greenhouse-a", "bay-2", "rack-1", "zone-3"]),
        },
        "sensor": {
            "water_level_pct": round(rng.uniform(35.0, 85.0), 1),
            moisture_field: round(rng.uniform(34.0, 62.0), 1),
            "flow_l_min": round(rng.uniform(0.4, 2.2), 2),
            "timestamp": "2026-07-09T10:00:00Z",
        },
        "actuator_states": {
            "pump_on": rng.choice([False, True]),
            "irrigation_valve_open": rng.choice([False, True]),
        },
        "expected_fields": ["water_level_pct", moisture_field, "flow_l_min"],
    }


def derive_output(input_data: dict[str, Any]) -> dict[str, Any]:
    sensor = input_data["sensor"]
    states = input_data.get("actuator_states") or {}
    expected_fields = input_data.get("expected_fields") or []
    labels: list[str] = []
    missing_fields: list[str] = []
    suspect_fields: list[str] = []
    checks: list[str] = []
    blocked: list[str] = []

    if not input_data.get("farm_context", {}).get("crop") or not expected_fields:
        add_unique(labels, "insufficient_context")
        checks.append("provide crop, system type, and expected irrigation fields before classification")

    for field in expected_fields:
        if sensor.get(field) is None:
            add_unique(missing_fields, field)
            if field == "water_level_pct":
                add_unique(labels, "missing_water_level")
                checks.append("restore or manually verify water level before irrigation decisions")
            elif "moisture" in field:
                add_unique(labels, "missing_moisture")
                checks.append("restore or manually verify root-zone moisture before irrigation decisions")

    water_level = sensor.get("water_level_pct")
    flow = sensor.get("flow_l_min")
    moisture_field = next((field for field in expected_fields if "moisture" in field), "substrate_moisture_pct")
    moisture = sensor.get(moisture_field)
    pump_on = bool(states.get("pump_on"))
    valve_open = bool(states.get("irrigation_valve_open"))

    if isinstance(water_level, (int, float)):
        if water_level < 0 or water_level > 100:
            add_unique(labels, "sensor_anomaly")
            add_unique(suspect_fields, "water_level_pct")
            checks.append("validate water-level sensor range and units")
        elif water_level <= 15:
            add_unique(labels, "low_water_level")
            add_unique(suspect_fields, "water_level_pct")
            checks.append("verify reservoir level before changing irrigation")
        elif water_level >= 95:
            add_unique(labels, "high_water_level")
            add_unique(suspect_fields, "water_level_pct")
            checks.append("verify overflow, drainage, and reservoir sensor calibration")

    if isinstance(moisture, (int, float)):
        if moisture < 0 or moisture > 100:
            add_unique(labels, "sensor_anomaly")
            add_unique(suspect_fields, moisture_field)
            checks.append("validate moisture sensor range and units")
        elif moisture <= 28:
            add_unique(labels, "low_moisture")
            add_unique(labels, "irrigation_underwatering")
            add_unique(suspect_fields, moisture_field)
            checks.append("confirm low moisture with a second reading before changing irrigation")
        elif moisture >= 78:
            add_unique(labels, "high_moisture")
            add_unique(labels, "irrigation_overwatering")
            add_unique(suspect_fields, moisture_field)
            checks.append("confirm moisture with a second reading before changing schedule")

    if isinstance(flow, (int, float)):
        if flow < 0 or flow > 20:
            add_unique(labels, "sensor_anomaly")
            add_unique(suspect_fields, "flow_l_min")
            checks.append("validate flow sensor range and units")
        elif pump_on and valve_open and flow <= 0.05:
            add_unique(labels, "pump_flow_anomaly")
            add_unique(suspect_fields, "flow_l_min")
            checks.append("inspect pump, filter, and flow sensor before increasing irrigation")
        elif not pump_on and not valve_open and flow >= 0.5:
            add_unique(labels, "valve_state_conflict")
            add_unique(suspect_fields, "flow_l_min")
            add_unique(suspect_fields, "pump_on")
            add_unique(suspect_fields, "irrigation_valve_open")
            checks.append("inspect valve and flow sensor state before allowing irrigation changes")

    if sensor.get("timestamp") == "2026-07-08T06:00:00Z":
        add_unique(labels, "stale_irrigation_data")
        add_unique(suspect_fields, "timestamp")
        checks.append("confirm latest irrigation telemetry timestamp before using this packet")

    if labels:
        add_unique(blocked, "autonomous_irrigation_change")
    if any(label in labels for label in ("low_moisture", "high_moisture", "irrigation_underwatering", "irrigation_overwatering")):
        add_unique(blocked, "irrigation_schedule_change")
    if any(label in labels for label in ("pump_flow_anomaly", "valve_state_conflict")):
        add_unique(blocked, "direct_pump_control")
        add_unique(blocked, "direct_valve_control")

    if not checks:
        checks.append("continue routine irrigation monitoring")
    rationale = (
        "Water and irrigation telemetry needs verification before action."
        if labels
        else "Water and moisture readings are present and inside expected operating ranges."
    )
    return {
        "irrigation_risk_labels": labels,
        "missing_fields": missing_fields,
        "suspect_fields": suspect_fields,
        "safe_next_checks": checks,
        "blocked_actions": blocked,
        "human_review_required": bool(labels or missing_fields or suspect_fields),
        "rationale": rationale,
    }


def make_record(record_id: str, input_data: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": record_id,
        "source_id": "pomona_generated_water_irrigation_v0_1",
        "input": input_data,
        "expected_output": derive_output(input_data),
        "notes": "Generated water-irrigation training case from Pomona rule templates.",
    }


def generated_records(seed: int, count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        item = base_input(rng)
        sensor = item["sensor"]
        states = item["actuator_states"]
        moisture_field = next(field for field in item["expected_fields"] if "moisture" in field)
        scenario = index % 14

        if scenario == 1:
            sensor["water_level_pct"] = None
        elif scenario == 2:
            sensor[moisture_field] = None
        elif scenario == 3:
            sensor["water_level_pct"] = rng.choice([3.0, 8.0, 14.0])
        elif scenario == 4:
            sensor["water_level_pct"] = rng.choice([96.0, 99.0, 100.0])
        elif scenario == 5:
            sensor[moisture_field] = rng.choice([16.0, 22.0, 27.0])
        elif scenario == 6:
            sensor[moisture_field] = rng.choice([79.0, 84.0, 91.0])
        elif scenario == 7:
            sensor["water_level_pct"] = rng.choice([-5.0, 120.0, 145.0])
        elif scenario == 8:
            sensor[moisture_field] = rng.choice([-2.0, 118.0])
        elif scenario == 9:
            sensor["flow_l_min"] = 0.0
            states["pump_on"] = True
            states["irrigation_valve_open"] = True
        elif scenario == 10:
            sensor["flow_l_min"] = rng.choice([1.3, 2.4, 3.8])
            states["pump_on"] = False
            states["irrigation_valve_open"] = False
        elif scenario == 11:
            sensor["timestamp"] = "2026-07-08T06:00:00Z"
        elif scenario == 12:
            item["expected_fields"] = []
        elif scenario == 13:
            sensor["water_level_pct"] = 9.0
            sensor[moisture_field] = 22.0
            sensor["flow_l_min"] = 0.0
            states["pump_on"] = True
            states["irrigation_valve_open"] = True

        records.append(make_record(f"generated-water-irrigation-{index:05d}", item))
    return records


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("irrigation_risk_labels") or []
    return labels[0] if labels else "normal"


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
        test_count = round(len(bucket) * 0.1)
        validation_count = round(len(bucket) * 0.1)
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
    parser.add_argument("--records", type=int, default=2100)
    parser.add_argument("--seed", type=int, default=47)
    args = parser.parse_args()

    seed_records = read_jsonl(args.dataset_dir / "data" / "samples.jsonl") + read_jsonl(args.dataset_dir / "data" / "eval_cases.jsonl")
    records = seed_records + generated_records(args.seed, args.records)
    train, validation, test = split_records(records, args.seed)

    write_jsonl(args.output_dir / "all_records.jsonl", records)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)

    label_counts: dict[str, int] = defaultdict(int)
    for record in records:
        labels = record["expected_output"]["irrigation_risk_labels"]
        label_counts[labels[0] if labels else "normal"] += 1
    summary = {
        "records": len(records),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "label_counts": dict(sorted(label_counts.items())),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
