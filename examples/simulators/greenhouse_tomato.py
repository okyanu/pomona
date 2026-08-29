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

# Zone-level context for the model-router's FAO-56/NPK calculator
# (services/model-router/app/agronomy_calc.py). Unlike the per-tick sensor
# readings below, these change slowly in real life (daily weather, fixed
# greenhouse geometry, a per-stage nutrient recipe), so the simulator holds
# them roughly steady and only jitters them slightly per reading.
ZONE_AREA_M2 = float(os.getenv("SIM_ZONE_AREA_M2", "20"))
CROP_KC = float(os.getenv("SIM_CROP_KC", "1.15"))  # FAO-56 Kc for tomato, mid-season
NPK_TARGET = {
    "n_ppm": float(os.getenv("SIM_NPK_N_PPM", "150")),
    "p_ppm": float(os.getenv("SIM_NPK_P_PPM", "50")),
    "k_ppm": float(os.getenv("SIM_NPK_K_PPM", "200")),
    "volume_liters": float(os.getenv("SIM_NPK_VOLUME_LITERS", "100")),
}


def build_weather() -> dict:
    t_mean = round(random.uniform(24.0, 31.0), 1)
    return {
        "t_mean_c": t_mean,
        "t_min_c": round(t_mean - random.uniform(3.0, 6.0), 1),
        "t_max_c": round(t_mean + random.uniform(3.0, 6.0), 1),
        "rh_mean_pct": round(random.uniform(55.0, 80.0), 1),
        "wind_speed_2m_ms": round(random.uniform(0.5, 3.0), 2),
        "solar_radiation_mj_m2_day": round(random.uniform(12.0, 22.0), 1),
        "elevation_m": float(os.getenv("SIM_ELEVATION_M", "300")),
    }


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
        "weather": build_weather(),
        "zone_area_m2": ZONE_AREA_M2,
        "crop_kc": CROP_KC,
        "npk_target": NPK_TARGET,
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
