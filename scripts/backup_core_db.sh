#!/usr/bin/env bash
# Kept so older commands still work: the Docker backup now covers both databases and the audit log.
exec "$(dirname "${BASH_SOURCE[0]}")/backup.sh" "$@"
