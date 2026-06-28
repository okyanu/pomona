import json
import logging
from typing import Any, Callable, Optional

try:
    import paho.mqtt.client as mqtt
except ModuleNotFoundError:
    mqtt = None  # type: ignore[assignment]

from app.config import settings
from app.schemas import SensorEvent
from app.store import event_store

logger = logging.getLogger(__name__)


class MqttIngestClient:
    def __init__(self, on_event: Optional[Callable[[SensorEvent], None]] = None) -> None:
        self._on_event = on_event or self._default_handler
        self._client: Any = None
        if mqtt is not None:
            self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            self._client.on_connect = self._on_connect
            self._client.on_message = self._on_message
        self.connected = False

    def _on_connect(
        self,
        client: Any,
        userdata: object,
        flags: Any,
        reason_code: Any,
        properties: Optional[Any] = None,
    ) -> None:
        if reason_code.is_failure:
            logger.error("MQTT connect failed: %s", reason_code)
            self.connected = False
            return

        self.connected = True
        client.subscribe(settings.mqtt_topic_pattern)
        logger.info(
            "MQTT connected to %s:%s, subscribed to %s",
            settings.mqtt_host,
            settings.mqtt_port,
            settings.mqtt_topic_pattern,
        )

    def _on_message(
        self,
        client: Any,
        userdata: object,
        message: Any,
    ) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            event = SensorEvent.model_validate(payload)
            event.source = event.source or "mqtt"
            self._on_event(event)
        except Exception:
            logger.exception("Failed to process MQTT message on topic %s", message.topic)

    def _default_handler(self, event: SensorEvent) -> None:
        event_store.add(event)
        logger.info(
            "sensor event device=%s farm=%s zone=%s ph=%.2f ec=%.2f temp=%.1f humidity=%.0f",
            event.device_id,
            event.farm_id,
            event.zone_id,
            event.ph,
            event.ec_ms_cm,
            event.air_temperature_c,
            event.humidity_pct,
        )

    def start(self) -> None:
        if self._client is None:
            logger.warning("paho-mqtt is not installed; MQTT ingest disabled")
            self.connected = False
            return

        try:
            self._client.connect_async(settings.mqtt_host, settings.mqtt_port, keepalive=60)
            self._client.loop_start()
        except Exception:
            logger.exception(
                "MQTT client failed to start (host=%s port=%s); HTTP ingest still available",
                settings.mqtt_host,
                settings.mqtt_port,
            )
            self.connected = False

    def stop(self) -> None:
        if self._client is None:
            self.connected = False
            return

        self._client.loop_stop()
        self._client.disconnect()
        self.connected = False


mqtt_client = MqttIngestClient()
