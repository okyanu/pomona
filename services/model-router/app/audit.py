"""Small append-only audit log for local software validation runs.

The file lives on the data volume and is bounded: once it reaches AUDIT_LOG_MAX_BYTES it is renamed to `<name>.1`
(replacing the previous rotated file, so at most two files exist) and a new file starts. Reading takes the newest
lines from the end of the file, never the whole file.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)
_lock = Lock()
_CHUNK = 8192


def _rotated(path: Path) -> Path:
    return path.with_name(path.name + ".1")  # same directory: a rename, no copy, on a read-only root with a data volume


def _rotate_if_full(path: Path) -> None:
    limit = settings.audit_log_max_bytes
    if limit <= 0:
        return
    try:
        if path.stat().st_size < limit:
            return
        os.replace(path, _rotated(path))
    except FileNotFoundError:
        return
    except OSError as exc:  # keep logging into the full file rather than lose the record
        logger.warning("audit log rotation failed: %s", exc)


def write_pipeline_audit(event: dict[str, Any]) -> None:
    path = settings.audit_log_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _rotate_if_full(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, default=str) + "\n")


def _tail_lines(path: Path, count: int) -> list[str]:
    """The last `count` non-empty lines of a file, read backwards in chunks from its end."""
    with path.open("rb") as handle:
        position = handle.seek(0, os.SEEK_END)
        data = b""
        while position > 0 and data.count(b"\n") <= count:
            step = min(_CHUNK, position)
            position -= step
            handle.seek(position)
            data = handle.read(step) + data
    pieces = data.split(b"\n")
    if position > 0:
        pieces = pieces[1:]  # the first piece may start mid-line
    lines = [piece.decode("utf-8", errors="replace") for piece in pieces if piece.strip()]
    return lines[-count:]


def read_pipeline_audit(limit: int = 50) -> list[dict[str, Any]]:
    """Read newest audit summaries without exposing sensor payloads."""
    path = settings.audit_log_path
    if limit <= 0:
        return []
    lines: list[str] = []
    try:
        if path.exists():
            lines = _tail_lines(path, limit)
        older = _rotated(path)
        if len(lines) < limit and older.exists():  # just after a rotation the newest events are still in `<name>.1`
            lines = _tail_lines(older, limit - len(lines)) + lines
    except OSError as exc:
        logger.warning("audit log could not be read: %s", exc)
    events: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            events.append(value)
    return list(reversed(events))
