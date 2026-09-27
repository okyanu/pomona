"""Replay an explicitly prepared single-zone JSONL log; writes only a new report."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"services/digital-twin"))
from app.replay import replay

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--split-index", required=True, type=int)
    parser.add_argument("--step-minutes", type=int, default=15)
    args = parser.parse_args()
    records = [json.loads(line) for line in args.input.read_text().splitlines() if line.strip()]
    report = replay(records, split_index=args.split_index, step_minutes=args.step_minutes)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2)
    print(f"Wrote replay report: {args.output}. No model fitting or field validation claimed.")
