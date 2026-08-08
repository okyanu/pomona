#!/usr/bin/env bash
set -euo pipefail

# Validate backup, Core restart recovery, and non-destructive restore on Docker.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORE_URL="${CORE_URL:-http://127.0.0.1:8080}"
PYTHON="${PYTHON:-${ROOT_DIR}/services/core/.venv/bin/python}"
TMP_DIR="$(mktemp -d /tmp/pomona-backup-validation.XXXXXX)"
BACKUP_PATH="${TMP_DIR}/pomona-backup.db"
RESTORED_PATH="${TMP_DIR}/pomona-restored.db"
DEVICE_ID="backup-validation-$(date +%s)"
trap 'rm -rf "${TMP_DIR}"' EXIT

wait_for_health() {
  for _ in {1..30}; do
    if curl -fsS "${CORE_URL}/health" >/dev/null 2>&1; then return 0; fi
    sleep 1
  done
  return 1
}

wait_for_health
curl -fsS -X POST "${CORE_URL}/v1/sensors/events" \
  -H 'Content-Type: application/json' \
  -d "{\"device_id\":\"${DEVICE_ID}\",\"farm_id\":\"demo-farm\",\"zone_id\":\"greenhouse-a\",\"crop\":\"tomato\",\"growth_stage\":\"flowering\",\"system_type\":\"greenhouse_substrate\",\"air_temperature_c\":25.0,\"humidity_pct\":64.0,\"ec_ms_cm\":2.0,\"ph\":6.1,\"soil_moisture_pct\":50.0,\"source\":\"backup-validation\"}" \
  >/dev/null

docker compose cp core:/app/data/pomona.db "${BACKUP_PATH}"
printf 'SQLite backup created: %s\n' "${BACKUP_PATH}"
docker compose restart core >/dev/null
wait_for_health

latest="$(curl -fsS "${CORE_URL}/v1/sensors/events/latest")"
DEVICE_ID="${DEVICE_ID}" python3 -c 'import json, os, sys; d=json.load(sys.stdin); assert d["device_id"] == os.environ["DEVICE_ID"]; assert d["source"] == "backup-validation"' <<<"${latest}"

./scripts/restore_sqlite.sh "${BACKUP_PATH}" "${RESTORED_PATH}" >/dev/null
BACKUP_DEVICE_ID="${DEVICE_ID}" "${PYTHON}" - "${RESTORED_PATH}" <<'PY'
import json
import os
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as db:
    rows = db.execute("SELECT payload FROM sensor_events ORDER BY id DESC").fetchall()
assert rows
payloads = [json.loads(row[0]) for row in rows]
assert any(item.get("device_id") == os.environ["BACKUP_DEVICE_ID"] for item in payloads)
print(f"Restored SQLite events: {len(payloads)}")
PY

echo "Backup/recovery validation passed for ${DEVICE_ID}."
echo "Live database was restarted; restore verification used a temporary database."
