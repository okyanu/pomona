"""In-memory suggestion store.

v0.1 scope: suggestions and their approval status live only in process
memory, matching the other stateless specialist services. No suggestion --
approved or not -- ever triggers an actuator; there is no execution path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional

from app.config import settings


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SuggestionStore:
    def __init__(self, max_suggestions: Optional[int] = None) -> None:
        self._max_suggestions = max_suggestions or settings.max_suggestions
        self._lock = Lock()
        self._suggestions: Dict[str, Dict[str, Any]] = {}
        self._order: List[str] = []

    def add(self, rule_id: str, action: str, message: str, context: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            suggestion_id = str(uuid.uuid4())
            suggestion = {
                "id": suggestion_id,
                "rule_id": rule_id,
                "action": action,
                "message": message,
                "context": context,
                "requires_approval": True,
                "status": "pending",
                "created_at": utc_now_iso(),
                "decided_at": None,
            }
            self._suggestions[suggestion_id] = suggestion
            self._order.append(suggestion_id)
            while len(self._order) > self._max_suggestions:
                oldest = self._order.pop(0)
                self._suggestions.pop(oldest, None)
            return dict(suggestion)

    def get(self, suggestion_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            suggestion = self._suggestions.get(suggestion_id)
            return dict(suggestion) if suggestion else None

    def list(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._lock:
            items = [dict(self._suggestions[sid]) for sid in reversed(self._order)]
        if status:
            items = [item for item in items if item["status"] == status]
        return items

    def decide(self, suggestion_id: str, status: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            suggestion = self._suggestions.get(suggestion_id)
            if not suggestion:
                return None
            if suggestion["status"] != "pending":
                return dict(suggestion)
            suggestion["status"] = status
            suggestion["decided_at"] = utc_now_iso()
            return dict(suggestion)

    def clear(self) -> None:
        with self._lock:
            self._suggestions.clear()
            self._order.clear()


suggestion_store = SuggestionStore()
