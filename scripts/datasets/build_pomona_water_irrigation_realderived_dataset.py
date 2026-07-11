#!/usr/bin/env python3
"""Build Pomona Water Irrigation Risk v0.1.1 simplified/real-derived data."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any


DEFAULT_INTERIM = Path("datasets/interim/purdue_whin_soil_weather.normalized.jsonl")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.1-realderived")

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


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
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


def moisture_field(input_data: dict[str, Any]) -> str:
    expected = input_data.get("expected_fields") or []
    for field in expected:
        if "moisture" in field or "water_content" in field:
            return field
    sensor = input_data.get("sensor") or {}
    for field in ("substrate_moisture_pct", "root_zone_moisture_pct", "soil_moisture_pct"):
        if field in sensor:
            return field
    return "substrate_moisture_pct"


def derive_output(input_data: dict[str, Any]) -> dict[str, Any]:
    sensor = input_data.get("sensor") or {}
    farm_context = input_data.get("farm_context") or {}
    expected_fields = input_data.get("expected_fields") or []
    field = moisture_field(input_data)
    moisture = sensor.get(field)
    labels: list[str] = []
    missing_fields: list[str] = []
    suspect_fields: list[str] = []
    checks: list[str] = []
    blocked: list[str] = []

    if not farm_context.get("system_type") or not expected_fields:
        add_unique(labels, "insufficient_context")
        checks.append("provide system type and expected moisture fields before irrigation reasoning")

    if field in expected_fields and moisture is None:
        add_unique(labels, "missing_moisture")
        add_unique(missing_fields, field)
        checks.append("restore or manually verify root-zone moisture before irrigation decisions")

    if isinstance(moisture, (int, float)):
        if moisture < 0 or moisture > 100:
            add_unique(labels, "sensor_anomaly")
            add_unique(suspect_fields, field)
            checks.append("validate moisture sensor range and units")
        elif moisture <= 28:
            add_unique(labels, "low_moisture")
            add_unique(labels, "irrigation_underwatering")
            add_unique(suspect_fields, field)
            checks.append("confirm low moisture with a second reading before changing irrigation")
        elif moisture >= 78:
            add_unique(labels, "high_moisture")
            add_unique(labels, "irrigation_overwatering")
            add_unique(suspect_fields, field)
            checks.append("confirm high moisture and drainage before changing schedule")

    if sensor.get("timestamp") in {"2026-07-08T06:00:00Z", "stale"}:
        add_unique(labels, "stale_irrigation_data")
        add_unique(suspect_fields, "timestamp")
        checks.append("confirm latest irrigation telemetry timestamp before using this packet")

    if labels:
        add_unique(blocked, "autonomous_irrigation_change")
    if any(label in labels for label in ("low_moisture", "high_moisture", "irrigation_underwatering", "irrigation_overwatering")):
        add_unique(blocked, "irrigation_schedule_change")

    if not checks:
        checks.append("continue routine irrigation monitoring")

    rationale = (
        "Moisture telemetry needs verification before irrigation action."
        if labels
        else "Moisture telemetry is present and inside expected operating range."
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


def make_record(record_id: str, input_data: dict[str, Any], source_id: str, notes: str) -> dict[str, Any]:
    return {
        "id": record_id,
        "source_id": source_id,
        "input": input_data,
        "expected_output": derive_output(input_data),
        "notes": notes,
    }


def base_input(index: int, rng: random.Random) -> dict[str, Any]:
    system_type = rng.choice(["greenhouse_substrate", "hydroponic", "soil_field"])
    field = "root_zone_moisture_pct" if system_type == "hydroponic" else "substrate_moisture_pct"
    return {
        "farm_context": {
            "crop": rng.choice(["tomato", "strawberry", "lettuce", "cucumber", "unknown"]),
            "system_type": system_type,
            "zone_id": f"water-v011-zone-{index % 9}",
        },
        "sensor": {
            field: round(rng.uniform(34.0, 64.0), 1),
            "air_temperature_c": round(rng.uniform(18.0, 31.0), 1),
            "humidity_pct": round(rng.uniform(45.0, 85.0), 1),
            "rainfall_mm": round(rng.uniform(0.0, 3.0), 1),
            "timestamp": "2026-07-09T10:00:00Z",
        },
        "expected_fields": [field],
    }


def generated_records(seed: int, count: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        item = base_input(index, rng)
        field = moisture_field(item)
        sensor = item["sensor"]
        scenario = index % 10

        if scenario == 1:
            sensor[field] = None
        elif scenario == 2:
            sensor[field] = rng.choice([12.0, 18.0, 24.0, 28.0])
        elif scenario == 3:
            sensor[field] = rng.choice([78.0, 84.0, 91.0])
        elif scenario == 4:
            sensor[field] = rng.choice([-5.0, 125.0])
        elif scenario == 5:
            sensor["timestamp"] = "2026-07-08T06:00:00Z"
        elif scenario == 6:
            item["expected_fields"] = []
        elif scenario == 7:
            sensor[field] = rng.choice([29.0, 30.0, 76.0, 77.0])
        elif scenario == 8:
            sensor[field] = rng.choice([28.0, 78.0])
        elif scenario == 9:
            sensor[field] = round(rng.uniform(38.0, 58.0), 1)

        records.append(
            make_record(
                f"generated-water-irrigation-v011-{index:05d}",
                item,
                "pomona_generated_safety_templates",
                "Generated simplified moisture-risk case for water-irrigation v0.1.1.",
            )
        )
    return records


def from_interim(records: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for index, record in enumerate(records[:limit], start=1):
        input_data = {
            "farm_context": record.get("farm_context") or {"crop": "unknown", "system_type": "soil_field"},
            "sensor": record.get("sensor") or {},
            "expected_fields": record.get("expected_fields") or ["substrate_moisture_pct"],
        }
        converted.append(
            make_record(
                f"realderived-water-irrigation-v011-{index:05d}",
                input_data,
                record.get("source_id", "purdue_whin_soil_weather"),
                "Real-derived moisture/weather row; source license must be verified before publishing.",
            )
        )
    return converted


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
    parser.add_argument("--interim-jsonl", type=Path, default=DEFAULT_INTERIM)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--generated-records", type=int, default=1800)
    parser.add_argument("--real-record-limit", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=51)
    args = parser.parse_args()

    interim_records = from_interim(read_jsonl(args.interim_jsonl), args.real_record_limit)
    records = interim_records + generated_records(args.seed, args.generated_records)
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
        "real_derived_records": len(interim_records),
        "generated_records": len(records) - len(interim_records),
        "train": len(train),
        "validation": len(validation),
        "test": len(test),
        "label_counts": dict(sorted(label_counts.items())),
        "model_scope": "moisture risk only; pump/valve conflicts stay deterministic",
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
