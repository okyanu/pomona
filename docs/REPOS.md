# Possible Pomona repositories

Where each piece of the ecosystem lives. **Split-first layout** (recommended).

---

## Required repos

### 1. `Okyanus/pomona` — Platform

**This folder.** Everything needed to run the edge AI stack locally.

```text
services/          core, dashboard, model-router, safety-checker, automation-engine
examples/          simulators
devices/           ESP32 firmware (future)
templates/         greenhouse-tomato deployment template
models/registry/   YAML metadata only — points to Hugging Face
docs/              architecture, roadmap, publishing
docker-compose.yml
```

**Who clones it:** Platform developers, users running Docker, contributors to dashboard/automation.

**Does NOT contain:** Training code, checkpoints, datasets, model weights.

---

### 2. `Okyanus/pomona-agronomist-llm` — ML training

Extracted from `models/agronomist-llm/` via `./scripts/split/extract-ml-repo.sh`.

```text
src/               digital twin pipeline
finetune/          LoRA training
deploy/            Gradio app + upload_to_hub.py
checkpoints/       local weights (gitignored)
data/              training data (gitignored)
```

**Who clones it:** You, when finetuning or updating the agronomist model.

**Links to:** Platform via HF model ID; platform does not need this repo at runtime.

---

### 3. Hugging Face — published models and datasets

| Repo | Type | Publish script |
|------|------|----------------|
| [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) | Advisor LoRA | ML repo `./scripts/publish/huggingface.sh` |
| [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) | Tomato reasoner LoRA | **Published** — platform `./scripts/huggingface/publish_tomato_reasoner_to_hf.sh` for new versions only |
| [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) | Water/irrigation reasoner LoRA | Published release candidate — `./scripts/huggingface/publish_water_irrigation_reasoner_to_hf.sh` |
| [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) | Actuator-gate LoRA | Published research preview — deterministic checker remains final |
| [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) | Published greenhouse sensor dataset | `./scripts/huggingface/publish_dataset_to_hf.sh` for future dataset releases |

Platform GitHub repo keeps code, schemas, and registry YAML — not `.safetensors` or teacher datasets.

---

## Future repos (add when needed)

| Repo | When to create | Contains |
|------|----------------|----------|
| `pomona-tomato-reasoner` | If tomato training outgrows `private/colab/` | Training + eval for tomato reasoner |
| `pomona-docs` | Only if docs outgrow platform repo | Public site, tutorials |
| `pomona-devices` | Only if firmware explodes (many boards) | ESP32, RP2040 firmware monorepo |

**Do not create yet:** Separate repos for `core`, `dashboard`, `model-router` — keep those in [Okyanus/pomona](https://github.com/Okyanus/pomona).

---

## Visual map

```text
                    ┌─────────────────────────┐
                    │  GitHub: pomona         │
                    │  (platform)             │
                    │  docker compose up      │
                    └───────────┬─────────────┘
                                │ reads registry YAML
                                ▼
                    ┌─────────────────────────┐
                    │  HF: ai-pomona-         │
                    │  agronomist-gemma4      │
                    │  (weights)              │
                    └───────────▲─────────────┘
                                │ upload
                    ┌───────────┴─────────────┐
                    │  GitHub: pomona-        │
                    │  agronomist-llm         │
                    │  (train + deploy)       │
                    └─────────────────────────┘
```

---

## Split command

```bash
# From pomona/ root — moves ML code to ../pomona-agronomist-llm
./scripts/split/extract-ml-repo.sh
```

Then publish each repo independently. Maintainer publish checklists are local only (not in this public repo).

---

## Summary table

| # | Name | Platform | Purpose |
|---|------|----------|---------|
| 1 | `pomona` | GitHub | Run the stack |
| 2 | `pomona-agronomist-llm` | GitHub | Train advisor LLM |
| 3 | `ai-pomona-agronomist-gemma4` | Hugging Face | Download weights |
| 4+ | Future reasoners | GitHub + HF each | When Phase 3+ ships |

**Total GitHub repos today: 2.** Not a monorepo.
