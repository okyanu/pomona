#!/usr/bin/env bash
# Rebuild spaces/try-to-fool-pomona/vendor/ from the repo (generated, gitignored). `--check` only verifies it.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "${PYTHON:-python3}" "${ROOT}/scripts/build_fool_space.py" "$@"
