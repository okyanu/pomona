#!/usr/bin/env bash
# Run the Pomona validation stack without Docker.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_PORT="${CORE_PORT:-18080}"
ROUTER_PORT="${ROUTER_PORT:-18081}"
DASHBOARD_PORT="${DASHBOARD_PORT:-13000}"
SAFETY_PORT="${SAFETY_PORT:-18082}"
DIGITAL_TWIN_PORT="${DIGITAL_TWIN_PORT:-18084}"
PY_CORE="${PY_CORE:-${ROOT_DIR}/services/core/.venv/bin/python}"
PY_ROUTER="${PY_ROUTER:-${ROOT_DIR}/services/model-router/.venv/bin/python}"
PY_DASHBOARD="${PY_DASHBOARD:-${ROOT_DIR}/services/core/.venv/bin/python}"
PY_SAFETY="${PY_SAFETY:-${ROOT_DIR}/services/core/.venv/bin/python}"
PY_DIGITAL_TWIN="${PY_DIGITAL_TWIN:-${ROOT_DIR}/services/core/.venv/bin/python}"
TMP_DIR="$(mktemp -d /tmp/pomona-local-validation.XXXXXX)"
DB_PATH="${TMP_DIR}/pomona.db"

for python in "${PY_CORE}" "${PY_ROUTER}" "${PY_DASHBOARD}" "${PY_SAFETY}" "${PY_DIGITAL_TWIN}"; do
  if [[ ! -x "${python}" ]]; then
    echo "Missing Python environment: ${python}" >&2
    exit 1
  fi
done

