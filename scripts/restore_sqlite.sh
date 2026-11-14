#!/usr/bin/env bash
# Restore a local SQLite database without Docker (Docker stack: scripts/restore.sh). Stop whatever uses the
# destination database first.
set -euo pipefail

SOURCE="${1:-}"
DEST="${2:-data/pomona.db}"
PYTHON="${PYTHON:-python3}"
if [[ -z "${SOURCE}" || ! -f "${SOURCE}" ]]; then
  printf 'Usage: %s /path/to/backup.db [destination.db]\n' "$0" >&2
  exit 2
fi
mkdir -p "$(dirname "${DEST}")"
# Restore into a temporary file next to the destination, check it, and only then touch the old database. A
# leftover -wal / -shm file next to the old database would be applied to the restored one, so those are removed
# just before the atomic replace, never earlier: if the source is bad, the old database and its WAL stay as they were.
TMP="${DEST}.restore-tmp"
cleanup() { rm -f "${TMP}" "${TMP}-wal" "${TMP}-shm" "${TMP}-journal"; }
trap cleanup EXIT
cleanup
"${PYTHON}" - "${SOURCE}" "${TMP}" <<'PY'
import sqlite3
import sys
source_db = sqlite3.connect("file:%s?mode=ro" % sys.argv[1], uri=True)
destination_db = sqlite3.connect(sys.argv[2])
try:
    source_db.backup(destination_db)
    result = destination_db.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        sys.exit("integrity check of the restored copy failed: " + result)
    destination_db.execute("PRAGMA journal_mode=DELETE")
finally:
    destination_db.close()
    source_db.close()
PY
rm -f "${DEST}-wal" "${DEST}-shm" "${DEST}-journal"
mv -f "${TMP}" "${DEST}"
printf 'SQLite database restored: %s\n' "${DEST}"
