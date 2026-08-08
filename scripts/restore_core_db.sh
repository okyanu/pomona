#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP="${1:-}"

if [[ -z "${BACKUP}" || ! -f "${BACKUP}" ]]; then
  printf 'Usage: %s /path/to/pomona-backup.db\n' "$0" >&2
  exit 2
fi

cd "${ROOT_DIR}"
printf 'Stopping core before restore...\n'
docker compose stop core
docker compose cp "${BACKUP}" core:/app/data/pomona.db
docker compose start core
printf 'SQLite backup restored: %s\n' "${BACKUP}"
