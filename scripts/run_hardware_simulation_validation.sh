#!/usr/bin/env bash
set -euo pipefail

# Publish observation-only ESP32-shaped packets into a running local stack.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_URL="${CORE_URL:-http://127.0.0.1:8080}"
ROUTER_URL="${ROUTER_URL:-http://127.0.0.1:8081}"
DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:3000}"
PYTHON="${PYTHON:-${ROOT_DIR}/services/core/.venv/bin/python}"

if [[ ! -x "${PYTHON}" ]]; then PYTHON="python3"; fi

wait_for_health() {
  local url="$1"
  for _ in {1..30}; do
    if curl -fsS "${url}/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Service did not become ready: ${url}" >&2
  return 1
}

wait_for_health "${CORE_URL}"
wait_for_health "${ROUTER_URL}"
wait_for_health "${DASHBOARD_URL}"

DEVICE_ID="hardware-validation-$(date +%s)"
export DEVICE_ID
export MQTT_HOST="${MQTT_HOST:-127.0.0.1}"
export MQTT_PORT="${MQTT_PORT:-1883}"

"${PYTHON}" - <<'PY'
import json
import os
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

device_id = os.environ["DEVICE_ID"]
topic = f"pomona/demo-farm/greenhouse-a/sensor/{device_id}/state"
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.connect(os.environ["MQTT_HOST"], int(os.environ["MQTT_PORT"]), keepalive=30)
client.loop_start()
timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
packets = [
    {"air_temperature_c": 25.0, "humidity_pct": 64.0, "ec_ms_cm": 2.0, "ph": 6.1, "soil_moisture_pct": 50.0},
    {"air_temperature_c": 31.0, "humidity_pct": 86.0, "ec_ms_cm": 3.8, "ph": 5.2, "soil_moisture_pct": 24.0},
]
for values in packets:
    payload = {
        "device_id": device_id,
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "crop": "tomato",
        "growth_stage": "fruiting",
        "system_type": "greenhouse_substrate",
        "timestamp": timestamp,
        "source": "hardware-validation",
        **values,
    }
    info = client.publish(topic, json.dumps(payload), qos=0)
    info.wait_for_publish()
    print(f"published observation packet moisture={values['soil_moisture_pct']}")
    time.sleep(0.5)
client.loop_stop()
client.disconnect()
PY

latest=""
for _ in {1..20}; do
  latest="$(curl -fsS "${CORE_URL}/v1/sensors/events/latest")"
  if DEVICE_ID="${DEVICE_ID}" python3 -c 'import json, os, sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("device_id")==os.environ["DEVICE_ID"] else 1)' <<<"${latest}"; then break; fi
  sleep 1
done
DEVICE_ID="${DEVICE_ID}" python3 -c 'import json, os, sys; d=json.load(sys.stdin); assert d["device_id"] == os.environ["DEVICE_ID"]; assert d["source"] == "hardware-validation"; assert d["soil_moisture_pct"] == 24.0' <<<"${latest}"

pipeline="$(curl -fsS "${DASHBOARD_URL}/api/pipeline")"
python3 -c 'import json, sys; d=json.load(sys.stdin); assert d["available"] is True; assert d["result"]["final_decision"]["human_review_required"] is True; print("Dashboard guarded pipeline: verified")' <<<"${pipeline}"

dry_run="$(curl -fsS -X POST "${ROUTER_URL}/v1/actuator-commands/dry-run" -H 'Content-Type: application/json' -d '{"actor":"hardware-validation","input":{"farm_context":{"crop":"tomato","system_type":"greenhouse_substrate"},"sensor":{"soil_moisture_pct":24.0},"risk_labels":["low_moisture"],"proposed_command":{"action_type":"start_irrigation"}}}')"
python3 -c 'import json, sys; d=json.load(sys.stdin); assert d["dry_run"] is True; assert d["execution_performed"] is False; assert d["decision"] == "blocked"; print("Dry-run actuator gate: verified")' <<<"${dry_run}"

echo "Hardware simulation validation passed for ${DEVICE_ID}."
echo "Only MQTT observation packets were published; no actuator command was executed."
