#!/usr/bin/env python3
"""Normalize Purdue WHIN soil/weather files into Pomona interim JSONL.

This is a scaffold only. Do not download or use raw WHIN data until the source
license and redistribution terms are manually verified.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


DEFAULT_RAW_DIR = Path("datasets/raw/purdue_whin_soil_weather")
DEFAULT_OUTPUT = Path("datasets/interim/purdue_whin_soil_weather.normalized.jsonl")


def find_column(fieldnames: list[str], candidates: list[str]) -> str | None:
    lowered = {name.lower().strip(): name for name in fieldnames}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    for name in fieldnames:
        low = name.lower()
        if any(candidate.lower() in low for candidate in candidates):
            return name
    return None


def as_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_csv(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            return records
        fields = reader.fieldnames
        timestamp_col = find_column(fields, ["timestamp", "datetime", "date_time", "time"])
        moisture_col = find_column(fields, ["soil_moisture", "moisture", "vwc", "water_content"])
        soil_temp_col = find_column(fields, ["soil_temperature", "soil_temp"])
        air_temp_col = find_column(fields, ["air_temperature", "air_temp", "temperature"])
        humidity_col = find_column(fields, ["relative_humidity", "humidity", "rh"])
        rainfall_col = find_column(fields, ["rainfall", "rain", "precipitation"])
        node_col = find_column(fields, ["node", "station", "site", "device"])

        for index, row in enumerate(reader, start=1):
            sensor = {
                "timestamp": row.get(timestamp_col) if timestamp_col else None,
                "substrate_moisture_pct": as_float(row.get(moisture_col)) if moisture_col else None,
                "soil_temperature_c": as_float(row.get(soil_temp_col)) if soil_temp_col else None,
                "air_temperature_c": as_float(row.get(air_temp_col)) if air_temp_col else None,
                "humidity_pct": as_float(row.get(humidity_col)) if humidity_col else None,
                "rainfall_mm": as_float(row.get(rainfall_col)) if rainfall_col else None,
            }
            records.append(
                {
                    "id": f"purdue-whin-{path.stem}-{index:06d}",
                    "source_id": "purdue_whin_soil_weather",
                    "farm_context": {
                        "crop": "unknown",
                        "system_type": "soil_field",
                        "zone_id": row.get(node_col) if node_col else path.stem,
                    },
                    "sensor": {key: value for key, value in sensor.items() if value is not None},
                    "expected_fields": ["substrate_moisture_pct"],
                    "notes": "Normalized from candidate WHIN soil/weather source; license must be verified before use.",
                }
            )
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=DEFAULT_RAW_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-unverified-license", action="store_true")
    args = parser.parse_args()

    if not args.allow_unverified_license:
        raise SystemExit(
            "Refusing to normalize Purdue WHIN data until license is verified. "
            "Pass --allow-unverified-license only for private local inspection."
        )
    if not args.raw_dir.exists():
        raise FileNotFoundError(f"Raw directory not found: {args.raw_dir}")

    records: list[dict[str, Any]] = []
    for csv_path in sorted(args.raw_dir.glob("*.csv")):
        records.extend(normalize_csv(csv_path))
    write_jsonl(args.output, records)
    print(f"wrote {len(records)} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
