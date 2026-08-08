"""Small append-only audit log for local software validation runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings


def write_pipeline_audit(event: dict[str, Any]) -> None:
    path = settings.audit_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def read_pipeline_audit(limit: int = 50) -> list[dict[str, Any]]:
    """Read newest audit summaries without exposing sensor payloads."""
    if limit <= 0 or not settings.audit_log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in settings.audit_log_path.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return list(reversed(events))
