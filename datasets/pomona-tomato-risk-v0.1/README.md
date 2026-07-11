# Pomona Tomato Risk v0.1

Compact tomato greenhouse risk-labeling dataset for Pomona reasoners.

Each JSONL record maps a digital twin **input** (sensor state, crop context, symptoms) to an **expected_output**:

- `risk_labels`
- `missing_data`
- `safe_next_checks`
- `blocked_actions`
- `human_review_required`

## What creates the dataset?

| File / script | Role |
|---|---|
| `data/samples.jsonl` | Committed seed examples (authored by Pomona) |
| `data/eval_cases.jsonl` | Committed evaluation cases (authored by Pomona) |
| `scripts/datasets/build_pomona_tomato_risk_dataset.py` | Checks scaffold files exist and prints counts; future merge point for interim data |
| `scripts/datasets/validate_pomona_dataset.py` | **Required check** — validates schema and safety enums |
| `scripts/datasets/normalize_*.py` | Convert downloaded raw source files → interim JSONL |
| `scripts/datasets/split_dataset.py` | Optional local train/val/test splits under `datasets/processed/` |
| `scripts/huggingface/publish_dataset_to_hf.sh` | Copies publishable files to `~/Desktop/hf-repos/pomona-tomato-risk-v0.1` |

**Today:** the dataset you use is the JSONL in `data/`. Run the validator before editing or publishing.

**Later:** external CC BY 4.0 sources (`mendeley_hydroponics_fertigation`, `udea_greenhouse_tomato`) feed interim files that get merged into `data/` after labeling. See `docs/source_mapping.md`.

Registered sources are listed in `datasets/registry.yaml` and `datasets/sources/`.

## Directory layout

- `schema/` — JSON Schema for `input`, `expected_output`, and allowed labels
- `data/samples.jsonl` — seed examples
- `data/eval_cases.jsonl` — eval cases
- `docs/` — labeling guide, annotation guide, source field mapping
- `DATASET_CARD.md` — Hugging Face dataset card (copied to HF `README.md` on publish)
- `LICENSES.md` — source attribution and license notes

## Commands

```bash
# From repo root — validate all committed records
python3 scripts/datasets/validate_pomona_dataset.py

# Count scaffold records (no file rewrite)
python3 scripts/datasets/build_pomona_tomato_risk_dataset.py

# Stage files for Hugging Face (validate runs inside the script)
./scripts/huggingface/publish_dataset_to_hf.sh
```

## Record shape (one line of JSONL)

```json
{
  "id": "example-001",
  "source_id": "pomona_handwritten_eval_cases",
  "input": { "...": "see schema/input.schema.json" },
  "expected_output": { "...": "see schema/output.schema.json" },
  "notes": "optional curator note"
}
```

Add or edit rows in `data/*.jsonl`, then re-run the validator.
