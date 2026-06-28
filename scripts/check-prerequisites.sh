#!/usr/bin/env bash
# Check prerequisites for Pomona (macOS, Linux, Windows Git Bash / WSL).
set -euo pipefail

OK=0
WARN=0

check() { echo "  OK   $1"; OK=$((OK + 1)); }
warn()  { echo "  WARN $1"; WARN=$((WARN + 1)); }
fail()  { echo "  FAIL $1"; exit 1; }

echo "==> Pomona prerequisites"
echo ""

# Python
if command -v python3 >/dev/null 2>&1; then
  PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  check "python3 ($PY_VER)"
else
  warn "python3 not found — needed for simulator and pip dev mode"
fi

# Docker
if command -v docker >/dev/null 2>&1; then
  if docker info >/dev/null 2>&1; then
    check "docker (daemon running)"
  else
    warn "docker installed but daemon not running — start Docker Desktop"
  fi
else
  warn "docker not found — use pip dev mode or install Docker Desktop"
fi

# Compose
if docker compose version >/dev/null 2>&1; then
  check "docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  warn "legacy docker-compose found — prefer 'docker compose' plugin"
else
  warn "docker compose not found"
fi

# curl (for make health)
if command -v curl >/dev/null 2>&1; then
  check "curl"
else
  warn "curl not found — health checks in Makefile may fail"
fi

# .env
if [[ -f .env ]]; then
  check ".env exists"
else
  warn ".env missing — run: cp .env.example .env"
fi

echo ""
echo "Summary: $OK checks passed, $WARN warnings"
echo ""
if [[ $WARN -gt 0 ]]; then
  echo "Docker path (recommended): install Docker Desktop, then ./scripts/up.sh"
  echo "Pip path: pip3 install -r requirements-dev.txt && ./scripts/run-local.sh"
fi
