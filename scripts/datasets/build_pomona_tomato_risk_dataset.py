#!/usr/bin/env python3
"""Build derived Pomona tomato risk records from normalized interim source data."""

from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import random
from pathlib import Path
from typing import Any


DEFAULT_DATASET_DIR = Path("datasets/pomona-tomato-risk-v0.1")
DEFAULT_INTERIM_FILES = [
    Path("datasets/interim/udea_greenhouse_tomato.normalized.jsonl"),
    Path("datasets/interim/4tu_autonomous_greenhouse_challenge.normalized.jsonl"),
]
DEFAULT_OUTPUT = Path("datasets/processed/pomona-tomato-risk-v0.1/derived_records.jsonl")
RULES_PATH = Path("services/safety-checker/app/tomato_rules.py")


def load_derive_tomato_risk():
    spec = importlib.util.spec_from_file_location("pomona_tomato_rules", RULES_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load rules from {RULES_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.derive_tomato_risk


derive_tomato_risk = load_derive_tomato_risk()


def count_jsonl(path: Path) -> int:
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                records.append(json.loads(line))
    return records


def derive_expected_output(input_data: dict[str, Any]) -> dict[str, Any]:
    return derive_tomato_risk(input_data)


def build_records(interim_files: list[Path]) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    for path in interim_files:
        if not path.exists():
            print(f"Skipping missing interim file: {path}")
            continue
        for record in read_jsonl(path):
            input_data = record.get("input")
            if not isinstance(input_data, dict):
                continue
            derived = {
                "id": f"derived-{record.get('id')}",
                "source_id": record.get("source_id"),
                "input": input_data,
                "expected_output": derive_expected_output(input_data),
                "source_metadata": record.get("source_metadata", {}),
                "notes": "Rule-derived Pomona risk labels from normalized public greenhouse data.",
            }
            built.append(derived)
    return built


def balance_records(records: list[dict[str, Any]], max_records: int, normal_ratio: float, seed: int) -> list[dict[str, Any]]:
    if not max_records or len(records) <= max_records:
        return records

    rng = random.Random(seed)
    normal = [record for record in records if not record["expected_output"]["risk_labels"]]
    risky = [record for record in records if record["expected_output"]["risk_labels"]]
    rng.shuffle(normal)
    rng.shuffle(risky)

    target_normal_count = round(max_records * normal_ratio)
    normal_count = min(len(normal), target_normal_count)
    risky_count = max_records - target_normal_count
    if risky_count > len(risky):
        risky_count = len(risky)
        target_normal_count = max_records - risky_count

    selected = (
        normal[:normal_count]
        + augment_normal_records(normal, target_normal_count - normal_count, rng)
        + risky[:risky_count]
    )
    rng.shuffle(selected)
    return selected


def jitter(value: Any, rng: random.Random, lower: float, upper: float, digits: int = 2) -> Any:
    if value is None:
        return None
    return round(rng.uniform(lower, upper), digits)


def augment_normal_records(
    normal_records: list[dict[str, Any]],
    count: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    if count <= 0 or not normal_records:
        return []

    augmented: list[dict[str, Any]] = []
    for index in range(count):
        base = copy.deepcopy(normal_records[index % len(normal_records)])
        original_id = base.get("id")
        input_data = base["input"]
        system_type = input_data.get("system_type")

        input_data["air_temperature_c"] = jitter(input_data.get("air_temperature_c"), rng, 21.0, 27.0)
        input_data["humidity_pct"] = jitter(input_data.get("humidity_pct"), rng, 55.0, 78.0)
        input_data["ph"] = jitter(input_data.get("ph"), rng, 5.8, 6.7)
        if system_type == "controlled_greenhouse":
            input_data["ec_ms_cm"] = jitter(input_data.get("ec_ms_cm"), rng, 1.4, 3.2)
        elif system_type == "greenhouse_substrate":
            input_data["ec_ms_cm"] = jitter(input_data.get("ec_ms_cm"), rng, 0.08, 0.35)
        input_data["water_temperature_c"] = jitter(input_data.get("water_temperature_c"), rng, 19.0, 24.0)
        input_data["substrate_temperature_c"] = jitter(input_data.get("substrate_temperature_c"), rng, 20.0, 26.0)
        input_data["substrate_moisture_pct"] = jitter(input_data.get("substrate_moisture_pct"), rng, 35.0, 65.0)
        input_data["co2_ppm"] = jitter(input_data.get("co2_ppm"), rng, 420.0, 850.0, digits=0)
        input_data["light_ppfd"] = jitter(input_data.get("light_ppfd"), rng, 120.0, 650.0)
        input_data["symptoms"] = []

        base["id"] = f"generated-normal-calibration-{index + 1:05d}"
        base["source_id"] = "pomona_generated_normal_calibration"
        base["source_metadata"] = {
            "generated_from_record_id": original_id,
            "generation_method": "safe-range jitter from no-risk normalized greenhouse records",
        }
        base["expected_output"] = derive_expected_output(input_data)
        base["notes"] = "Generated Pomona no-risk calibration case for balancing conservative routine-monitoring behavior."
        if base["expected_output"]["risk_labels"]:
            continue
        augmented.append(base)
    return augmented


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, default=DEFAULT_DATASET_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--interim-file", action="append", type=Path, dest="interim_files")
    parser.add_argument("--max-records", type=int, default=2000, help="Maximum derived records; 0 means all.")
    parser.add_argument("--normal-ratio", type=float, default=0.6, help="Target no-risk ratio when sampling.")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    data_dir = args.dataset_dir / "data"
    samples = data_dir / "samples.jsonl"
    eval_cases = data_dir / "eval_cases.jsonl"

    for path in (samples, eval_cases):
        if not path.exists():
            parser.error(f"required seed file missing: {path}")

    print(f"Dataset scaffold: {args.dataset_dir}")
    print(f"samples: {count_jsonl(samples)}")
    print(f"eval_cases: {count_jsonl(eval_cases)}")

    interim_files = args.interim_files or DEFAULT_INTERIM_FILES
    if args.normal_ratio < 0 or args.normal_ratio > 1:
        parser.error("--normal-ratio must be between 0 and 1")
    records = build_records(interim_files)
    records = balance_records(records, args.max_records, args.normal_ratio, args.seed)
    write_jsonl(args.output, records)
    print(f"derived_records: {len(records)}")
    print(f"wrote: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
