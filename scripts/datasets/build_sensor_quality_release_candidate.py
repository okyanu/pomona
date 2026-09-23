"""Prepare fresh, neutral synthetic release-candidate fixtures, not a release approval.

Expected labels are explicitly authored here, not copied from the detector.
Owner review and overlap checks remain required before a model release.
"""
import argparse
import hashlib
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path


def cases():
    rng = random.Random(9162026)
    kinds = ("normal", "missing_ph", "impossible_ph", "stale_reading", "invalid_value", "future_time", "combined")
    rows = []
    for index in range(8):
        now = datetime(2027, 2, 3, tzinfo=timezone.utc) + timedelta(days=index * 9, seconds=137 * index)
        for kind in kinds:
            sensor = {"ph": round(rng.uniform(5.75, 6.55), 3), "ec_ms_cm": round(rng.uniform(1.2, 2.7), 3),
                      "air_temperature_c": round(rng.uniform(20, 29), 2), "humidity_pct": round(rng.uniform(55, 78), 2),
                      "timestamp": (now - timedelta(seconds=173 + index * 11)).isoformat()}
            labels, missing, suspect = [], [], []
            if kind in {"missing_ph", "combined"}:
                if index % 2:
                    sensor.pop("ph")
                else:
                    sensor["ph"] = None
                labels.append("missing_ph"); missing.append("ph")
            if kind == "impossible_ph":
                sensor["ph"] = 2.999 if index % 2 else 11.001
                labels.append(kind); suspect.append("ph")
            if kind in {"stale_reading", "combined"}:
                sensor["timestamp"] = (now - timedelta(seconds=3601 + index)).isoformat()
                labels.append("stale_reading"); suspect.append("timestamp")
            if kind == "invalid_value":
                sensor["ph"] = [True, "broken", "NaN", {}][index % 4]
                labels.append("insufficient_context"); suspect.append("ph")
            if kind == "future_time":
                sensor["timestamp"] = (now + timedelta(seconds=61 + index)).isoformat()
                labels.append("insufficient_context"); suspect.append("timestamp")
            rows.append({"id": f"candidate-{len(rows):04d}", "bucket": kind,
                         "input": {"farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": f"zone-{index:02d}"},
                                   "sensor": sensor, "expected_fields": ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct"], "current_time": now.isoformat()},
                         "expected_output": {"data_quality_labels": labels, "missing_fields": missing, "suspect_fields": suspect,
                                             "human_review_required": bool(labels)},
                         "review_status": "pending_owner_review"})
    rng.shuffle(rows)
    return rows


def build(destination: Path):
    destination.mkdir(parents=True, exist_ok=False)
    rows = cases()
    content = "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)
    (destination / "test.jsonl").write_text(content)
    manifest = {"version": "sensor-quality-neutral-candidate-2026-09-16", "cases": len(rows),
                "sha256": hashlib.sha256(content.encode()).hexdigest(), "release_approved": False,
                "expected_labels_source": "explicit fixture specification, not detector outputs",
                "limitations": ["synthetic; no field validation", "owner review and training-overlap audit required",
                                "bucket/id/review_status must never enter model prompts", "not an exhaustive release suite"]}
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output_dir", type=Path)
    print(json.dumps(build(parser.parse_args().output_dir), indent=2))
