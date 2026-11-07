#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# Compose refuses to read the file without MQTT_PASSWORD; stopping containers needs no real password.
export MQTT_PASSWORD="${MQTT_PASSWORD:-unused-by-down}"

if docker compose version >/dev/null 2>&1; then
  docker compose down "$@"
else
  docker-compose down "$@"
fi
