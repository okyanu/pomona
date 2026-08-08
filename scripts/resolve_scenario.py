#!/usr/bin/env python3
"""Resolve dynamic values in a local Pomona validation scenario."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CURRENT_TIMESTAMP = "__CURRENT_TIMESTAMP__"


def resolve_dynamic_values(value: Any, *, now: datetime | None = None) -> Any:
    timestamp = (now or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {key: resolve_dynamic_values(item, now=now) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve_dynamic_values(item, now=now) for item in value]
    if value == CURRENT_TIMESTAMP:
        return timestamp
    return value


def resolve_scenario(path: Path) -> dict[str, Any]:
    return resolve_dynamic_values(json.loads(path.read_text()))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: resolve_scenario.py SCENARIO_JSON")
    print(json.dumps(resolve_scenario(Path(sys.argv[1])), separators=(",", ":")))
