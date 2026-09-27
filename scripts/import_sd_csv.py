#!/usr/bin/env python3
"""Import SD-card or hand-entered sensor CSV files into Pomona Core.

Each CSV row becomes one POST /v1/sensors/observations. Core remains the
validator of record: rows it rejects (HTTP 422) are reported, never dropped
silently. Re-importing the same file is safe: Core accepts (HTTP 201) but does
not store again rows it already has (boot_id + sequence), so "accepted" counts
rows Core took, not new rows. Repeated rows inside one run are skipped here.

Columns (header required; only the first four are mandatory):
  timestamp_utc, zone_id, measurement, value,
  farm_id, device_id, sensor_id, unit, quality, boot_id, sequence,
  calibration_timestamp, firmware, raw

`raw` is kept on the SD card for later recalibration and is not sent to Core.
Rows without a timezone-aware timestamp are rejected (no guessed times).
Stdlib only, so it runs outside the service virtualenvs.

Usage:
  python scripts/import_sd_csv.py LOG.CSV [...] --farm-id home-pilot
  python scripts/import_sd_csv.py manual_readings.csv --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

UNITS = {
    "air_temperature_c": "C",
    "water_temperature_c": "C",
    "humidity_pct": "%",
    "ph": "pH",
    "ec_ms_cm": "mS/cm",
    "soil_moisture_pct": "%",
    "low_level_contact": "boolean",
}
PASSTHROUGH = ("calibration_timestamp", "firmware")
# Logged on the SD card but not yet part of Core's observation contract.
SD_ONLY_MEASUREMENTS = {"substrate_temperature_c"}

Poster = Callable[[str, Dict[str, Any]], Tuple[int, str]]


def _clean(row: Dict[str, Any]) -> Dict[str, str]:
    return {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}


def row_to_observation(row: Dict[str, Any], defaults: Dict[str, str]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Map one CSV row to a SensorObservation payload, or return an error."""
    row = _clean(row)
    get = lambda key: row.get(key) or defaults.get(key, "")  # noqa: E731

    timestamp = row.get("timestamp_utc") or row.get("timestamp", "")
    if not timestamp:
        return None, "missing timestamp"
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None, f"unparseable timestamp {timestamp!r}"
    if parsed.tzinfo is None:
        return None, "timestamp must include a timezone (use ...Z for UTC)"

    measurement = row.get("measurement", "")
    if measurement not in UNITS:
        return None, f"unknown measurement {measurement!r}"

    for key in ("farm_id", "zone_id"):
        if not get(key):
            return None, f"missing {key}"

    payload: Dict[str, Any] = {
        "device_id": get("device_id") or "manual-log",
        "farm_id": get("farm_id"),
        "zone_id": get("zone_id"),
        "sensor_id": get("sensor_id") or f"manual-{measurement}",
        "measurement": measurement,
        "unit": row.get("unit") or UNITS[measurement],
        "timestamp": parsed.isoformat(),
    }
    value = row.get("value", "")
    if value:
        try:
            payload["value"] = float(value)
        except ValueError:
            return None, f"non-numeric value {value!r}"
    payload["quality"] = row.get("quality") or ("valid" if value else "missing")
    if row.get("boot_id"):
        payload["boot_id"] = row["boot_id"]
    if row.get("sequence"):
        try:
            payload["sequence"] = int(row["sequence"])
        except ValueError:
            return None, f"non-integer sequence {row['sequence']!r}"
    for key in PASSTHROUGH:
        if row.get(key):
            payload[key] = row[key]
    return payload, None


def _identity(payload: Dict[str, Any]) -> str:
    if "boot_id" in payload and "sequence" in payload:
        keys = ("device_id", "sensor_id", "measurement", "boot_id", "sequence")
        return json.dumps([payload[k] for k in keys])
    return json.dumps(payload, sort_keys=True)


def http_poster(core_url: str, api_key: str = "") -> Poster:
    def post(path: str, payload: Dict[str, Any]) -> Tuple[int, str]:
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            core_url.rstrip("/") + path,
            data=json.dumps(payload).encode(),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    return post


def import_rows(
    rows: Iterable[Tuple[str, Dict[str, Any]]],
    defaults: Dict[str, str],
    post: Optional[Poster],
) -> Dict[str, Any]:
    """Import (location, row) pairs. post=None performs a dry run."""
    seen = set()
    summary: Dict[str, Any] = {"accepted": 0, "duplicates": 0, "sd_only_skipped": 0, "rejected": []}
    for location, row in rows:
        if (row.get("measurement") or "").strip() in SD_ONLY_MEASUREMENTS:
            summary["sd_only_skipped"] += 1
            continue
        payload, error = row_to_observation(row, defaults)
        if error:
            summary["rejected"].append({"row": location, "reason": error})
            continue
        identity = _identity(payload)
        if identity in seen:
            summary["duplicates"] += 1
            continue
        seen.add(identity)
        if post is None:
            summary["accepted"] += 1
            continue
        status, body = post("/v1/sensors/observations", payload)
        if status == 201:
            summary["accepted"] += 1
        else:
            summary["rejected"].append({"row": location, "reason": f"HTTP {status}: {body[:300]}"})
    return summary


def read_csv_rows(paths: List[Path]) -> Iterable[Tuple[str, Dict[str, Any]]]:
    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(line for line in handle if not line.lstrip().startswith("#"))
            for number, row in enumerate(reader, start=2):
                yield f"{path.name}:{number}", row


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv_files", nargs="+", type=Path)
    parser.add_argument("--core-url", default=os.environ.get("POMONA_CORE_URL", "http://localhost:8080"))
    parser.add_argument("--api-key", default=os.environ.get("API_KEY", ""))
    parser.add_argument("--farm-id", default="", help="default farm_id for rows without one")
    parser.add_argument("--zone-id", default="", help="default zone_id for rows without one")
    parser.add_argument("--device-id", default="", help="default device_id for rows without one")
    parser.add_argument("--dry-run", action="store_true", help="validate locally without posting")
    args = parser.parse_args(argv)

    defaults = {"farm_id": args.farm_id, "zone_id": args.zone_id, "device_id": args.device_id}
    post = None if args.dry_run else http_poster(args.core_url, args.api_key)
    summary = import_rows(read_csv_rows(args.csv_files), defaults, post)
    print(json.dumps(summary, indent=2))
    return 1 if summary["rejected"] else 0


if __name__ == "__main__":
    sys.exit(main())
