#!/usr/bin/env python3
"""Report whether sensor-quality training data covers truly-omitted fields.

The 2026-09-07 paired diagnostic found both trained adapters fail all 5
truly-omitted-field cases (key absent from `sensor`) while passing all 5
explicit-null cases (key present with value `null`), even though the system
prompt says to treat "null/missing" the same way. This script checks whether
that is because the training data itself only ever demonstrates the null
form. It does not modify or regenerate any dataset.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_PATH = Path("datasets/processed/pomona-sensor-quality-v0.1/all_records.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args()

    if not args.path.exists():
        print(f"not found: {args.path} (run scripts/datasets/build_pomona_sensor_quality_dataset.py first)")
        return 1

    omitted = 0
    nulled = 0
    total_missing_field_records = 0
    with args.path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            missing_fields = record["expected_output"].get("missing_fields") or []
            if not missing_fields:
                continue
            total_missing_field_records += 1
            sensor = record["input"].get("sensor", {})
            for field in missing_fields:
                if field not in sensor:
                    omitted += 1
                elif sensor[field] is None:
                    nulled += 1

    print(f"records with a missing_fields label: {total_missing_field_records}")
    print(f"  as explicit null (key present, value null): {nulled}")
    print(f"  as truly omitted (key absent from sensor):  {omitted}")
    if omitted == 0 and nulled > 0:
        print(
            "\nGAP: training data has zero truly-omitted-field examples. "
            "The deployed rules fallback (services/model-router/app/sensor_quality.py) "
            "and the system prompt both treat omitted-key and explicit-null as "
            "equivalent, but a model only ever shown the null form has no reason "
            "to generalize to the omitted form. This matches the paired diagnostic's "
            "0/5 true-omission result for both adapters. See "
            "docs/SENSOR_QUALITY_INPUT_CONTRACT.md before adding omitted-key cases "
            "to training data or retraining."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
