# Publishing guide

Three publish targets — **three different places**, not one Git repo for everything.

| Target | What | Script |
|--------|------|--------|
| **GitHub `Okyanus/pomona`** | Platform code, Docker, docs, dataset pipeline | `./scripts/publish/github.sh` |
| **GitHub `Okyanus/pomona-agronomist-llm`** | Agronomist training pipeline (split repo) | separate `git push` in that repo |
| **Hugging Face — models** | LoRA adapter weights + model card | see below |
| **Hugging Face — datasets** | Clean JSONL + schema + dataset card | `./scripts/huggingface/publish_dataset_to_hf.sh` |

> **Multi-repo recommended.** Platform + ML training are separate GitHub repos. Weights and dataset releases live on Hugging Face only.

---

## Published assets (current)

| Asset | GitHub (source of truth) | Hugging Face (release) | Status |
|-------|--------------------------|------------------------|--------|
| Platform stack | [Okyanus/pomona](https://github.com/Okyanus/pomona) | — | Active |
| Tomato risk reasoner v0.1.7 LoRA | [models/registry/tomato-risk-reasoner-v0.1.7.yaml](../models/registry/tomato-risk-reasoner-v0.1.7.yaml) + [docs/TOMATO_RISK_REASONER.md](./TOMATO_RISK_REASONER.md) | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) | **Published — do not republish unless you ship a new adapter version** |
| Water/irrigation reasoner v0.1.8 LoRA | [models/registry/water-irrigation-risk-reasoner-v0.1.yaml](../models/registry/water-irrigation-risk-reasoner-v0.1.yaml) + [docs/WATER_IRRIGATION_RISK_REASONER.md](./WATER_IRRIGATION_RISK_REASONER.md) | [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) | **Published release candidate — advisory only** |
| Actuator command gate v0.1 LoRA | [models/registry/actuator-command-gate-reasoner-v0.1.yaml](../models/registry/actuator-command-gate-reasoner-v0.1.yaml) + [docs/ACTUATOR_COMMAND_GATE_REASONER.md](./ACTUATOR_COMMAND_GATE_REASONER.md) | [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) | **Published research preview — below standalone gate; deterministic checker required** |
| Greenhouse sensor dataset | [datasets/pomona-tomato-risk-v0.1/](../datasets/pomona-tomato-risk-v0.1/) pipeline scaffold | [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) | Published dataset; do not republish from this repo unless you are doing a planned dataset release |
| Agronomist advisor LoRA | [models/registry/agronomist-gemma4.yaml](../models/registry/agronomist-gemma4.yaml) | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) | Separate ML repo publish flow |

---

## What stays on GitHub only (never push to Hugging Face)

| Path / content | Why |
|----------------|-----|
| `services/`, `docker-compose.yml`, `scripts/` (except HF copy step) | Platform runtime — not a model or dataset |
| `private/**` | Local training, adapter zips, Colab outputs, teacher datasets |
| `*.safetensors`, checkpoints, adapter zips | Weights belong on HF model repos only |
| `datasets/raw/`, `datasets/interim/`, `datasets/processed/` | Local working data (gitignored) |
| `private/colab/teacher-datasets/**` | Intermediate training artifacts |
| `scripts/datasets/build_pomona_*teacher*.py` outputs | Teacher/label-list builders — local only |
| Rule checker + hybrid runner code | Platform safety logic — stays in GitHub |
| Normalizer scaffolds (`normalize_*.py`) | Pipeline code, not release data |

---

## What goes to Hugging Face model repo only

**Repo:** [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)

| Include | Exclude |
|---------|---------|
| `adapter_model.safetensors`, `adapter_config.json` | Full platform repo |
| Tokenizer files bundled with the adapter | Dataset JSONL (separate dataset repo) |
| `labels.json`, `sample_input.json` | Training scripts, teacher datasets |
| Model card `README.md` | Rule checker Python code |

**Script:** `./scripts/huggingface/publish_tomato_reasoner_to_hf.sh`
**Skip this** if the model is already on HF and you are not releasing a new checkpoint. Re-running overwrites the HF model card and re-uploads weights.

