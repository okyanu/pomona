#!/usr/bin/env bash
# Hugging Face uploads moved to the ML training repo.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ML_REPO="${ML_REPO_PATH:-$(dirname "$ROOT")/pomona-agronomist-llm}"

echo "Model weights are published from the ML repo, not the platform repo."
echo ""
if [[ -x "${ML_REPO}/scripts/publish/huggingface.sh" ]]; then
  echo "Running: ${ML_REPO}/scripts/publish/huggingface.sh"
  exec "${ML_REPO}/scripts/publish/huggingface.sh" "$@"
else
  echo "ML repo not found at: ${ML_REPO}"
  echo ""
  echo "First extract the ML repo:"
  echo "  ./scripts/split/extract-ml-repo.sh"
  echo ""
  echo "Then publish:"
  echo "  cd ${ML_REPO}"
  echo "  HF_TOKEN=hf_... ./scripts/publish/huggingface.sh"
  exit 1
fi
