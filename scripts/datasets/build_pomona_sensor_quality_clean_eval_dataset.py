#!/usr/bin/env python3
"""Build an independent clean holdout for the sensor-quality adapter."""

from __future__ import annotations

import argparse
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-sensor-quality-v0.1.1-clean-eval")
RULES_PATH = Path("services/model-router/app/sensor_quality.py")
NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def load_rules():
    spec = importlib.util.spec_from_file_location("pomona_sensor_quality_rules", RULES_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load rules from {RULES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.derive_sensor_quality


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def make_input(bucket: str, index: int) -> dict[str, Any]:
    sensor: dict[str, Any] = {
        "air_temperature_c": round(19.3 + (index % 11) * 0.83, 1),
        "humidity_pct": round(47.5 + (index % 10) * 3.7, 1),
        "ph": round(5.55 + (index % 9) * 0.13, 2),
        "ec_ms_cm": round(1.15 + (index % 8) * 0.27, 2),
        "substrate_moisture_pct": round(33.5 + (index % 12) * 2.3, 1),
        "timestamp": "2026-07-10T11:40:00Z",
    }
    expected_fields = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
    context = {
        "crop": ("tomato", "strawberry", "lettuce", "cucumber")[index % 4],
        "system_type": "controlled_greenhouse",
        "zone_id": f"sensor-clean-{bucket}-{index:03d}",
    }

    if bucket.startswith("missing_"):
        field = {
            "missing_ph": "ph",
            "missing_ec": "ec_ms_cm",
            "missing_temperature": "air_temperature_c",
            "missing_humidity": "humidity_pct",
            "missing_moisture": "substrate_moisture_pct",
        }[bucket]
        if field not in expected_fields:
            expected_fields.append(field)
        if index % 2:
            sensor.pop(field)
        else:
            sensor[field] = None
    elif bucket == "impossible_ph":
        sensor["ph"] = (-0.4, 1.8, 11.4, 15.1)[index % 4]
    elif bucket == "impossible_ec":
        sensor["ec_ms_cm"] = (-2.5, -0.05, 12.4, 20.0)[index % 4]
    elif bucket == "impossible_temperature":
        sensor["air_temperature_c"] = (-31.0, -10.5, 65.5, 104.0)[index % 4]
    elif bucket == "impossible_humidity":
        sensor["humidity_pct"] = (-25.0, -0.5, 100.5, 155.0)[index % 4]
    elif bucket == "stale_reading":
        sensor["timestamp"] = "2026-07-10T09:30:00Z"
    elif bucket == "unit_mismatch":
        sensor["temperature_f"] = round(float(sensor["air_temperature_c"]) * 9 / 5 + 32, 1)
        sensor["sensor_units"] = {"air_temperature_c": "C", "temperature_f": "F"}
    elif bucket == "sensor_drift_possible":
        sensor["previous_ph"] = round(float(sensor["ph"]) - 0.95, 2)
    elif bucket == "conflicting_readings":
        sensor["backup_air_temperature_c"] = round(float(sensor["air_temperature_c"]) + 11.5, 1)
    elif bucket == "insufficient_context":
        if index % 2:
            expected_fields = []
        else:
            context["system_type"] = ""
    elif bucket != "normal":
        raise ValueError(f"Unknown bucket: {bucket}")

    return {"farm_context": context, "sensor": sensor, "expected_fields": expected_fields}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-bucket", type=int, default=12)
    args = parser.parse_args()
    derive = load_rules()
    buckets = (
        "normal", "missing_ph", "missing_ec", "missing_temperature", "missing_humidity",
        "missing_moisture", "impossible_ph", "impossible_ec", "impossible_temperature",
        "impossible_humidity", "stale_reading", "unit_mismatch", "sensor_drift_possible",
        "conflicting_readings", "insufficient_context",
    )
    records = []
    for bucket in buckets:
        for index in range(args.per_bucket):
            input_data = make_input(bucket, index)
            records.append({
                "id": f"sensor-clean-{bucket}-{index:04d}",
                "source_id": "pomona_generated_sensor_quality_clean_holdout",
                "input": input_data,
                "expected_output": derive(
                    input_data["farm_context"], input_data["sensor"], input_data["expected_fields"], now=NOW
                ),
                "notes": "Independent clean holdout with unique context and boundary values.",
            })
    write_jsonl(args.output_dir / "test.jsonl", records)
    summary = {"records": len(records), "per_bucket": args.per_bucket, "buckets": list(buckets)}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
