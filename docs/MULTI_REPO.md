# Multi-repo layout

**Split-first is the correct approach.** This doc matches the current layout after `./scripts/split/extract-ml-repo.sh`.

See **[REPOS.md](./REPOS.md)** for the full catalog of current and future repos.

---

## Today: 2 GitHub repos + 1 Hugging Face

```text
GitHub   Okyanus/pomona                    ← platform (this repo)
GitHub   Okyanus/pomona-agronomist-llm     ← ML training (sibling folder)
HF       Okyanus/ai-pomona-agronomist-gemma4
```

---

## Split steps

```bash
# 1. Extract ML code to sibling repo
make split-ml

# 2. Publish ML repo
cd ../pomona-agronomist-llm
git init && git add . && git commit -m "init: agronomist LLM pipeline"
gh repo create pomona-agronomist-llm --public --source=. --push

# 3. Publish platform repo
cd ../pomona
make publish-github

# 4. Publish weights (any time, independent)
cd ../pomona-agronomist-llm
HF_TOKEN=hf_... ./scripts/publish/huggingface.sh
```

---

## What stays in `pomona`

- `models/registry/*.yaml` — metadata pointing to HF
- All `services/`, Docker, simulators, docs

## What moves to `pomona-agronomist-llm`

- Everything that was `models/agronomist-llm/`
- `models/checkpoints/` → `checkpoints/` in ML repo

---

## Do NOT split per service

Keep `core`, `dashboard`, `model-router` in one platform repo.