For the agronomist model, use `./scripts/publish/huggingface.sh` from the ML repo (see [HF_USAGE.md](./HF_USAGE.md)).

---

## What goes to Hugging Face dataset repo only

**Current published dataset repo:** [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)

The local tomato-risk dataset scaffold is kept in `datasets/pomona-tomato-risk-v0.1/`. Only publish it when you intentionally create a new cleaned dataset release.

Copied by `publish_dataset_to_hf.sh`:

- `DATASET_CARD.md` → HF `README.md`
- `LICENSES.md`, `CITATION.cff`
- `schema/*.json`
- `data/samples.jsonl`, `data/eval_cases.jsonl`, `data/golden_eval.jsonl`
- Generated `data/train.jsonl`, `validation.jsonl`, `test.jsonl` (from local processed build)

**Do not copy to HF dataset repo:**

- Model weights or LoRA adapters
- `private/**` teacher datasets
- Raw third-party downloads from `datasets/raw/`

---

## Architecture

```text
GitHub:  Okyanus/pomona
           ├── platform code, schemas, docs
           ├── datasets/pomona-tomato-risk-v0.1/   (source pipeline)
           └── models/registry/*.yaml              (metadata only)

HF model:   Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora   ← adapter weights (published)
HF dataset: Okyanus/greenhouse-sensor-data                   ← published dataset
HF model:   Okyanus/ai-pomona-agronomist-gemma4              ← advisor weights
```

---

## Scripts

| Script | Purpose | When to run |
|--------|---------|-------------|
| [`scripts/publish/check.sh`](../scripts/publish/check.sh) | Block secrets and large files | Before any GitHub push |
| [`scripts/publish/github.sh`](../scripts/publish/github.sh) | Push platform to GitHub | Platform code/doc changes |
| [`scripts/huggingface/publish_tomato_reasoner_to_hf.sh`](../scripts/huggingface/publish_tomato_reasoner_to_hf.sh) | Upload tomato LoRA adapter | **New adapter version only** |
| [`scripts/huggingface/publish_water_irrigation_reasoner_to_hf.sh`](../scripts/huggingface/publish_water_irrigation_reasoner_to_hf.sh) | Upload water/irrigation LoRA adapter | Release-candidate updates only |
| [`scripts/huggingface/publish_actuator_command_gate_reasoner_to_hf.sh`](../scripts/huggingface/publish_actuator_command_gate_reasoner_to_hf.sh) | Upload actuator-gate LoRA adapter | Research-preview updates only |
| [`scripts/huggingface/publish_dataset_to_hf.sh`](../scripts/huggingface/publish_dataset_to_hf.sh) | Copy validated JSONL to HF dataset checkout | Dataset/schema changes |
| [`scripts/publish/huggingface.sh`](../scripts/publish/huggingface.sh) | Agronomist weights (ML repo wrapper) | Agronomist model updates |

### Platform → GitHub

```bash
export GITHUB_USER=Okyanus
export GITHUB_REPO=pomona

./scripts/publish/check.sh
./scripts/publish/github.sh
```

### Dataset → Hugging Face

```bash
./scripts/huggingface/publish_dataset_to_hf.sh
PUSH_TO_HF=1 ./scripts/huggingface/publish_dataset_to_hf.sh   # commit + push HF dataset repo
```

### Tomato reasoner → Hugging Face (new version only)

```bash
PUSH_TO_HF=1 ./scripts/huggingface/publish_tomato_reasoner_to_hf.sh
```

Requires `private/colab/adapters/v0.1.7-risk-label-list-normalfix.zip` locally. Skip if [v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) is already current.

---

## Pre-push checklist

- [ ] `git status --ignored` — no checkpoints, `.env`, or `assets/` binaries staged
- [ ] `make publish-check` passes
- [ ] Weights go to HF model repos, not GitHub
- [ ] Teacher datasets and adapter zips stay in `private/`
- [ ] Do not re-run model publish scripts for assets already live on Hugging Face
