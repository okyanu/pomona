#!/usr/bin/env bash
# Pyodide parity: the engine in Pyodide (as the page runs it) gives byte-identical results to CPython.
# Needs node (18+) and, the first time, network for `npm ci`. Run via `make fool-space-pyodide-check` after the Space is built.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SPACE="$(cd "$HERE/.." && pwd)"
REPO="$(cd "$SPACE/../.." && pwd)"
PY="${FOOL_PY:-$SPACE/.venv/bin/python}"

command -v node >/dev/null || { echo "node is not installed: cannot run the Pyodide parity check" >&2; exit 2; }
[ -f "$SPACE/pyodide/pyodide.asm.wasm" ] && [ -f "$SPACE/pomona.zip" ] || { echo "run scripts/build_fool_space.sh first" >&2; exit 1; }
if [ ! -d "$HERE/node_modules/pyodide" ]; then
  (cd "$HERE" && npm ci --no-audit --no-fund --silent)
fi

OUT="$(mktemp -d "${TMPDIR:-/tmp}/fool-space-parity.XXXXXX")"
trap 'rm -rf "$OUT"' EXIT
echo "-- CPython reference (real asyncio loop)"
PYTHONDONTWRITEBYTECODE=1 "$PY" -I "$HERE/parity_driver.py" "$SPACE" "$REPO/examples/simulators/scenarios/demo.json" "$OUT/expected.json"
echo "-- Pyodide (SyncLoop, no eval)"
(cd "$HERE" && node --disallow-code-generation-from-strings pyodide_parity.mjs "$OUT/expected.json")
