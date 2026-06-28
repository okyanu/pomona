#!/usr/bin/env bash
# Start full Pomona stack with Docker (macOS, Linux, Windows with Docker Desktop).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
fi

if docker compose version >/dev/null 2>&1; then
  docker compose up -d --build "$@"
elif command -v docker-compose >/dev/null 2>&1; then
  docker-compose up -d --build "$@"
else
  echo "ERROR: docker compose not found. Install Docker Desktop."
  exit 1
fi

echo ""
echo "Pomona is starting."
echo "  Core API:     http://localhost:8080/health"
echo "  Model router: http://localhost:8081/health"
echo "  MQTT:         localhost:1883"
echo ""
echo "Next (new terminal):"
echo "  ./scripts/sim.sh"
echo "  curl http://localhost:8080/health"
