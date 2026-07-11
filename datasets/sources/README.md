# Dataset Sources

One YAML file per source. These files describe **provenance and license**, not the data itself.

Active v0.1 sources for `pomona-tomato-risk-v0.1`:

| File | Source ID |
|---|---|
| `mendeley_hydroponics_fertigation.yaml` | External CC BY 4.0 fertigation data |
| `udea_greenhouse_tomato.yaml` | External CC BY 4.0 greenhouse tomato data |
| `pomona_handwritten_eval_cases.yaml` | Pomona-authored seed and eval JSONL |

`datasets/registry.yaml` references these IDs for the tomato risk dataset.

## How to use a source YAML

1. Read `license`, `redistribution_allowed`, and `attribution_required`.
2. Download raw data from the source `url` into `datasets/raw/<source_id>/`.
3. Run the matching normalizer in `scripts/datasets/normalize_<source>.py`.
4. Label interim rows to Pomona schema and add them to `datasets/pomona-tomato-risk-v0.1/data/`.
5. Record attribution in `datasets/pomona-tomato-risk-v0.1/LICENSES.md` when publishing derived rows.

For `pomona_handwritten_eval_cases`, skip download — edit `data/samples.jsonl` and `data/eval_cases.jsonl` directly.

## Required fields

External sources:

- `id`, `name`, `url`, `doi`, `license`
- `redistribution_allowed`, `derived_dataset_allowed`, `attribution_required`
- `status: active_v0_1_source`

Pomona-authored sources also include `created_by`.
