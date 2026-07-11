#!/usr/bin/env python3
"""Build a clean, unseen evaluation set for the v0.1.6 water adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_pomona_water_irrigation_realderived_dataset import derive_output, write_jsonl
from build_pomona_water_irrigation_v0_1_4_edgefix_dataset import force_exact_output


DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-water-irrigation-risk-v0.1.6-clean-eval")
CROPS = ("tomato", "lettuce", "strawberry", "cucumber")


def make_input(bucket: str, index: int) -> dict[str, Any]:
    field = "root_zone_moisture_pct" if index % 2 else "substrate_moisture_pct"
    system_type = "hydroponic" if field == "root_zone_moisture_pct" else "greenhouse_substrate"
    sensor: dict[str, Any] = {
        field: 52.0,
        "air_temperature_c": round(17.5 + (index % 14) * 1.1, 1),
        "humidity_pct": round(43.0 + (index % 12) * 3.4, 1),
        "timestamp": "2026-07-10T10:00:00Z",
    }
    expected_fields = [field]
    farm_context = {
        "crop": CROPS[index % len(CROPS)],
        "system_type": system_type,
        "zone_id": f"clean-holdout-{bucket}-{index:03d}",
    }

    if bucket == "normal":
        sensor[field] = round(30.5 + (index % 18) * 2.45, 1)
    elif bucket == "low_moisture":
        sensor[field] = round(4.5 + (index % 20) * 1.15, 1)
    elif bucket == "high_moisture":
        sensor[field] = round(78.5 + (index % 20) * 0.95, 1)
    elif bucket == "missing_moisture":
        if index % 2:
            sensor.pop(field)
        else:
            sensor[field] = None
    elif bucket == "stale_irrigation_data":
        sensor[field] = round(34.5 + (index % 16) * 2.1, 1)
        sensor["timestamp"] = "stale"
    elif bucket == "sensor_anomaly":
        values = (-50.0, -20.5, -0.5, 100.5, 112.5, 145.0)
        sensor[field] = values[index % len(values)]
    elif bucket == "insufficient_context":
        if index % 2:
            expected_fields = []
        else:
            farm_context["system_type"] = ""
    else:
        raise ValueError(f"Unknown bucket: {bucket}")

    return {
        "farm_context": farm_context,
        "sensor": sensor,
        "expected_fields": expected_fields,
    }


def make_record(bucket: str, index: int) -> dict[str, Any]:
    record = {
        "id": f"water-v016-clean-eval-{bucket}-{index:04d}",
        "source_id": "pomona_generated_water_irrigation_v0_1_6_clean_holdout",
        "input": make_input(bucket, index),
        "expected_output": {},
        "notes": "Clean holdout packet with a unique zone and unseen moisture values.",
    }
    record["expected_output"] = derive_output(record["input"])
    force_exact_output(record)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-bucket", type=int, default=24)
    args = parser.parse_args()

    buckets = (
        "normal",
        "low_moisture",
        "high_moisture",
        "missing_moisture",
        "stale_irrigation_data",
        "sensor_anomaly",
        "insufficient_context",
    )
    records = [make_record(bucket, index) for bucket in buckets for index in range(args.per_bucket)]
    write_jsonl(args.output_dir / "test.jsonl", records)
    summary = {
        "records": len(records),
        "per_bucket": args.per_bucket,
        "buckets": list(buckets),
        "purpose": "Leakage-free holdout evaluation for the v0.1.6 schema-order adapter.",
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"wrote: {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
