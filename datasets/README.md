# Pomona Datasets

This directory holds dataset **metadata**, **schemas**, **small committed JSONL files**, and **scripts** that build and publish releases. It is not a dump of full third-party raw data.

The first dataset is **`pomona-tomato-risk-v0.1`**: tomato greenhouse risk labels for safe agriculture reasoners.

## What each part does

| Path | Purpose |
|---|---|
| `registry.yaml` | Index of Pomona datasets: Hugging Face target, linked source IDs, publishable file list |
| `sources/*.yaml` | One file per **source**: license, attribution, redistribution flags — not the data itself |
| `pomona-tomato-risk-v0.1/` | The **dataset package**: schema, docs, and committed JSONL (`samples.jsonl`, `eval_cases.jsonl`) |
| `raw/` | You download third-party files here locally (gitignored) |
| `interim/` | Normalized working JSONL from raw sources (gitignored) |
| `processed/` | Local train/validation/test splits (gitignored) |
| `../scripts/datasets/` | Build, validate, normalize, and split scripts |
| `../scripts/huggingface/publish_dataset_to_hf.sh` | Copy validated files to the local Hugging Face checkout |

## Quick start (use the dataset as it is today)

The committed JSONL files **are** the current v0.1 scaffold. You do not need to run a builder to create them from scratch.

```bash
# Check records match the schema and safety enums
python3 scripts/datasets/validate_pomona_dataset.py

# Optional: print record counts (does not rewrite data yet)
python3 scripts/datasets/build_pomona_tomato_risk_dataset.py
```

Read examples:

- `datasets/pomona-tomato-risk-v0.1/data/samples.jsonl` — seed training-style examples
- `datasets/pomona-tomato-risk-v0.1/data/eval_cases.jsonl` — evaluation cases

Schema and labeling rules:

- `datasets/pomona-tomato-risk-v0.1/schema/`
- `datasets/pomona-tomato-risk-v0.1/docs/`

## Full pipeline (when adding external source data)

1. Read the source entry in `datasets/sources/<source_id>.yaml`.
2. Download raw files into `datasets/raw/<source_id>/` (local only).
3. Normalize to interim JSONL:

   ```bash
   python3 scripts/datasets/normalize_mendeley_hydroponics.py \
     --input datasets/raw/mendeley_hydroponics_fertigation/ \
     --output datasets/interim/mendeley_hydroponics_fertigation.jsonl

   python3 scripts/datasets/normalize_udea_greenhouse_tomato.py \
     --input datasets/raw/udea_greenhouse_tomato/ \
     --output datasets/interim/udea_greenhouse_tomato.jsonl
   ```

   Normalizers are scaffolds today; implement source-specific field mapping before relying on them.

4. Merge labeled records into `datasets/pomona-tomato-risk-v0.1/data/` (by hand or by extending the builder).
5. Validate:

   ```bash
   python3 scripts/datasets/validate_pomona_dataset.py
   ```

6. Optional local splits (not committed by default):

   ```bash
   python3 scripts/datasets/split_dataset.py \
     --input datasets/pomona-tomato-risk-v0.1/data/samples.jsonl
   ```

7. Publish to Hugging Face checkout:

   ```bash
   ./scripts/huggingface/publish_dataset_to_hf.sh
   ```

   Set `PUSH_TO_HF=1` only when you intend to commit and push the HF repo.

Published release target: [Okyanus/pomona-tomato-risk-v0.1](https://huggingface.co/datasets/Okyanus/pomona-tomato-risk-v0.1).

See [datasets/pomona-tomato-risk-v0.1/README.md](pomona-tomato-risk-v0.1/README.md) for validate and publish commands.
