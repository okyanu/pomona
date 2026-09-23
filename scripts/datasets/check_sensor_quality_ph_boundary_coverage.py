#!/usr/bin/env python3
"""Report whether sensor-quality training data covers a graded pH boundary.

The 2026-09-07 pH sweep (private/SENSOR_QUALITY_PH_SWEEP_2026_09_07.md) found
both trained adapters wrongly flag plausible normal pH (e.g. 4.0, 9.0, 10.0)
as impossible_ph, because impossible_ph training data only ever used three
far-extreme constants (2.9, 12.8, 14.0) with no example anywhere near the
deployed boundary (`ph < 3.0 or ph > 11.0`,
services/model-router/app/sensor_quality.py). This script checks the
regenerated dataset for near-boundary coverage on both sides of the line. It
does not modify or regenerate any dataset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_PATH = Path("datasets/processed/pomona-sensor-quality-v0.1/all_records.jsonl")
NEAR_BOUNDARY_MARGIN = 2.0  # within this many pH units of 3.0 or 11.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    if not args.path.exists():
        print(f"not found: {args.path} (run scripts/datasets/build_pomona_sensor_quality_dataset.py first)")
        return 1

    near_boundary_impossible = []  # true positives just outside [3.0, 11.0]
    near_boundary_normal = []  # true negatives just inside [3.0, 11.0]
    with args.path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            ph = record["input"].get("sensor", {}).get("ph")
            if not isinstance(ph, (int, float)):
                continue
            labels = record["expected_output"].get("data_quality_labels") or []
            is_impossible = "impossible_ph" in labels
            if is_impossible and ph < 3.0 and ph >= 3.0 - NEAR_BOUNDARY_MARGIN:
                near_boundary_impossible.append(ph)
            elif is_impossible and ph > 11.0 and ph <= 11.0 + NEAR_BOUNDARY_MARGIN:
                near_boundary_impossible.append(ph)
            elif not is_impossible and 3.0 <= ph <= 3.0 + NEAR_BOUNDARY_MARGIN:
                near_boundary_normal.append(ph)
            elif not is_impossible and 11.0 - NEAR_BOUNDARY_MARGIN <= ph <= 11.0:
                near_boundary_normal.append(ph)

    print(f"impossible_ph records within {NEAR_BOUNDARY_MARGIN} of the boundary: {len(near_boundary_impossible)}")
    print(f"  distinct values: {sorted(set(near_boundary_impossible))}")
    print(f"normal-labeled records within {NEAR_BOUNDARY_MARGIN} of the boundary: {len(near_boundary_normal)}")
    print(f"  distinct values: {sorted(set(near_boundary_normal))}")

    if not near_boundary_impossible or not near_boundary_normal:
        print(
            "\nGAP: training data still lacks a graded pH boundary on at least one side. "
            "Both a near-boundary impossible_ph example and a near-boundary normal example "
            "are needed for the model to learn the actual 3.0/11.0 threshold instead of a "
            "training-range cluster. See docs/SENSOR_QUALITY_INPUT_CONTRACT.md."
        )
        return 1

    print("\nOK: both sides of the pH boundary have near-boundary examples.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
