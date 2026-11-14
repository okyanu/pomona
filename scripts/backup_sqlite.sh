#!/usr/bin/env bash
# Create a consistent local SQLite backup of a database on this machine (no Docker). The Docker stack's databases
# are backed up with scripts/backup.sh instead.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="${1:-${ROOT_DIR}/data/pomona.db}"
DEST="${2:-${ROOT_DIR}/backups/pomona-$(date +%Y%m%d-%H%M%S).db}"
PYTHON="${PYTHON:-python3}"

if [[ ! -f "${SOURCE}" ]]; then
  echo "SQLite database not found: ${SOURCE}" >&2
  exit 2
fi
mkdir -p "$(dirname "${DEST}")"
"${PYTHON}" - "${SOURCE}" "${DEST}" <<'PY'
import sqlite3
import sys
source_db = sqlite3.connect(sys.argv[1])
destination_db = sqlite3.connect(sys.argv[2])
source_db.backup(destination_db)
destination_db.execute("PRAGMA journal_mode=DELETE")  # the copy is one self-contained file
destination_db.close()
source_db.close()
PY
printf 'SQLite backup created: %s\n' "${DEST}"
