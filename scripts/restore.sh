#!/usr/bin/env bash
# Restore the Docker deployment from a folder made by scripts/backup.sh.
#
#   ./scripts/restore.sh backups/20260101-020000     restores every file found in the folder
#   ./scripts/restore.sh /path/to/core.db            a single Core database (the old backup_core_db.sh format)
#
# This REPLACES the live data. Take a fresh backup first if the current data matters (./scripts/backup.sh).
# For each service: stop it, write the backup into its data volume with a one-off container of the same image (via
# stdin, to a temporary file, then an atomic rename), delete the old database's -wal / -shm files, start it again.
# Nothing is stopped until every file has passed an integrity check on this machine. If a restore fails after its
# service was stopped, the service is started again with its old, unchanged database and the script exits non-zero.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${1:-}"
PYTHON="${PYTHON:-python3}"

if [[ -z "${SOURCE}" || ( ! -d "${SOURCE}" && ! -f "${SOURCE}" ) ]]; then
  printf 'Usage: %s <backup folder from backup.sh | core.db>\n' "$0" >&2
  exit 2
fi

# The script changes into the repository folder below, so a relative path given by the caller must be made absolute now.
if [[ -d "${SOURCE}" ]]; then
  SOURCE="$(cd "${SOURCE}" && pwd)"
else
  SOURCE="$(cd "$(dirname "${SOURCE}")" && pwd)/$(basename "${SOURCE}")"
fi

# Runs in the one-off container. argv: <sqlite|file> <env var holding the path> <default path> [suffix, e.g. ".1"];
# the backup arrives on stdin.
read -r -d '' RESTORE_PY <<'PY' || true
import os, shutil, sqlite3, sys
kind, var, default = sys.argv[1:4]
dest = os.environ.get(var, default) + (sys.argv[4] if len(sys.argv) > 4 else "")
tmp = dest + ".restore-tmp"
try:
    with open(tmp, "wb") as handle:
        shutil.copyfileobj(sys.stdin.buffer, handle)
        handle.flush()
        os.fsync(handle.fileno())
    if os.path.getsize(tmp) == 0:
        sys.exit("the backup is empty")
    if kind == "sqlite":
        db = sqlite3.connect(tmp)
        result = db.execute("PRAGMA integrity_check").fetchone()[0]
        db.close()
        if result != "ok":
            sys.exit("integrity check failed: " + result)
        for suffix in ("-wal", "-shm", "-journal"):
            try:
                os.remove(dest + suffix)
            except FileNotFoundError:
                pass
    os.replace(tmp, dest)
finally:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(tmp + suffix)
        except FileNotFoundError:
            pass
PY

# Work list: "<service>|<backup file>|<kind>|<env var>|<default path>|<path suffix>"
JOBS=()
if [[ -d "${SOURCE}" ]]; then
  [[ -f "${SOURCE}/core.db" ]] && JOBS+=("core|${SOURCE}/core.db|sqlite|DB_PATH|/app/data/pomona.db|")
  [[ -f "${SOURCE}/automation.db" ]] && JOBS+=("automation-engine|${SOURCE}/automation.db|sqlite|AUTOMATION_DB_PATH|/data/automation.db|")
  # The rotated part first, then the live log (both go to the same service, which is stopped once for the pair).
  [[ -f "${SOURCE}/audit.jsonl.1" ]] && JOBS+=("model-router|${SOURCE}/audit.jsonl.1|file|AUDIT_LOG_PATH|/app/data/pomona-pipeline-audit.jsonl|.1")
  [[ -f "${SOURCE}/audit.jsonl" ]] && JOBS+=("model-router|${SOURCE}/audit.jsonl|file|AUDIT_LOG_PATH|/app/data/pomona-pipeline-audit.jsonl|")
  if [[ ${#JOBS[@]} -eq 0 ]]; then
    echo "No core.db, automation.db, audit.jsonl or audit.jsonl.1 in ${SOURCE}" >&2
    exit 2
  fi
else
  JOBS+=("core|${SOURCE}|sqlite|DB_PATH|/app/data/pomona.db|")
  echo "Single file given: restoring Core's database only."
fi

for job in "${JOBS[@]}"; do
  IFS='|' read -r service file kind _ _ _ <<<"${job}"
  [[ "${kind}" == sqlite ]] || continue
  "${PYTHON}" - "${file}" <<'PY'
import sqlite3, sys
db = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
try:
    result = db.execute("PRAGMA integrity_check").fetchone()[0]
except sqlite3.DatabaseError as error:
    result = str(error)
db.close()
if result != "ok":
    sys.exit("%s is not a healthy SQLite database: %s" % (sys.argv[1], result))
PY
done

cd "${ROOT_DIR}"

# A service is stopped while its files are replaced. If anything fails in that window (the one-off container, or the
# stop itself), start it again: the restore writes to a temporary file and replaces the real one only at the end, so
# the service comes back with its old data.
STOPPED=""
start_stopped() {
  if [[ -n "${STOPPED}" ]]; then
    docker compose up -d --no-deps "${STOPPED}"
    STOPPED=""
  fi
}
on_exit() {
  local rc=$?
  if [[ ${rc} -ne 0 && -n "${STOPPED}" ]]; then
    echo "ERROR: restoring ${STOPPED} failed (exit ${rc}). Starting ${STOPPED} again with its previous data." >&2
    docker compose up -d --no-deps "${STOPPED}" || echo "Could not start ${STOPPED}: run 'docker compose up -d ${STOPPED}' yourself." >&2
    echo "Services restored before this one keep their restored data; the rest were not touched." >&2
  fi
}
trap on_exit EXIT

for job in "${JOBS[@]}"; do
  IFS='|' read -r service file kind var default suffix <<<"${job}"
  printf 'Restoring %s from %s ...\n' "${service}" "${file}"
  if [[ "${service}" != "${STOPPED}" ]]; then
    start_stopped
    STOPPED="${service}"
    docker compose stop "${service}"
  fi
  docker compose run --rm --no-deps -T --entrypoint python "${service}" -c "${RESTORE_PY}" "${kind}" "${var}" "${default}" "${suffix}" < "${file}"
done
start_stopped
printf 'Restore finished: %s\n' "${SOURCE}"
