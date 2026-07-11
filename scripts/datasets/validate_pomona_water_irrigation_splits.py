#!/usr/bin/env python3
"""Reject water-irrigation splits that share exact input packets."""

from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path


def input_signatures(path: Path) -> set[str]:
    signatures: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                signatures.add(json.dumps(record["input"], sort_keys=True, separators=(",", ":")))
    return signatures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", type=Path, required=True)
    args = parser.parse_args()

    splits = {
        name: input_signatures(args.dataset_dir / f"{name}.jsonl")
        for name in ("train", "validation", "test")
    }
    overlaps: list[str] = []
    for left, right in combinations(splits, 2):
        count = len(splits[left] & splits[right])
        print(f"{left}/{right}: {count} exact input overlaps")
        if count:
            overlaps.append(f"{left}/{right}={count}")
    if overlaps:
        raise SystemExit("Split leakage detected: " + ", ".join(overlaps))
    print("OK: no exact input overlap across splits.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
