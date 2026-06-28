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

### 3. `Okyanus/ai-pomona-agronomist-gemma4` — Hugging Face (weights)

**Not GitHub.** Published LoRA adapter + model card.

**Publish:** `HF_TOKEN=hf_... ./scripts/publish/huggingface.sh` from ML repo.

---

## Future repos (add when needed)

| Repo | When to create | Contains |
|------|----------------|----------|
| `pomona-tomato-reasoner` | Phase 3 — rule/ML reasoner gets its own training pipeline | Training + eval for tomato reasoner |
| `Okyanus/pomona-tomato-reasoner-v1` (HF) | When reasoner has trainable weights | Small reasoner model weights |
| `pomona-docs` | Only if docs outgrow platform repo | Public site, tutorials |
| `pomona-devices` | Only if firmware explodes (many boards) | ESP32, RP2040 firmware monorepo |

**Do not create yet:** Separate repos for `core`, `dashboard`, `model-router` — keep those in `pomona`.

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

Then publish each repo independently. See [PUBLISHING.md](./PUBLISHING.md).

---

## Summary table

| # | Name | Platform | Purpose |
|---|------|----------|---------|
| 1 | `pomona` | GitHub | Run the stack |
| 2 | `pomona-agronomist-llm` | GitHub | Train advisor LLM |
| 3 | `ai-pomona-agronomist-gemma4` | Hugging Face | Download weights |
| 4+ | Future reasoners | GitHub + HF each | When Phase 3+ ships |

**Total GitHub repos today: 2.** Not a monorepo.
