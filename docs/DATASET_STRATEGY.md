# Dataset Strategy

Pomona's GitHub repo holds pipeline code, source metadata, schemas, small hand-written JSONL, and publish scripts. The **published** dataset for downstream users lives on Hugging Face:

- Published dataset: [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)
- Local HF checkout for future releases: `~/Desktop/hf-repos/greenhouse-sensor-data`
- GitHub pipeline: `datasets/pomona-tomato-risk-v0.1/` + `scripts/datasets/`

Raw third-party files stay at their original URLs and in your local `datasets/raw/` folder. Pomona tracks license and attribution in `datasets/sources/*.yaml`.

## Active v0.1 sources

| Source ID | Role | License |
|---|---|---|
| `mendeley_hydroponics_fertigation` | Hydroponic fertigation sensor patterns | CC BY 4.0 |
| `udea_greenhouse_tomato` | Greenhouse tomato environmental and crop-state mapping | CC BY 4.0 |
| `pomona_handwritten_eval_cases` | Pomona-authored seed and eval JSONL | Apache-2.0 |

`datasets/registry.yaml` links these sources to `pomona-tomato-risk-v0.1`.

## How the files fit together

```text
datasets/sources/*.yaml          license + attribution metadata
        │
        ▼
datasets/raw/                    you download source files here (local, gitignored)
        │
        ▼
scripts/datasets/normalize_*.py  raw → interim JSONL (scaffolded)
        │
        ▼
datasets/pomona-tomato-risk-v0.1/data/*.jsonl   labeled records (committed scaffold today)
        │
        ▼
scripts/datasets/validate_pomona_dataset.py       schema + safety check
        │
        ▼
scripts/huggingface/publish_dataset_to_hf.sh    copy to HF checkout
        │
        ▼
~/Desktop/hf-repos/greenhouse-sensor-data       Hugging Face release repo
```

**Using the dataset now:** open or load `data/samples.jsonl` and `data/eval_cases.jsonl` after running the validator. No build step is required for the current scaffold.

**Growing the dataset:** download CC BY 4.0 sources, normalize to interim, label to Pomona schema, append to `data/*.jsonl`, validate, publish.

## Release steps

1. Download verified source data into `datasets/raw/`.
2. Run the matching `normalize_*.py` script → `datasets/interim/`.
3. Add or merge labeled JSONL into `datasets/pomona-tomato-risk-v0.1/data/`.
4. Run `python3 scripts/datasets/validate_pomona_dataset.py`.
5. Run `./scripts/huggingface/publish_dataset_to_hf.sh`.

Practical copy-paste commands: [datasets/README.md](../datasets/README.md).

## Label design

Pomona labels support compact agriculture reasoners: risk detection, missing-data requests, and blocked unsafe actions — not direct disease diagnosis or autonomous actuator control.

## Non-goals

- No raw third-party datasets in GitHub.
- No Hugging Face Git repositories nested inside this repo.
- No model weights or `.safetensors` in this repo.
- No large generated splits in GitHub unless intentionally tiny.
