#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_DIR="${BACKUP_DIR:-${ROOT_DIR}/backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
DEST="${BACKUP_DIR}/pomona-${STAMP}.db"

mkdir -p "${BACKUP_DIR}"
cd "${ROOT_DIR}"
docker compose cp core:/app/data/pomona.db "${DEST}"
printf 'SQLite backup created: %s\n' "${DEST}"
