#!/usr/bin/env bash
# Run the fake greenhouse against a minimal no-Docker Pomona stack (Core with its outcome feed,
# model-router, automation-engine) in real time, then grade what Pomona raised against the truth log.
#   SCENARIO=...  scenario JSON (default: scenarios/quick.json, about 28 minutes at INTERVAL=30)
#   INTERVAL=30   seconds between ticks (real time: the alert debounce windows are in sample time)
#   CONTROL_PORT=8090  also serve the control page while it runs
#   OUT_DIR=...   where truth log, JSON and markdown reports go (default data/fake_greenhouse, gitignored)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCENARIO="${SCENARIO:-${ROOT_DIR}/examples/simulators/scenarios/quick.json}"
INTERVAL="${INTERVAL:-30}"
CONTROL_PORT="${CONTROL_PORT:-}"
OUT_DIR="${OUT_DIR:-${ROOT_DIR}/data/fake_greenhouse}"
CORE_PORT="${FG_CORE_PORT:-18190}"
ROUTER_PORT="${FG_ROUTER_PORT:-18191}"
AUTOMATION_ENGINE_PORT="${FG_AUTOMATION_PORT:-18195}"
PY_CORE="${PY_CORE:-${ROOT_DIR}/services/core/.venv/bin/python}"
PY_ROUTER="${PY_ROUTER:-${ROOT_DIR}/services/model-router/.venv/bin/python}"
PY_AUTOMATION_ENGINE="${PY_AUTOMATION_ENGINE:-${ROOT_DIR}/services/automation-engine/.venv/bin/python}"
TMP_DIR="$(mktemp -d /tmp/pomona-fake-greenhouse.XXXXXX)"

for python in "${PY_CORE}" "${PY_ROUTER}" "${PY_AUTOMATION_ENGINE}"; do
  if [[ ! -x "${python}" ]]; then
    echo "Missing Python environment: ${python}" >&2
    exit 1
  fi
done

cleanup() {
  kill "${CORE_PID:-}" "${ROUTER_PID:-}" "${AUTOMATION_ENGINE_PID:-}" 2>/dev/null || true
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

PYTHONPATH="${ROOT_DIR}/services/core" DB_PATH="${TMP_DIR}/pomona.db" MQTT_HOST=127.0.0.1 \
  MODEL_ROUTER_URL="http://127.0.0.1:${ROUTER_PORT}" AUTOMATION_ENGINE_URL="http://127.0.0.1:${AUTOMATION_ENGINE_PORT}" \
  "${PY_CORE}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/core" \
  --host 127.0.0.1 --port "${CORE_PORT}" >"${TMP_DIR}/core.log" 2>&1 &
CORE_PID=$!
PYTHONPATH="${ROOT_DIR}/services/model-router" AUDIT_LOG_PATH="${TMP_DIR}/pipeline-audit.jsonl" \
  "${PY_ROUTER}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/model-router" \
  --host 127.0.0.1 --port "${ROUTER_PORT}" >"${TMP_DIR}/router.log" 2>&1 &
ROUTER_PID=$!
PYTHONPATH="${ROOT_DIR}/services/automation-engine" AUTOMATION_DB_PATH="${TMP_DIR}/automation.db" \
  "${PY_AUTOMATION_ENGINE}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/automation-engine" \
  --host 127.0.0.1 --port "${AUTOMATION_ENGINE_PORT}" >"${TMP_DIR}/automation-engine.log" 2>&1 &
AUTOMATION_ENGINE_PID=$!

for url in "http://127.0.0.1:${CORE_PORT}/health" "http://127.0.0.1:${ROUTER_PORT}/health" \
           "http://127.0.0.1:${AUTOMATION_ENGINE_PORT}/health"; do
  for attempt in $(seq 1 30); do
    if curl -fsS "${url}" >/dev/null 2>&1; then break; fi
    if [[ "${attempt}" == 30 ]]; then
      echo "Service did not become ready: ${url}" >&2
      cat "${TMP_DIR}"/*.log >&2
      exit 1
    fi
    sleep 1
  done
done

mkdir -p "${OUT_DIR}"
SIM_ARGS=(--core-url "http://127.0.0.1:${CORE_PORT}" --scenario "${SCENARIO}" --interval "${INTERVAL}"
          --truth-log "${OUT_DIR}/truth.jsonl")
if [[ -n "${CONTROL_PORT}" ]]; then
  SIM_ARGS+=(--control-port "${CONTROL_PORT}")
fi
echo "Running ${SCENARIO} at ${INTERVAL}s per tick (real time; Ctrl+C stops, then grade with the printed commands)"
"${PY_CORE}" -u "${ROOT_DIR}/examples/simulators/fake_greenhouse.py" "${SIM_ARGS[@]}" 2>&1 | tee "${OUT_DIR}/sim.log"

echo "Waiting for Core's outcome feed to finish"
sleep 5

"${PY_CORE}" "${ROOT_DIR}/scripts/score_fake_greenhouse.py" --truth "${OUT_DIR}/truth.jsonl" \
  --automation-url "http://127.0.0.1:${AUTOMATION_ENGINE_PORT}" --core-url "http://127.0.0.1:${CORE_PORT}" \
  --json "${OUT_DIR}/score_stack.json" --report "${OUT_DIR}/report_stack.md"
"${PY_ROUTER}" "${ROOT_DIR}/scripts/score_fake_greenhouse.py" --truth "${OUT_DIR}/truth.jsonl" --offline \
  --json "${OUT_DIR}/score_offline.json" --report "${OUT_DIR}/report_offline.md"

echo
echo "Truth log (answer key): ${OUT_DIR}/truth.jsonl"
echo "Report, running stack:  ${OUT_DIR}/report_stack.md  (${OUT_DIR}/score_stack.json)"
echo "Report, offline replay: ${OUT_DIR}/report_offline.md  (${OUT_DIR}/score_offline.json)"
