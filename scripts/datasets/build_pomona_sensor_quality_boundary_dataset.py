#!/usr/bin/env python3
"""Build Pomona Sensor Quality Reasoner v0.1.1 boundary training data."""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from copy import deepcopy
from pathlib import Path
from typing import Any


DEFAULT_BASE_JSONL = Path("datasets/processed/pomona-sensor-quality-v0.1/all_records.jsonl")
DEFAULT_OUTPUT_DIR = Path("datasets/processed/pomona-sensor-quality-v0.1.1-boundary")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def normal_input(index: int, rng: random.Random) -> dict[str, Any]:
    system_type = rng.choice(["controlled_greenhouse", "hydroponic", "greenhouse_substrate"])
    expected_fields = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
    if system_type == "greenhouse_substrate":
        expected_fields.append("substrate_moisture_pct")
    return {
        "farm_context": {
            "crop": rng.choice(["tomato", "strawberry", "lettuce", "cucumber"]),
            "system_type": system_type,
            "zone_id": f"boundary-zone-{index % 7}",
        },
        "sensor": {
            "air_temperature_c": round(20.0 + (index % 10) * 0.6, 1),
            "humidity_pct": round(52.0 + (index % 9) * 3.0, 1),
            "ph": round(5.7 + (index % 8) * 0.12, 2),
            "ec_ms_cm": round(1.4 + (index % 7) * 0.24, 2),
            "substrate_moisture_pct": round(36.0 + (index % 11) * 2.0, 1),
            "timestamp": "2026-07-07T10:00:00Z",
        },
        "expected_fields": expected_fields,
    }


def make_record(
    record_id: str,
    input_data: dict[str, Any],
    labels: list[str],
    missing_fields: list[str],
    suspect_fields: list[str],
    checks: list[str],
    rationale: str,
) -> dict[str, Any]:
    return {
        "id": record_id,
        "source_id": "pomona_generated_sensor_quality_v0_1_1_boundary",
        "input": input_data,
        "expected_output": {
            "data_quality_labels": labels,
            "missing_fields": missing_fields,
            "suspect_fields": suspect_fields,
            "safe_next_checks": checks,
            "human_review_required": bool(labels or missing_fields or suspect_fields),
            "rationale": rationale,
        },
        "notes": "Generated boundary case for Pomona sensor-quality label separation.",
    }


