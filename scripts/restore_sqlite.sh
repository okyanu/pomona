#!/usr/bin/env bash
# Restore a local SQLite database without Docker.
set -euo pipefail

SOURCE="${1:-}"
DEST="${2:-data/pomona.db}"
PYTHON="${PYTHON:-python3}"
if [[ -z "${SOURCE}" || ! -f "${SOURCE}" ]]; then
  printf 'Usage: %s /path/to/backup.db [destination.db]\n' "$0" >&2
  exit 2
fi
mkdir -p "$(dirname "${DEST}")"
"${PYTHON}" - "${SOURCE}" "${DEST}" <<'PY'
import sqlite3
import sys
with sqlite3.connect(sys.argv[1]) as source_db, sqlite3.connect(sys.argv[2]) as destination_db:
    source_db.backup(destination_db)
PY
printf 'SQLite database restored: %s\n' "${DEST}"
