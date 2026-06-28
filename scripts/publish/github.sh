#!/usr/bin/env bash
# Publish Pomona source code to GitHub (no model weights).
#
# Usage:
#   ./scripts/publish/github.sh              # first-time init + push
#   ./scripts/publish/github.sh push         # commit all changes + push
#   ./scripts/publish/github.sh push "fix: core mqtt reconnect"
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

GITHUB_USER="${GITHUB_USER:-Okyanus}"
GITHUB_REPO="${GITHUB_REPO:-pomona}"
GITHUB_VISIBILITY="${GITHUB_VISIBILITY:-public}"
BRANCH="${GITHUB_BRANCH:-main}"

MODE="${1:-init}"
if [[ "$MODE" == "push" ]]; then
  COMMIT_MSG="${2:-chore: update pomona}"
else
  COMMIT_MSG="init: Pomona monorepo — edge AI platform for agriculture"
fi

echo "==> Pomona GitHub publish"
echo "    repo: ${GITHUB_USER}/${GITHUB_REPO}"
echo "    mode: ${MODE}"
echo ""

"$(dirname "$0")/check.sh"

if ! git rev-parse --git-dir >/dev/null 2>&1; then
  git init
  git branch -M "$BRANCH"
  echo "Initialized git on branch ${BRANCH}"
fi

git add .

echo ""
echo "==> Staged files:"
git diff --cached --stat

if git diff --cached --quiet; then
  echo "Nothing new to commit."
else
  git commit -m "$COMMIT_MSG"
fi

REMOTE_URL="git@github.com:${GITHUB_USER}/${GITHUB_REPO}.git"

if ! git remote get-url origin >/dev/null 2>&1; then
  if command -v gh >/dev/null 2>&1 && [[ "$MODE" != "push" ]]; then
    echo ""
    echo "==> Creating GitHub repo via gh..."
    gh repo create "${GITHUB_REPO}" \
      --"${GITHUB_VISIBILITY}" \
      --source=. \
      --remote=origin \
      --description "Open edge AI stack for agriculture (Pomona)" || true
  fi
  if ! git remote get-url origin >/dev/null 2>&1; then
    git remote add origin "$REMOTE_URL"
  fi
fi

echo ""
echo "==> Pushing to origin/${BRANCH}..."
git push -u origin "$BRANCH"

echo ""
echo "Done: https://github.com/${GITHUB_USER}/${GITHUB_REPO}"
echo ""
echo "Model weights → Hugging Face (separate):"
echo "  HF_TOKEN=hf_... ./scripts/publish/huggingface.sh"
