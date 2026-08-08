#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${PORT:-8081}"
PYTHON="${PYTHON:-${ROOT_DIR}/services/model-router/.venv/bin/python}"

if [[ ! -x "${PYTHON}" ]]; then
  PYTHON="python3"
fi

echo "Starting Pomona model-router on port ${PORT}"
PYTHONPATH="${ROOT_DIR}/services/model-router" "${PYTHON}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/model-router" --host 127.0.0.1 --port "${PORT}" >/tmp/pomona-model-router-validation.log 2>&1 &
SERVER_PID=$!
trap 'kill "${SERVER_PID}" 2>/dev/null || true' EXIT

for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then break; fi
  sleep 1
done
if ! curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
  echo "Model-router did not start; log follows:" >&2
  cat /tmp/pomona-model-router-validation.log >&2
  exit 1
fi

for scenario in "${ROOT_DIR}"/examples/scenarios/*.json; do
  echo "\n=== ${scenario##*/} ==="
  python3 "${ROOT_DIR}/scripts/resolve_scenario.py" "${scenario}" | curl -fsS "http://127.0.0.1:${PORT}/v1/pipeline/evaluate" \
    -H 'Content-Type: application/json' \
    --data-binary @-
  echo
done

python3 "${ROOT_DIR}/scripts/benchmark_software_validation.py" \
  --base-url "http://127.0.0.1:${PORT}"

echo "\nAudit log: ${ROOT_DIR}/data/pomona-pipeline-audit.jsonl"
