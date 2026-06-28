#!/usr/bin/env bash
# Run core + model-router on host with pip (MQTT broker must already run).
#
# Typical: ./scripts/up.sh mqtt   then   ./scripts/run-local.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
export MQTT_HOST="${MQTT_HOST:-localhost}"
export MQTT_PORT="${MQTT_PORT:-1883}"
export MODELS_DIR="${MODELS_DIR:-${ROOT}/models/registry}"
export POMONA_LLM_BACKEND="${POMONA_LLM_BACKEND:-stub}"

if [[ ! -f .env ]]; then
  cp .env.example .env
fi
# shellcheck disable=SC1091
set -a && source .env && set +a
export MQTT_HOST=localhost  # host always uses localhost when broker is in Docker

"$PYTHON" -m pip install -q -r requirements-dev.txt

CORE_PID=""
ROUTER_PID=""
cleanup() {
  [[ -n "$CORE_PID" ]] && kill "$CORE_PID" 2>/dev/null || true
  [[ -n "$ROUTER_PID" ]] && kill "$ROUTER_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting pomona-core on :8080 ..."
(cd services/core && PYTHONPATH=. "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8080) &
CORE_PID=$!

echo "Starting model-router on :8081 ..."
(cd services/model-router && PYTHONPATH=. MODELS_DIR="$MODELS_DIR" "$PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port 8081) &
ROUTER_PID=$!

sleep 2
echo ""
echo "Local services running (Ctrl+C to stop)."
echo "  Core:   http://localhost:8080/health"
echo "  Router: http://localhost:8081/health"
echo ""
echo "Run simulator: ./scripts/sim.sh"

wait
