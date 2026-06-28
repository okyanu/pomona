#!/usr/bin/env bash
# Extract ML training code from pomona/ into sibling repo pomona-agronomist-llm/
#
# Run from pomona repo root:
#   ./scripts/split/extract-ml-repo.sh
#
# Result:
#   ../pomona-agronomist-llm/   ← new Git repo (training + checkpoints)
#   ./models/registry/          ← stays in pomona (metadata only)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PARENT="$(dirname "$ROOT")"
ML_REPO="${ML_REPO_PATH:-${PARENT}/pomona-agronomist-llm}"
SRC_ML="${ROOT}/models/agronomist-llm"
SRC_CKPT="${ROOT}/models/checkpoints"

echo "==> Pomona ML repo extraction"
echo "    platform: ${ROOT}"
echo "    ML repo:  ${ML_REPO}"
echo ""

if [[ ! -d "$SRC_ML" ]]; then
  echo "Already extracted (models/agronomist-llm not found)."
  echo "ML repo expected at: ${ML_REPO}"
  exit 0
fi

if [[ -e "$ML_REPO" ]]; then
  echo "ERROR: ${ML_REPO} already exists. Remove or set ML_REPO_PATH."
  exit 1
fi

echo "==> Moving training code..."
mv "$SRC_ML" "$ML_REPO"

if [[ -d "$SRC_CKPT" ]]; then
  echo "==> Moving checkpoints..."
  mv "$SRC_CKPT" "${ML_REPO}/checkpoints"
fi

echo "==> Writing ML repo root files..."
cp "${ROOT}/LICENSE" "${ML_REPO}/LICENSE" 2>/dev/null || true

cat > "${ML_REPO}/.gitignore" <<'EOF'
# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/
.DS_Store

# Secrets
.env
.env.local
HF_TOKEN

# Weights — publish to Hugging Face, not GitHub
checkpoints/
finetune/adapter/
adapter/
outputs/
*.safetensors
*.pt
*.bin

# Large data
data/raw/
data/**/*.csv
data/**/*.7z
data/**/*.zip
EOF

mkdir -p "${ML_REPO}/scripts/publish"

cat > "${ML_REPO}/scripts/publish/huggingface.sh" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ADAPTER_DIR="${ADAPTER_DIR:-finetune/adapter}"
HF_REPO_ID="${HF_REPO_ID:-Okyanus/ai-pomona-agronomist-gemma4}"
HF_TOKEN="${HF_TOKEN:-}"
if [[ -z "$HF_TOKEN" ]]; then echo "ERROR: set HF_TOKEN"; exit 1; fi
python3 -m pip install -q huggingface_hub
python3 deploy/upload_to_hub.py --adapter "$ADAPTER_DIR" --repo "$HF_REPO_ID" --token "$HF_TOKEN"
echo "Done: https://huggingface.co/${HF_REPO_ID}"
EOF
chmod +x "${ML_REPO}/scripts/publish/huggingface.sh"

cat > "${ML_REPO}/README.md" <<'EOF'
# Pomona Agronomist LLM

Training pipeline and deployment tools for the Pomona Agronomist advisor model.

| Artifact | Location |
|----------|----------|
| **Weights** | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |
| **Platform** | [Okyanus/pomona](https://github.com/Okyanus/pomona) |
| **Registry** | `models/registry/agronomist-gemma4.yaml` in platform repo |

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r deploy/requirements.txt
python deploy/app.py          # Gradio UI (GPU)
```

## Publish weights to Hugging Face

```bash
HF_TOKEN=hf_... ./scripts/publish/huggingface.sh
```

## Publish this repo to GitHub

```bash
git init
git add .
git commit -m "init: agronomist LLM training pipeline"
gh repo create pomona-agronomist-llm --public --source=. --push
```

Not part of the Pomona platform repo — clone separately when finetuning.
EOF

if [[ ! -d "${ROOT}/models/registry" ]]; then
  echo "WARN: models/registry/ missing in platform — run platform updates first."
fi

echo ""
echo "==> Done."
echo ""
echo "Next steps:"
echo "  1. cd ${ML_REPO} && git init && git add . && git commit -m 'init: agronomist LLM'"
echo "  2. gh repo create pomona-agronomist-llm --public --source=. --push"
echo "  3. cd ${ROOT} && ./scripts/publish/github.sh   # platform repo only"
echo ""
echo "Platform pomona/ no longer contains training code."
