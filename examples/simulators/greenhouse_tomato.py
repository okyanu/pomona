#!/usr/bin/env python3
"""Publish simulated greenhouse tomato sensor readings to MQTT."""

from __future__ import annotations

import json
import os
import random
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

FARM_ID = os.getenv("SIM_FARM_ID", "demo-farm")
ZONE_ID = os.getenv("SIM_ZONE_ID", "greenhouse-a")
DEVICE_ID = os.getenv("SIM_DEVICE_ID", "sim-greenhouse-01")
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
INTERVAL_SEC = float(os.getenv("SIM_INTERVAL_SEC", "5"))
TOPIC = f"pomona/{FARM_ID}/{ZONE_ID}/sensor/{DEVICE_ID}/state"


def build_reading() -> dict:
    air_temperature_c = round(random.uniform(22.0, 34.0), 1)
    soil_moisture_pct = round(random.uniform(30.0, 70.0), 1)
    return {
        "device_id": DEVICE_ID,
        "farm_id": FARM_ID,
        "zone_id": ZONE_ID,
        "crop": "tomato",
        "growth_stage": "flowering",
        "system_type": "greenhouse_substrate",
        "air_temperature_c": air_temperature_c,
        "humidity_pct": round(random.uniform(55.0, 92.0), 1),
        "ec_ms_cm": round(random.uniform(1.8, 4.2), 2),
        "ph": round(random.uniform(5.5, 7.8), 2),
        "soil_moisture_pct": soil_moisture_pct,
        # greenhouse_substrate is a critical-fields system type for the
        # tomato reasoner (see services/model-router/app/tomato_reasoner.py);
        # without these two, every reading is flagged missing_critical_data.
        "substrate_temperature_c": round(air_temperature_c - random.uniform(0.5, 2.5), 1),
        "substrate_moisture_pct": soil_moisture_pct,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "simulator",
    }


def main() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_start()

    print(f"Publishing to {TOPIC} every {INTERVAL_SEC}s (Ctrl+C to stop)")

    try:
        while True:
            reading = build_reading()
            client.publish(TOPIC, json.dumps(reading), qos=0)
            print(
                f"published ph={reading['ph']} ec={reading['ec_ms_cm']} "
                f"temp={reading['air_temperature_c']} humidity={reading['humidity_pct']}"
            )
            time.sleep(INTERVAL_SEC)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
