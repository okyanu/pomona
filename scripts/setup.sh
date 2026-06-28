#!/usr/bin/env bash
# First-time setup — cross-platform (macOS, Linux, WSL, Git Bash).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "==> Pomona setup"
echo ""

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env"
fi

PYTHON="${PYTHON:-python3}"
if command -v "$PYTHON" >/dev/null 2>&1; then
  echo "Installing Python dev dependencies..."
  "$PYTHON" -m pip install -U pip -q
  "$PYTHON" -m pip install -r requirements-dev.txt -q
  echo "Python deps installed."
else
  echo "WARN: python3 not found — skip pip install (Docker-only mode still works)"
fi

chmod +x scripts/*.sh 2>/dev/null || true
./scripts/check-prerequisites.sh

echo ""
echo "==> Choose how to run"
echo ""
echo "  A) Docker (recommended — same on Mac, Windows, Linux):"
echo "       ./scripts/up.sh"
echo "       ./scripts/sim.sh    # second terminal"
echo ""
echo "  B) Pip local dev (MQTT in Docker, APIs on host):"
echo "       ./scripts/up.sh mqtt"
echo "       ./scripts/run-local.sh"
echo "       ./scripts/sim.sh"
echo ""
echo "Docs: docs/INSTALL.md"
