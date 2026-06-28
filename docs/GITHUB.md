# GitHub setup

How to publish Pomona safely and run it anywhere.

## What goes to GitHub

| Included | Excluded (local only) |
|----------|------------------------|
| Source code in `services/`, `examples/`, `models/registry/` | `assets/` contents |
| Docs, templates, Docker files | `models/checkpoints/` (~750 MB) |
| Model registry YAML + HF links | `.env`, tokens, `private/` |
| CI workflow | `*.safetensors`, `*.pt`, raw datasets |

See [`.gitignore`](../.gitignore) for the full list.

## Publishing

**Two platforms, two scripts — do not mix them.**

| Platform | Script | Contents |
|----------|--------|----------|
| GitHub | `./scripts/publish/github.sh` | Code, docs, Docker |
| Hugging Face | `./scripts/publish/huggingface.sh` | Model weights only |

Full guide: [docs/PUBLISHING.md](./PUBLISHING.md)

One GitHub monorepo is enough. Model weights live on [Hugging Face](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4).

## First-time publish

```bash
cp .env.example .env
./scripts/publish/check.sh
./scripts/publish/github.sh

# After training — separate step:
HF_TOKEN=hf_... ./scripts/publish/huggingface.sh
```

## Hugging Face token (optional)

For gated base models (`google/gemma-4-E2B-it`) or Hub uploads:

1. Create a token at [huggingface.co/settings/tokens](https://huggingface.co/settings/tokens)
2. Add to `.env` (never commit):

```bash
HF_TOKEN=hf_...
```

3. Login locally when training:

```bash
huggingface-cli login
```

## Run anywhere

### Docker (recommended)

Works on any machine with Docker Desktop:

```bash
cp .env.example .env
make up              # MQTT + core + model-router (stub mode)
make sim             # sensor simulator (host)
make health
make advisor-health  # model-router
```

Optional Ollama profile (when you have a compatible local model):

```bash
docker compose --profile ollama up -d
# set POMONA_LLM_BACKEND=ollama in .env
```

### Pip (local dev without Docker)

```bash
./scripts/setup.sh
make test
make sim-pip         # requires Mosquitto running (make up or local broker)
```

## Model on Hugging Face

The Pomona Agronomist advisor is published at:

**[Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)**

Pomona references it via:

- `models/registry/agronomist-gemma4.yaml` — registry entry
- `services/model-router/` — API that builds prompts and calls stub/Ollama/HF backends

Full GPU inference lives in the sibling ML repo:

```bash
git clone https://github.com/Okyanus/pomona-agronomist-llm.git
cd pomona-agronomist-llm
HF_TOKEN=hf_... python deploy/app.py
```

## Pre-push checklist

- [ ] `git status` shows no `.env`, checkpoints, or `assets/` binaries
- [ ] No API keys in code or commit history
- [ ] `make test` passes
- [ ] README quickstart works on a clean clone + `docker compose up`
