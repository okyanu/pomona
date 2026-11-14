#!/usr/bin/env bash
# Kept so older commands still work: restore.sh takes a backup folder (both databases) or a single core.db file.
exec "$(dirname "${BASH_SOURCE[0]}")/restore.sh" "$@"
