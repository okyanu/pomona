#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PACKAGE_DIR="${PACKAGE_DIR:-${ROOT_DIR}/private/colab/hf-publish/pomona-water-irrigation-risk-reasoner-v0.1.8-lora}"
ADAPTER_ZIP="${ADAPTER_ZIP:-${ROOT_DIR}/private/colab/adapters/water-irrigation-risk-v0.1.8-context-low-lock-local.zip}"
HF_REPO_ID="${HF_REPO_ID:-Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora}"
HF_REPO_DIR="${HF_REPO_DIR:-${HOME}/Desktop/hf-repos/pomona-water-irrigation-risk-reasoner-v0.1.8-lora}"

if [ ! -f "${ADAPTER_ZIP}" ]; then
  echo "Adapter zip not found: ${ADAPTER_ZIP}" >&2
  exit 1
fi

if [ ! -f "${PACKAGE_DIR}/README.md" ]; then
  echo "Prepared package missing README.md: ${PACKAGE_DIR}" >&2
  exit 1
fi

case "${HF_REPO_DIR}" in
  "${ROOT_DIR}"|"${ROOT_DIR}"/*)
    echo "HF_REPO_DIR must stay outside the Pomona Git repository: ${HF_REPO_DIR}" >&2
    exit 1
    ;;
esac

mkdir -p "${HF_REPO_DIR}"

for name in README.md LICENSE CITATION.cff labels.json sample_input.json sample_output.json eval_summary.json; do
  cp "${PACKAGE_DIR}/${name}" "${HF_REPO_DIR}/${name}"
done

unzip -j -o "${ADAPTER_ZIP}" \
  adapter_config.json \
  adapter_model.safetensors \
  chat_template.jinja \
  tokenizer.json \
  tokenizer_config.json \
  -d "${HF_REPO_DIR}" \
  >/dev/null

echo "Prepared Hugging Face model folder: ${HF_REPO_DIR}"
find "${HF_REPO_DIR}" -maxdepth 1 -type f -print | sort

if [ -d "${HF_REPO_DIR}/.git" ]; then
  git -C "${HF_REPO_DIR}" lfs install --local
  git -C "${HF_REPO_DIR}" lfs track "*.safetensors"
  git -C "${HF_REPO_DIR}" status
else
  echo "No Git checkout found; prepared files only."
fi

if [ "${PUSH_TO_HF:-0}" = "1" ]; then
  hf repo create "${HF_REPO_ID}" --type model --public --exist-ok
  hf upload "${HF_REPO_ID}" "${HF_REPO_DIR}" . --repo-type model
else
  echo "PUSH_TO_HF is not 1; not uploading to Hugging Face."
fi
