#!/usr/bin/env bash
# Start full Pomona stack with Docker (macOS, Linux, Windows with Docker Desktop).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi
# shellcheck disable=SC1091
. "$ROOT/scripts/mqtt-env.sh"
ensure_mqtt_password .env  # the broker requires a login; a blank MQTT_PASSWORD gets a random one

if docker compose version >/dev/null 2>&1; then
  COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE=(docker-compose)
else
  echo "ERROR: docker compose not found. Install Docker Desktop."
  exit 1
fi

"${COMPOSE[@]}" build "$@"
# Services run as uid 10001. Volumes created by older, root-run versions hold root-owned
# files; hand them to that user once (idempotent, touches only Pomona's own volumes).
for pair in core:/app/data model-router:/app/data automation-engine:/data; do
  service="${pair%%:*}"; dir="${pair#*:}"
  "${COMPOSE[@]}" run --rm --no-deps -T --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE \
    --cap-add FOWNER --entrypoint chown "$service" -R 10001:10001 "$dir" >/dev/null
done
"${COMPOSE[@]}" up -d "$@"

echo ""
echo "Pomona is starting."
echo "  Core API:     http://localhost:8080/health"
echo "  Model router: http://localhost:8081/health"
echo "  MQTT:         localhost:1883 (login required: MQTT_USERNAME / MQTT_PASSWORD in .env)"
echo ""
echo "Next (new terminal):"
echo "  ./scripts/sim.sh"
echo "  curl http://localhost:8080/health"
