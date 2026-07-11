#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATASET_DIR="${ROOT_DIR}/datasets/pomona-tomato-risk-v0.1"
PROCESSED_DIR="${ROOT_DIR}/datasets/processed/pomona-tomato-risk-v0.1"
HF_REPO_DIR="${HOME}/Desktop/hf-repos/pomona-tomato-risk-v0.1"

cd "${ROOT_DIR}"

python3 scripts/datasets/build_pomona_tomato_risk_dataset.py --dataset-dir "${DATASET_DIR}"
python3 scripts/datasets/split_dataset.py \
  --input "${PROCESSED_DIR}/derived_records.jsonl" \
  --output-dir "${PROCESSED_DIR}"
python3 scripts/datasets/validate_pomona_dataset.py --jsonl "${PROCESSED_DIR}/train.jsonl"
python3 scripts/datasets/validate_pomona_dataset.py --jsonl "${PROCESSED_DIR}/validation.jsonl"
python3 scripts/datasets/validate_pomona_dataset.py --jsonl "${PROCESSED_DIR}/test.jsonl"
python3 scripts/datasets/validate_pomona_dataset.py --dataset-dir "${DATASET_DIR}"

mkdir -p "${HF_REPO_DIR}/schema" "${HF_REPO_DIR}/data"

cp "${DATASET_DIR}/DATASET_CARD.md" "${HF_REPO_DIR}/README.md"
cp "${DATASET_DIR}/LICENSES.md" "${HF_REPO_DIR}/LICENSES.md"
cp "${DATASET_DIR}/CITATION.cff" "${HF_REPO_DIR}/CITATION.cff"
cp "${DATASET_DIR}/schema/input.schema.json" "${HF_REPO_DIR}/schema/input.schema.json"
cp "${DATASET_DIR}/schema/output.schema.json" "${HF_REPO_DIR}/schema/output.schema.json"
cp "${DATASET_DIR}/schema/labels.schema.json" "${HF_REPO_DIR}/schema/labels.schema.json"
cp "${DATASET_DIR}/data/samples.jsonl" "${HF_REPO_DIR}/data/samples.jsonl"
cp "${DATASET_DIR}/data/eval_cases.jsonl" "${HF_REPO_DIR}/data/eval_cases.jsonl"
cp "${DATASET_DIR}/data/golden_eval.jsonl" "${HF_REPO_DIR}/data/golden_eval.jsonl"
cp "${PROCESSED_DIR}/train.jsonl" "${HF_REPO_DIR}/data/train.jsonl"
cp "${PROCESSED_DIR}/validation.jsonl" "${HF_REPO_DIR}/data/validation.jsonl"
cp "${PROCESSED_DIR}/test.jsonl" "${HF_REPO_DIR}/data/test.jsonl"

if [ -d "${HF_REPO_DIR}/docs" ]; then
  rm -rf "${HF_REPO_DIR}/docs"
fi
mkdir -p "${HF_REPO_DIR}/docs"
cp "${DATASET_DIR}/docs/label_guide.md" "${HF_REPO_DIR}/docs/label_guide.md"
cp "${DATASET_DIR}/docs/annotation_guide.md" "${HF_REPO_DIR}/docs/annotation_guide.md"
cp "${DATASET_DIR}/docs/source_mapping.md" "${HF_REPO_DIR}/docs/source_mapping.md"

cd "${HF_REPO_DIR}"
if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git status
else
  echo "WARNING: ${HF_REPO_DIR} is not a Git repository yet; copied files are ready, but git status/push were skipped."
  echo "Create or clone the Hugging Face dataset repo there before setting PUSH_TO_HF=1."
  exit 0
fi

if [ "${PUSH_TO_HF:-0}" = "1" ]; then
  git add README.md LICENSES.md CITATION.cff schema data docs
  git commit -m "Publish Pomona tomato risk v0.1 dataset"
  git push
else
  echo "PUSH_TO_HF is not 1; not committing or pushing to Hugging Face."
fi
