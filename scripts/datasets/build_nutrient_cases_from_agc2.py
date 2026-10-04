#!/usr/bin/env python3
"""Build candidate nutrient pH/EC eval cases from real Wageningen AGC2 lab analyses.

Source: the 2nd Autonomous Greenhouse Challenge (cherry tomato on rockwool, CC0), file
LabAnalysis.csv of each compartment: one lab sample every ~2 weeks with irrigation (feed) and
drain pH / EC. Raw files stay local (datasets/raw/4tu_agc2_cherry_tomato/extracted/).

Each lab sample gives two cases: the feed solution and the drain (root zone). The expected output
is what Pomona's deterministic nutrient rules say today. These are NOT agronomic ground truth:
`review.needs_owner_review` marks cases where the rule label contradicts how commercial rockwool
tomato is normally run (feed pH 5.0-5.5, drain EC 4-6 mS/cm), so a person decides before any case
is added to the committed eval set. Output goes to datasets/interim/ (gitignored).

Usage: python3 scripts/datasets/build_nutrient_cases_from_agc2.py [--out PATH]
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "datasets/raw/4tu_agc2_cherry_tomato/extracted"
DEFAULT_OUT = ROOT / "datasets/interim/agc2_nutrient_candidate_cases.jsonl"

# Typical commercial rockwool tomato practice (general horticulture knowledge, not from the dataset).
FEED_PH_NORMAL = (5.0, 6.0)
DRAIN_EC_NORMAL_MAX = 6.5


def load_rules():
    sys.path.insert(0, str(ROOT / "services/model-router"))
    from app.nutrient_ph_ec import derive_nutrient_ph_ec
    return derive_nutrient_ph_ec


def number(row, key):
    try:
        value = float(row[key])
    except (KeyError, ValueError, TypeError):
        return None
    return None if value != value else value


def review_note(kind, ph, ec, labels):
    notes = []
    if kind == "feed" and ph is not None and "low_ph" in labels and ph >= FEED_PH_NORMAL[0]:
        notes.append(f"feed pH {ph} is in the normal rockwool feed range {FEED_PH_NORMAL}; rule low_ph (<= 5.3) fires")
    if kind == "drain" and ec is not None and "high_ec" in labels and ec <= DRAIN_EC_NORMAL_MAX:
        notes.append(f"drain EC {ec} is normal for rockwool tomato (salinity is used on purpose); rule high_ec (>= 4.5) fires")
    return notes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    if not RAW.exists():
        raise SystemExit(f"raw data missing: {RAW} (see datasets/sources/4tu_agc2_cherry_tomato.yaml)")
    derive = load_rules()
    cases = []
    for path in sorted(RAW.glob("*/LabAnalysis.csv")):
        team = path.parent.name
        with path.open(encoding="utf-8-sig") as handle:
            for index, row in enumerate(csv.DictReader(handle, skipinitialspace=True)):
                day = (datetime(1899, 12, 30) + timedelta(days=float(row["%Time"]))).date().isoformat()
                for kind, ph_key, ec_key in (("feed", "irr_PH", "irr_EC"), ("drain", "drain_PH", "drain_EC")):
                    ph, ec = number(row, ph_key), number(row, ec_key)
                    if ph is None and ec is None:
                        continue
                    sensor = {"ph": ph, "ec_ms_cm": ec}
                    request = {"farm_context": {"crop": "tomato", "system_type": "hydroponic"},
                               "sensor": sensor, "expected_fields": ["ph", "ec_ms_cm"]}
                    expected = derive(request)
                    notes = review_note(kind, ph, ec, expected["nutrient_risk_labels"])
                    cases.append({
                        "id": f"agc2-nutrient-{team.lower()}-{day}-{kind}",
                        "source_id": "4tu_agc2_cherry_tomato",
                        "input": request,
                        "expected_output": expected,
                        "review": {"needs_owner_review": bool(notes), "notes": notes,
                                   "compartment": team, "sample_date": day, "sample_kind": kind},
                    })
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, sort_keys=True) + "\n")
    flagged = [c for c in cases if c["review"]["needs_owner_review"]]
    labels = {}
    for case in cases:
        for label in case["expected_output"]["nutrient_risk_labels"]:
            labels[label] = labels.get(label, 0) + 1
    print(json.dumps({"cases": len(cases), "label_counts": labels, "needs_owner_review": len(flagged),
                      "agree_with_rules_and_practice": len(cases) - len(flagged), "out": str(args.out)}, indent=1))


if __name__ == "__main__":
    main()
