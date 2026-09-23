"""Render raw JSONL into canonical training text without columnar inference.

Preparation only: no training, Hub access, or model loading. Output must be new.
"""
import argparse
import hashlib
import json
from pathlib import Path

from sensor_quality_contract import render_prompt, SYSTEM_PROMPT_SHA256


def prepare(source: Path, destination: Path) -> dict:
    if destination.exists():
        raise FileExistsError("Choose a new output path; historical inputs are immutable")
    rows = []
    ids = set()
    for line in source.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record["id"] in ids:
            raise ValueError("Duplicate record ID")
        ids.add(record["id"])
        prompt = render_prompt(record["input"])
        rows.append({"id": record["id"], "prompt": prompt,
                     "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                     "answer": json.dumps(record["expected_output"], sort_keys=True, separators=(",", ":"), allow_nan=False)})
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("x") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    return {"rows": len(rows), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "system_prompt_sha256": SYSTEM_PROMPT_SHA256, "training_run": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.destination), indent=2))
