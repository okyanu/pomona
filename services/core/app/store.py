from collections import deque
from threading import Lock
from typing import Optional

from app.config import settings
from app.schemas import SensorEvent


class SensorEventStore:
    def __init__(self, max_events: Optional[int] = None) -> None:
        self._max_events = max_events or settings.max_events
        self._events: deque[SensorEvent] = deque(maxlen=self._max_events)
        self._lock = Lock()

    def add(self, event: SensorEvent) -> None:
        with self._lock:
            self._events.append(event)

    def list_events(self, limit: int = 50) -> list[SensorEvent]:
        with self._lock:
            if limit <= 0:
                return []
            return list(self._events)[-limit:]

    def count(self) -> int:
        with self._lock:
            return len(self._events)


event_store = SensorEventStore()
