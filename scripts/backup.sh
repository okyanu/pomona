#!/usr/bin/env bash
# Back up the Docker deployment: Core's database, the automation engine's database and the model-router's audit log,
# into one timestamped folder (default: backups/<YYYYmmdd-HHMMSS>/, which is gitignored).
#
#   ./scripts/backup.sh [destination-folder]        (BACKUP_DIR=... changes the parent folder)
#
# Each database is copied with SQLite's online backup API, run inside the running container, so the copy is
# consistent even while Core is writing (a plain file copy of a live database, especially in WAL mode, is not).
# The backup is written to a temporary file in the database's own data volume (NOT /tmp, a 64 MB tmpfs that a big
# database would fill), streamed to this machine over `docker compose exec` stdout, and the temporary file is removed.
# So the free space needed is about the size of the database, in the same volume. For a database outside Docker use
# scripts/backup_sqlite.sh. To restore: scripts/restore.sh.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${1:-${BACKUP_DIR}/${STAMP}}"
PYTHON="${PYTHON:-python3}"

if [[ -e "${DEST}" ]]; then
  echo "Backup folder already exists: ${DEST}" >&2
  exit 2
fi

cd "${ROOT_DIR}"

# Runs in the container. argv: <env var holding the path> <default path>. Stdout carries only the database bytes.
read -r -d '' DB_BACKUP_PY <<'PY' || true
import os, shutil, sqlite3, sys
var, default = sys.argv[1:3]
src_path = os.environ.get(var, default)
if not os.path.exists(src_path):
    sys.exit("database not found: " + src_path)
tmp = os.path.join(os.path.dirname(src_path), ".backup-%d.tmp" % os.getpid())
try:
    src = sqlite3.connect(src_path, timeout=30)
    dst = sqlite3.connect(tmp)
    src.backup(dst)
    dst.execute("PRAGMA journal_mode=DELETE")
    result = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close()
    src.close()
    if result != "ok":
        sys.exit("integrity check of the copy failed: " + result)
    with open(tmp, "rb") as handle:
        shutil.copyfileobj(handle, sys.stdout.buffer)
    sys.stdout.buffer.flush()
finally:
    for suffix in ("", "-wal", "-shm", "-journal"):
        try:
            os.remove(tmp + suffix)
        except FileNotFoundError:
            pass
PY

# Runs in the container. Copies the first N bytes (N = size when the copy starts), so a line being written
# at that moment is not half-copied into the middle of the file; exit 3 = the file does not exist (no audit log yet,
# or no rotated one). argv: <env var holding the path> <default path> [suffix appended to the path, e.g. ".1"].
read -r -d '' FILE_COPY_PY <<'PY' || true
import os, sys
var, default = sys.argv[1:3]
path = os.environ.get(var, default) + (sys.argv[3] if len(sys.argv) > 3 else "")
if not os.path.exists(path):
    sys.exit(3)
left = os.path.getsize(path)
with open(path, "rb") as handle:
    while left > 0:
        chunk = handle.read(min(left, 1 << 20))
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
        left -= len(chunk)
sys.stdout.buffer.flush()
PY

mkdir -p "${DEST}"
trap 'rc=$?; if [[ $rc -ne 0 ]]; then rm -rf "${DEST}"; echo "Backup FAILED: the incomplete folder was removed." >&2; fi' EXIT

require_running() {
  if [[ -z "$(docker compose ps --status running -q "$1")" ]]; then
    echo "The $1 container is not running: start the stack first (./scripts/up.sh)." >&2
    exit 1
  fi
}

backup_db() {  # <service> <file name> <env var> <default path>
  local service="$1" name="$2"
  require_running "${service}"
  docker compose exec -T "${service}" python -c "${DB_BACKUP_PY}" "$3" "$4" > "${DEST}/${name}"
  "${PYTHON}" - "${DEST}/${name}" <<'PY'
import sqlite3, sys
path = sys.argv[1]
db = sqlite3.connect(path)
result = db.execute("PRAGMA integrity_check").fetchone()[0]
db.close()
if result != "ok":
    sys.exit("backup %s failed the integrity check on this machine: %s" % (path, result))
PY
  printf 'Backed up %s -> %s (%s bytes)\n' "${service}" "${name}" "$(wc -c < "${DEST}/${name}" | tr -d ' ')"
}

backup_db core core.db DB_PATH /app/data/pomona.db
backup_db automation-engine automation.db AUTOMATION_DB_PATH /data/automation.db

require_running model-router
copy_audit() {  # <file name> <path suffix: "" for the live log, ".1" for the rotated one> <label>
  local name="$1" suffix="$2" label="$3" status
  set +e
  docker compose exec -T model-router python -c "${FILE_COPY_PY}" AUDIT_LOG_PATH /app/data/pomona-pipeline-audit.jsonl "${suffix}" > "${DEST}/${name}"
  status=$?
  set -e
  if [[ ${status} -eq 3 ]]; then
    rm -f "${DEST}/${name}"
    echo "No ${label} yet: skipped."
  elif [[ ${status} -ne 0 ]]; then
    echo "Could not copy the ${label} (exit ${status})." >&2
    exit 1
  else
    printf 'Copied %s -> %s (%s bytes)\n' "${label}" "${name}" "$(wc -c < "${DEST}/${name}" | tr -d ' ')"
  fi
}
# The rotated file (<audit log>.1) holds the events from before the last rotation (see services/model-router/app/audit.py).
copy_audit audit.jsonl.1 .1 "model-router rotated audit log"
copy_audit audit.jsonl "" "model-router audit log"

printf 'Pomona backup %s\ncore.db: Core events and state\nautomation.db: automation suggestions and alerts\naudit.jsonl: model-router pipeline audit log (if it existed)\naudit.jsonl.1: the rotated older part of the audit log (if it existed)\n' "${STAMP}" > "${DEST}/README.txt"
printf 'Backup created: %s\n' "${DEST}"