cleanup() {
  kill "${CORE_PID:-}" "${ROUTER_PID:-}" "${DASHBOARD_PID:-}" "${SAFETY_PID:-}" "${DIGITAL_TWIN_PID:-}" 2>/dev/null || true
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

echo "Starting local validation stack"
start_core() {
  PYTHONPATH="${ROOT_DIR}/services/core" DB_PATH="${DB_PATH}" MQTT_HOST=127.0.0.1 \
    "${PY_CORE}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/core" \
    --host 127.0.0.1 --port "${CORE_PORT}" >"${TMP_DIR}/core.log" 2>&1 &
  CORE_PID=$!
}

start_core

PYTHONPATH="${ROOT_DIR}/services/model-router" \
AUDIT_LOG_PATH="${TMP_DIR}/pipeline-audit.jsonl" \
  "${PY_ROUTER}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/model-router" \
  --host 127.0.0.1 --port "${ROUTER_PORT}" >"${TMP_DIR}/router.log" 2>&1 &
ROUTER_PID=$!

PYTHONPATH="${ROOT_DIR}/services/safety-checker" \
  "${PY_SAFETY}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/safety-checker" \
  --host 127.0.0.1 --port "${SAFETY_PORT}" >"${TMP_DIR}/safety.log" 2>&1 &
SAFETY_PID=$!

PYTHONPATH="${ROOT_DIR}/services/digital-twin" \
  "${PY_DIGITAL_TWIN}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/digital-twin" \
  --host 127.0.0.1 --port "${DIGITAL_TWIN_PORT}" >"${TMP_DIR}/digital-twin.log" 2>&1 &
DIGITAL_TWIN_PID=$!

CORE_URL="http://127.0.0.1:${CORE_PORT}" \
MODEL_ROUTER_URL="http://127.0.0.1:${ROUTER_PORT}" \
SAFETY_CHECKER_URL="http://127.0.0.1:${SAFETY_PORT}" \
DIGITAL_TWIN_URL="http://127.0.0.1:${DIGITAL_TWIN_PORT}" \
  "${PY_DASHBOARD}" -m uvicorn app.main:app --app-dir "${ROOT_DIR}/services/dashboard" \
  --host 127.0.0.1 --port "${DASHBOARD_PORT}" >"${TMP_DIR}/dashboard.log" 2>&1 &
DASHBOARD_PID=$!

wait_for() {
  local url="$1"
  for _ in $(seq 1 30); do
    if curl -fsS "${url}" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  echo "Service did not become ready: ${url}" >&2
  cat "${TMP_DIR}"/*.log >&2
  return 1
}

wait_for "http://127.0.0.1:${CORE_PORT}/health"
wait_for "http://127.0.0.1:${ROUTER_PORT}/health"
wait_for "http://127.0.0.1:${SAFETY_PORT}/health"
wait_for "http://127.0.0.1:${DIGITAL_TWIN_PORT}/health"
wait_for "http://127.0.0.1:${DASHBOARD_PORT}/health"

curl -fsS -X POST "http://127.0.0.1:${CORE_PORT}/v1/sensors/events" \
  -H 'Content-Type: application/json' \
  -d '{"device_id":"local-validation-01","farm_id":"demo-farm","zone_id":"greenhouse-a","crop":"tomato","growth_stage":"fruiting","air_temperature_c":33.0,"humidity_pct":80.0,"ec_ms_cm":3.8,"ph":5.2,"soil_moisture_pct":27.0,"timestamp":"2026-07-20T10:00:00Z","source":"local-validation"}' \
  >"${TMP_DIR}/event.json"

kill "${CORE_PID}" 2>/dev/null || true
wait "${CORE_PID}" 2>/dev/null || true
start_core
wait_for "http://127.0.0.1:${CORE_PORT}/health"
curl -fsS "http://127.0.0.1:${CORE_PORT}/v1/sensors/events/latest" >"${TMP_DIR}/restarted-event.json"

curl -fsS "http://127.0.0.1:${DASHBOARD_PORT}/api/pipeline" >"${TMP_DIR}/pipeline.json"
curl -fsS "http://127.0.0.1:${DASHBOARD_PORT}/api/audit" >"${TMP_DIR}/audit.json"
curl -fsS "http://127.0.0.1:${DASHBOARD_PORT}/api/services" >"${TMP_DIR}/services.json"
curl -fsS "http://127.0.0.1:${DASHBOARD_PORT}/api/runtimes" >"${TMP_DIR}/runtimes.json"
curl -fsS "http://127.0.0.1:${DASHBOARD_PORT}/" >"${TMP_DIR}/dashboard.html"
curl -fsS -X POST "http://127.0.0.1:${SAFETY_PORT}/v1/actuator-command-gate/check" \
  -H 'Content-Type: application/json' \
  -d '{"input":{"farm_context":{"crop":"tomato","system_type":"greenhouse_substrate"},"sensor":{"humidity_pct":80.0},"sensor_quality":{"data_quality_labels":["missing_ph"],"missing_fields":["ph"]},"risk_labels":["missing_critical_data"],"actor":"automation_engine","proposed_command":{"action_type":"start_irrigation"}}}' \
  >"${TMP_DIR}/safety.json"
curl -fsS -X POST "http://127.0.0.1:${ROUTER_PORT}/v1/pipeline/evaluate" \
  -H 'Content-Type: application/json' \
  -d '{"scenario_id":"local-validation-lettuce-normal","farm_context":{"crop":"lettuce","system_type":"hydroponic","zone_id":"rack-1"},"sensor":{"air_temperature_c":21.0,"humidity_pct":64.0,"ph":6.1,"ec_ms_cm":1.8,"water_temperature_c":20.0},"expected_fields":["air_temperature_c","humidity_pct","ph","ec_ms_cm","water_temperature_c"],"proposed_command":{"action_type":"continue_monitoring"},"actor":"local_validation","mode":"hybrid_guarded"}' \
  >"${TMP_DIR}/normal.json"

"${PY_CORE}" - "${TMP_DIR}/pipeline.json" "${TMP_DIR}/audit.json" "${TMP_DIR}/safety.json" "${TMP_DIR}/services.json" "${TMP_DIR}/runtimes.json" "${TMP_DIR}/normal.json" "${TMP_DIR}/dashboard.html" "${TMP_DIR}/restarted-event.json" <<'PY'
import json
import sys
from pathlib import Path

pipeline = json.loads(Path(sys.argv[1]).read_text())
audit = json.loads(Path(sys.argv[2]).read_text())
safety = json.loads(Path(sys.argv[3]).read_text())
services = json.loads(Path(sys.argv[4]).read_text())
runtimes = json.loads(Path(sys.argv[5]).read_text())
normal = json.loads(Path(sys.argv[6]).read_text())
dashboard = Path(sys.argv[7]).read_text()
restarted_event = json.loads(Path(sys.argv[8]).read_text())
assert pipeline["available"] is True
decision = pipeline["result"]["final_decision"]
assert decision["human_review_required"] is True
assert decision["blocked_actions"]
assert audit["available"] is True
assert audit["result"]["events"]
assert all("sensor" not in event for event in audit["result"]["events"])
assert safety["decision"] == "blocked"
assert "direct_actuator_control" in safety["blocked_actions"]
assert all(item["available"] for item in services["services"].values())
assert runtimes["available"] is True
assert runtimes["result"]["rules"]["available"] is True
assert normal["final_decision"]["risk_level"] == "routine"
assert normal["final_decision"]["blocked_actions"] == []
assert normal["final_decision"]["human_review_required"] is False
assert "Integrated guarded pipeline" in dashboard
assert "Recent pipeline audit" in dashboard
assert "Read-only dashboard view" in dashboard
assert restarted_event["device_id"] == "local-validation-01"
print("Local validation passed")
print("Pipeline:", pipeline["result"]["pipeline_id"])
print("Risk:", decision["risk_level"])
print("Blocked:", ", ".join(decision["blocked_actions"]))
print("Audit summaries:", audit["result"]["count"])
print("Safety gate:", safety["decision"])
print("Services online:", ", ".join(services["services"]))
print("Rules runtime:", runtimes["result"]["rules"]["available"])
print("Normal path: routine")
print("Dashboard HTML: verified")
print("SQLite restart recovery: verified")
PY