def boundary_records(seed: int, repeats: int) -> list[dict[str, Any]]:
    rng = random.Random(seed)
    records: list[dict[str, Any]] = []
    counter = 1

    for index in range(repeats):
        base = normal_input(index, rng)
        sensor = base["sensor"]

        cases: list[tuple[dict[str, Any], list[str], list[str], list[str], list[str], str, str]] = []

        normal = deepcopy(base)
        cases.append(
            (
                normal,
                [],
                [],
                [],
                ["continue routine monitoring"],
                "Critical readings are present, recent, and inside plausible ranges.",
                "normal",
            )
        )

        missing_ph = deepcopy(base)
        missing_ph["sensor"]["ph"] = None
        cases.append(
            (
                missing_ph,
                ["missing_ph"],
                ["ph"],
                [],
                ["restore or manually measure pH before risk or fertigation reasoning"],
                "pH is explicitly expected but missing; this is not a drift or conflict case.",
                "missing-ph",
            )
        )

        missing_ec = deepcopy(base)
        missing_ec["sensor"]["ec_ms_cm"] = None
        cases.append(
            (
                missing_ec,
                ["missing_ec"],
                ["ec_ms_cm"],
                [],
                ["restore or manually verify EC before nutrient reasoning"],
                "EC is explicitly expected but missing; no other reading can replace it automatically.",
                "missing-ec",
            )
        )

        missing_temp = deepcopy(base)
        missing_temp["sensor"]["air_temperature_c"] = None
        cases.append(
            (
                missing_temp,
                ["missing_temperature"],
                ["air_temperature_c"],
                [],
                ["restore or manually verify air temperature before stress reasoning"],
                "Air temperature is expected but missing; do not infer it from humidity or timestamps.",
                "missing-temperature",
            )
        )

        missing_humidity = deepcopy(base)
        missing_humidity["sensor"]["humidity_pct"] = None
        cases.append(
            (
                missing_humidity,
                ["missing_humidity"],
                ["humidity_pct"],
                [],
                ["restore or manually verify humidity before disease-pressure reasoning"],
                "Humidity is expected but missing; this is a missing field, not a suspicious value.",
                "missing-humidity",
            )
        )

        missing_moisture = deepcopy(base)
        if "substrate_moisture_pct" not in missing_moisture["expected_fields"]:
            missing_moisture["expected_fields"].append("substrate_moisture_pct")
        missing_moisture["sensor"]["substrate_moisture_pct"] = None
        cases.append(
            (
                missing_moisture,
                ["missing_moisture"],
                ["substrate_moisture_pct"],
                [],
                ["restore or manually verify substrate moisture before irrigation reasoning"],
                "Substrate moisture is expected for this packet and is missing.",
                "missing-moisture",
            )
        )

        impossible_ph = deepcopy(base)
        impossible_ph["sensor"]["ph"] = rng.choice([2.2, 12.9, 14.4])
        cases.append(
            (
                impossible_ph,
                ["impossible_ph"],
                [],
                ["ph"],
                ["inspect pH probe calibration and units before using this reading"],
                "The pH value is outside a plausible agricultural sensor range.",
                "impossible-ph",
            )
        )

        impossible_ec = deepcopy(base)
        impossible_ec["sensor"]["ec_ms_cm"] = rng.choice([-0.7, -0.1, 18.2])
        cases.append(
            (
                impossible_ec,
                ["impossible_ec"],
                [],
                ["ec_ms_cm"],
                ["inspect EC sensor units, sample availability, and calibration"],
                "The EC value is outside a plausible sensor range and is not merely drifting.",
                "impossible-ec",
            )
        )

        impossible_humidity = deepcopy(base)
        impossible_humidity["sensor"]["humidity_pct"] = rng.choice([-8.0, 118.0, 132.0])
        cases.append(
            (
                impossible_humidity,
                ["impossible_humidity"],
                [],
                ["humidity_pct"],
                ["validate humidity sensor range and compare with a backup reading"],
                "Humidity percentage must stay between 0 and 100.",
                "impossible-humidity",
            )
        )

        impossible_temp = deepcopy(base)
        impossible_temp["sensor"]["air_temperature_c"] = rng.choice([-24.0, 76.0, 93.0])
        cases.append(
            (
                impossible_temp,
                ["impossible_temperature"],
                [],
                ["air_temperature_c"],
                ["compare air temperature against a backup sensor and check units"],
                "The current Celsius temperature is impossible for a normal greenhouse packet.",
                "impossible-temperature",
            )
        )

        stale = deepcopy(base)
        stale["sensor"]["timestamp"] = "2026-07-06T07:30:00Z"
        cases.append(
            (
                stale,
                ["stale_reading"],
                [],
                ["timestamp"],
                ["confirm the latest telemetry timestamp before using this packet"],
                "Values are plausible, but the timestamp is too old for current reasoning.",
                "stale-reading",
            )
        )

        unit = deepcopy(base)
        unit["sensor"]["temperature_f"] = sensor["air_temperature_c"]
        unit["sensor"]["sensor_units"] = {"air_temperature_c": "F", "temperature_f": "C"}
        cases.append(
            (
                unit,
                ["unit_mismatch"],
                [],
                ["air_temperature_c", "temperature_f", "sensor_units"],
                ["verify temperature units and sensor mapping before comparing thresholds"],
                "The packet has explicit unit ambiguity; this is not a backup-sensor conflict.",
                "unit-mismatch",
            )
        )

        conflict = deepcopy(base)
        conflict["sensor"]["backup_air_temperature_c"] = round(float(sensor["air_temperature_c"]) + rng.choice([10.5, 13.0, -11.0]), 1)
        cases.append(
            (
                conflict,
                ["conflicting_readings"],
                [],
                ["air_temperature_c", "backup_air_temperature_c"],
                ["compare primary and backup temperature probes before using the value"],
                "Two Celsius temperature probes disagree; there is no unit ambiguity field.",
                "conflicting-readings",
            )
        )

        drift = deepcopy(base)
        drift["sensor"]["previous_ph"] = round(float(sensor["ph"]) - rng.choice([0.9, 1.1, -1.0]), 2)
        cases.append(
            (
                drift,
                ["sensor_drift_possible"],
                [],
                ["ph", "previous_ph"],
                ["repeat pH measurement and inspect probe drift before threshold reasoning"],
                "The current pH is plausible but changed sharply from the previous reading.",
                "sensor-drift-possible",
            )
        )

        insufficient_context = deepcopy(base)
        insufficient_context["expected_fields"] = []
        insufficient_context["farm_context"] = {"crop": insufficient_context["farm_context"]["crop"]}
        cases.append(
            (
                insufficient_context,
                ["insufficient_context"],
                [],
                ["expected_fields", "farm_context.system_type"],
                ["provide expected fields and farm system context before quality classification"],
                "The packet lacks expected-field and system context; values alone are not enough.",
                "insufficient-context",
            )
        )

        for input_data, labels, missing, suspect, checks, rationale, suffix in cases:
            records.append(
                make_record(
                    f"boundary-sensor-quality-{counter:05d}-{suffix}",
                    input_data,
                    labels,
                    missing,
                    suspect,
                    checks,
                    rationale,
                )
            )
            counter += 1

    return records


def bucket_key(record: dict[str, Any]) -> str:
    labels = record["expected_output"].get("data_quality_labels") or []
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
    parser.add_argument("--base-jsonl", type=Path, default=DEFAULT_BASE_JSONL)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--repeats", type=int, default=40)
    parser.add_argument("--seed", type=int, default=77)
    args = parser.parse_args()

    base_records = read_jsonl(args.base_jsonl)
    hardcases = boundary_records(args.seed, args.repeats)
    records = base_records + hardcases
    train, validation, test = split_records(records, args.seed)

    write_jsonl(args.output_dir / "all_records.jsonl", records)
    write_jsonl(args.output_dir / "train.jsonl", train)
    write_jsonl(args.output_dir / "validation.jsonl", validation)
    write_jsonl(args.output_dir / "test.jsonl", test)

    label_counts: dict[str, int] = defaultdict(int)
    for record in records:
        label_counts[bucket_key(record)] += 1

    summary = {
        "base_records": len(base_records),
        "boundary_records": len(hardcases),
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
