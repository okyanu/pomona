"""Bounded SQLite suggestion history; recording decisions never runs hardware."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

from app.config import settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SuggestionStore:
    def __init__(self, max_suggestions: Optional[int] = None, db_path: Optional[Path] = None, ttl_seconds: Optional[int] = None) -> None:
        self._ttl_seconds = ttl_seconds if ttl_seconds is not None else settings.suggestion_ttl_seconds
        if self._ttl_seconds < 1:
            raise ValueError("ttl_seconds must be positive")
        self._max_suggestions = max_suggestions if max_suggestions is not None else settings.max_suggestions
        if self._max_suggestions < 1:
            raise ValueError("max_suggestions must be positive")
        self._lock = Lock()
        if db_path is not None:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path) if db_path is not None else ":memory:",
                                   check_same_thread=False, timeout=10)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS suggestions (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                rule_id TEXT NOT NULL, action TEXT NOT NULL, message TEXT NOT NULL,
                context TEXT NOT NULL, status TEXT NOT NULL,
                created_at TEXT NOT NULL, decided_at TEXT, reviewer TEXT)""")
            # Upgrade the previous local history schema without losing decisions.
            columns = {row[1] for row in self._db.execute("PRAGMA table_info(suggestions)")}
            if "dedupe_key" not in columns:
                self._db.execute("ALTER TABLE suggestions ADD COLUMN dedupe_key TEXT")
            if "expires_at" not in columns:
                self._db.execute("ALTER TABLE suggestions ADD COLUMN expires_at TEXT")
                for row in self._db.execute("SELECT id, created_at, context FROM suggestions").fetchall():
                    self._db.execute("UPDATE suggestions SET expires_at=? WHERE id=?",
                                     (self._expiry(row["created_at"], json.loads(row["context"])), row["id"]))
            self._db.execute("CREATE UNIQUE INDEX IF NOT EXISTS suggestions_dedupe ON suggestions(dedupe_key)")

    def _expiry(self, created_at: str, context: Dict[str, Any]) -> str:
        created = datetime.fromisoformat(created_at)
        expiry = created + timedelta(seconds=self._ttl_seconds)
        if "sensor_timestamp" in context:
            try:
                sampled = datetime.fromisoformat(context["sensor_timestamp"].replace("Z", "+00:00"))
                if sampled.tzinfo is None or sampled > created + timedelta(seconds=60):
                    raise ValueError("Invalid sample clock")
                expiry = min(expiry, sampled + timedelta(seconds=settings.suggestion_sample_max_age_seconds))
            except (ValueError, TypeError, AttributeError):
                expiry = created
        return expiry.isoformat()

    def _expire(self) -> None:
        self._db.execute("""UPDATE suggestions SET status='expired', decided_at=?
            WHERE status='pending' AND (expires_at IS NULL OR julianday(expires_at)<=julianday(?))""",
                         (utc_now_iso(), utc_now_iso()))

    @staticmethod
    def _decode(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item.pop("seq")
        item.pop("dedupe_key", None)
        item["context"] = json.loads(item["context"])
        item["requires_approval"] = True
        return item

    def add(self, rule_id: str, action: str, message: str, context: Dict[str, Any], event_id: Optional[str] = None) -> Dict[str, Any]:
        suggestion_id = str(uuid.uuid4())
        # Stable event + rule content, never the randomly generated pipeline run ID.
        key = hashlib.sha256(json.dumps([event_id, rule_id, action, message]).encode()).hexdigest() if event_id else None
        created = utc_now_iso()
        with self._lock, self._db:
            self._expire()
            self._db.execute("""INSERT INTO suggestions
                (id, rule_id, action, message, context, status, created_at, dedupe_key, expires_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT(dedupe_key) DO NOTHING""",
                (suggestion_id, rule_id, action, message, json.dumps(context), created, key, self._expiry(created, context)))
            self._expire()
            if key:
                row = self._db.execute("SELECT * FROM suggestions WHERE dedupe_key = ?", (key,)).fetchone()
            else:
                row = self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return self._decode(row)

    def get(self, suggestion_id: str) -> Optional[Dict[str, Any]]:
        with self._lock, self._db:
            self._expire()
            row = self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
        return self._decode(row) if row else None

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock, self._db:
            self._expire()
            if status is None:
                rows = self._db.execute("SELECT * FROM suggestions ORDER BY seq DESC").fetchall()
            else:
                rows = self._db.execute("SELECT * FROM suggestions WHERE status = ? ORDER BY seq DESC", (status,)).fetchall()
        return [self._decode(row) for row in rows]

    def decide(self, suggestion_id: str, status: str, reviewer: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if status not in {"approved", "rejected"}:
            raise ValueError("Decision must be approved or rejected")
        with self._lock, self._db:
            self._expire()
            # First decision wins, atomically, even across multiple processes.
            self._db.execute("""UPDATE suggestions SET status = ?, decided_at = ?, reviewer = ?
                WHERE id = ? AND status = 'pending'""", (status, utc_now_iso(), reviewer, suggestion_id))
            row = self._db.execute("SELECT * FROM suggestions WHERE id = ?", (suggestion_id,)).fetchone()
            # Pending work is never purged; only completed history is bounded.
            self._db.execute("""DELETE FROM suggestions WHERE status != 'pending' AND seq NOT IN
                (SELECT seq FROM suggestions WHERE status != 'pending'
                 ORDER BY decided_at DESC, seq DESC LIMIT ?)""", (self._max_suggestions,))
        return self._decode(row) if row else None

    def clear(self) -> None:
        with self._lock, self._db:
            self._db.execute("DELETE FROM suggestions")

    def close(self) -> None:
        with self._lock:
            self._db.close()


suggestion_store = SuggestionStore(db_path=settings.automation_db_path)
