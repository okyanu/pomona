import json
import sqlite3
from threading import Lock
from pathlib import Path
from typing import Optional

from app.config import settings
from app.schemas import SensorEvent


class SensorEventStore:
    def __init__(self, max_events: Optional[int] = None) -> None:
        self._max_events = max_events or settings.max_events
        self._lock = Lock()
        self._db_path = Path(settings.db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sensor_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    payload TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def add(self, event: SensorEvent) -> None:
        with self._lock:
            payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
            with self._connect() as connection:
                connection.execute(
                    "INSERT INTO sensor_events (timestamp, payload) VALUES (?, ?)",
                    (event.timestamp.isoformat(), payload),
                )
                connection.execute(
                    """
                    DELETE FROM sensor_events
                    WHERE id NOT IN (
                        SELECT id FROM sensor_events ORDER BY id DESC LIMIT ?
                    )
                    """,
                    (self._max_events,),
                )

    def list_events(self, limit: int = 50) -> list[SensorEvent]:
        with self._lock:
            if limit <= 0:
                return []
            with self._connect() as connection:
                rows = connection.execute(
                    "SELECT payload FROM sensor_events ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [SensorEvent.model_validate(json.loads(row["payload"])) for row in reversed(rows)]

    def count(self) -> int:
        with self._lock:
            with self._connect() as connection:
                return int(connection.execute("SELECT COUNT(*) FROM sensor_events").fetchone()[0])

    def clear(self) -> None:
        with self._lock:
            with self._connect() as connection:
                connection.execute("DELETE FROM sensor_events")


event_store = SensorEventStore()
