#!/usr/bin/env bash
set -euo pipefail

# Run the complete software-only safety contract before connecting hardware.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-18081}"
PYTHON="${PYTHON:-${ROOT_DIR}/services/model-router/.venv/bin/python}"

if [[ ! -x "${PYTHON}" ]]; then PYTHON="python3"; fi

echo "Starting Pomona pre-hardware validation on port ${PORT}"
PYTHONPATH="${ROOT_DIR}/services/model-router" "${PYTHON}" -m uvicorn app.main:app \
  --app-dir "${ROOT_DIR}/services/model-router" --host 127.0.0.1 --port "${PORT}" \
  >/tmp/pomona-pre-hardware-validation.log 2>&1 &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT

for _ in {1..30}; do
  curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null || {
  cat /tmp/pomona-pre-hardware-validation.log >&2
  exit 1
}

"${PYTHON}" "${ROOT_DIR}/scripts/benchmark_software_validation.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --scenarios "examples/scenarios/*.json" \
  --output "private/colab/outputs/pre_hardware_validation.json"

"${PYTHON}" "${ROOT_DIR}/scripts/capture_article_scenarios.py" \
  --base-url "http://127.0.0.1:${PORT}" \
  --output "private/colab/outputs/article_scenarios.json"

echo "Pre-hardware validation passed: all scenario contracts matched."
echo "This validates software behavior only; no actuator or hardware command was executed."
