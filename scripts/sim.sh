#!/usr/bin/env bash
# Run greenhouse sensor simulator (works on any OS with Python 3).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
MQTT_HOST="${MQTT_HOST:-localhost}"
MQTT_PORT="${MQTT_PORT:-1883}"

"$PYTHON" -m pip install -q -r examples/simulators/requirements.txt 2>/dev/null || true

echo "Publishing to MQTT at ${MQTT_HOST}:${MQTT_PORT} (Ctrl+C to stop)"
MQTT_HOST="$MQTT_HOST" MQTT_PORT="$MQTT_PORT" "$PYTHON" examples/simulators/greenhouse_tomato.py
