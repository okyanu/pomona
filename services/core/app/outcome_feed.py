"""Advisory outcome feed: forward each new full packet for rules-only evaluation and alert tracking.

Core posts the reading to model-router (/v1/pipeline/evaluate, rules_only) and then the resulting
labels to automation-engine (/v1/automation/alerts/observe), so approved-suggestion outcomes and
alerts move even when no dashboard is open. Suggestions only: no actuator path. A background
worker with a bounded queue keeps ingest independent of both services; failures are only logged.
"""
import json
import logging
import queue
import threading
import time
import urllib.request
from typing import Any, Dict, List, Optional

from app.config import settings
from app.schemas import SensorEvent
from app.store import SensorEventStore, event_store

logger = logging.getLogger(__name__)

HISTORY_LIMIT = 12
TIMEOUT_SECONDS = 5.0


def pipeline_risk_labels(result: Dict[str, Any]) -> List[str]:
    return list(dict.fromkeys([
        *(result.get("sensor_quality") or {}).get("data_quality_labels", []),
        *(result.get("water_irrigation") or {}).get("irrigation_risk_labels", []),
        *(result.get("nutrient_ph_ec") or {}).get("nutrient_risk_labels", []),
        *(result.get("crop_risk") or {}).get("risk_labels", []),
    ]))


def _post(base_url: str, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
    if not base_url.startswith(("http://", "https://")):
        raise ValueError(f"unsupported feed URL {base_url!r}")
    request = urllib.request.Request(base_url.rstrip("/") + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (http/https checked above)
        return json.loads(response.read() or b"{}")


class OutcomeFeed:
    def __init__(self, store: Optional[SensorEventStore] = None, queue_size: Optional[int] = None) -> None:
        self._store = store or event_store
        self._queue: "queue.Queue[SensorEvent]" = queue.Queue(maxsize=queue_size or settings.outcome_feed_queue_size)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_drop_log = 0.0
        self.dropped = 0

    @property
    def enabled(self) -> bool:
        return bool(settings.model_router_url and settings.automation_engine_url)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="outcome-feed", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=TIMEOUT_SECONDS * 2 + 1)
            self._thread = None
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def submit(self, event: SensorEvent) -> None:
        """Queue one stored reading. Never blocks and never raises; a full queue drops and counts."""
        if not self.enabled:
            return
        try:
            self._queue.put_nowait(event.model_copy(deep=True))
        except queue.Full:
            self.dropped += 1
            now = time.monotonic()
            if now - self._last_drop_log >= 60:
                self._last_drop_log = now
                logger.warning("outcome feed queue full; %d reading(s) dropped so far", self.dropped)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                event = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                self._process(event)
            except Exception as exc:
                logger.warning("outcome feed failed for device=%s farm=%s zone=%s: %s",
                               event.device_id, event.farm_id, event.zone_id, exc)

    def _history(self, event: SensorEvent) -> List[Dict[str, Any]]:
        """Prior-only packets for the same farm/zone, oldest first: what the dashboard sends (newest 12
        minus the latest = 11), taken relative to this reading so a backed-up queue cannot shrink it."""
        history = []
        for item in self._store.prior_events(event, HISTORY_LIMIT - 1):
            packet = item.model_dump(mode="json")
            for name in ("source", "received_at", "mqtt_retained"):
                packet.pop(name, None)
            history.append(packet)
        return history

    def _process(self, event: SensorEvent) -> None:
        sensor = event.model_dump(mode="json")
        sensor.pop("source", None)
        result = _post(settings.model_router_url, "/v1/pipeline/evaluate", {
            "scenario_id": "core_feed",
            "farm_context": {
                "crop": sensor.get("crop", "tomato"),
                "system_type": sensor.get("system_type", "greenhouse_substrate"),
                "zone_id": sensor.get("zone_id", "unknown"),
                "weather": sensor.get("weather"),
                "zone_area_m2": sensor.get("zone_area_m2"),
                "crop_kc": sensor.get("crop_kc"),
                "npk_target": sensor.get("npk_target"),
            },
            "sensor": sensor,
            "history": self._history(event),
            "proposed_command": {"action_type": "continue_monitoring"},
            "actor": "core_feed",
            "mode": "rules_only",
        })
        _post(settings.automation_engine_url, "/v1/automation/alerts/observe", {
            "farm_id": event.farm_id, "zone_id": event.zone_id, "device_id": event.device_id,
            "sample_time": sensor["timestamp"], "risk_labels": pipeline_risk_labels(result),
            "data_quality_labels": (result.get("sensor_quality") or {}).get("data_quality_labels", [])})


outcome_feed = OutcomeFeed()
