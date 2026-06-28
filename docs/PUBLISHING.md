# Publishing guide

Three publish targets — **three different places**, not one Git repo for everything.

| Target | What | Script |
|--------|------|--------|
| **GitHub `pomona`** | Platform code, Docker, docs | `./scripts/publish/github.sh` |
| **GitHub `pomona-agronomist-llm`** | Training pipeline (split repo) | separate `git push` in that repo |
| **Hugging Face** | Model weights only | `./scripts/publish/huggingface.sh` |

> **Multi-repo recommended.** This folder mixes platform + ML training. For easier control, use **2 GitHub repos** — see [MULTI_REPO.md](./MULTI_REPO.md).

---

## Architecture

```text
GitHub:  Okyanus/pomona                      ← platform (services, docker, docs)
GitHub:  Okyanus/pomona-agronomist-llm       ← training code (optional split)
HF:      Okyanus/ai-pomona-agronomist-gemma4 ← weights
```

**Not recommended:** one GitHub repo per service (`pomona-core`, `pomona-dashboard`, …).

**Recommended:** one platform repo + one ML repo + Hugging Face for weights.

---

## Scripts (this repo)

| Script | Purpose |
|--------|---------|
| [`scripts/publish/check.sh`](../scripts/publish/check.sh) | Block secrets and large files |
| [`scripts/publish/github.sh`](../scripts/publish/github.sh) | Push **platform** to GitHub |
| [`scripts/publish/huggingface.sh`](../scripts/publish/huggingface.sh) | Push **weights** to Hugging Face |

### Platform → GitHub

```bash
export GITHUB_USER=Okyanus
export GITHUB_REPO=pomona

./scripts/publish/check.sh
./scripts/publish/github.sh          # first push
./scripts/publish/github.sh push     # updates
```

### Weights → Hugging Face

```bash
export HF_TOKEN=hf_...
./scripts/publish/huggingface.sh

# Or from a checkpoint:
ADAPTER_DIR=models/checkpoints/chekpoint-1728 ./scripts/publish/huggingface.sh
```

GitHub and Hugging Face are **independent** — update either without touching the other.

---

## Typical workflow

### Platform developer (no ML)

```bash
git clone git@github.com:Okyanus/pomona.git
cp .env.example .env
make up
```

No training code, no checkpoints — small clone.

### ML developer

```bash
git clone git@github.com:Okyanus/pomona-agronomist-llm.git
# train, then:
HF_TOKEN=hf_... python deploy/upload_to_hub.py
```

### Full stack locally (both clones)

```bash
~/pomona/                    # platform
~/pomona-agronomist-llm/     # training (optional, for finetune only)
```

Platform reads the model from Hugging Face at runtime — no need for the ML repo to run Docker.

---

## Future models

Each model: **one HF repo** + optional **one GitHub repo** if it has training code. Platform stays one repo with `models/registry/*.yaml` metadata files.

---

## Pre-push checklist

- [ ] `git status --ignored` — no checkpoints, `.env`, or `assets/` binaries staged
- [ ] `make publish-check` passes
- [ ] Training code going to `pomona-agronomist-llm`, not bloating `pomona`
