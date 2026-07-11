# Contributing to Pomona

Thank you for helping make Pomona open source. **Contributions are welcome** — code, docs, issues, models, and device templates.

## Open source

| Item | Detail |
|------|--------|
| **License** | [Apache-2.0](../LICENSE) — use, modify, and distribute with attribution |
| **Platform repo** | This repo (`pomona`) — Docker stack, services, docs |
| **ML repo** | [pomona-agronomist-llm](https://github.com/Okyanus/pomona-agronomist-llm) — training pipeline |
| **Model weights** | [Hugging Face](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |

You do not need permission to fork, experiment, or open a PR.

---

## Quick start for contributors

```bash
git clone https://github.com/YOUR_USER/pomona.git
cd pomona
cp .env.example .env
./scripts/setup.sh
./scripts/up.sh
make test
```

Read before coding:

1. [docs/architecture.md](architecture.md) — system design and safety boundaries
2. [docs/PROJECT_STATUS.md](PROJECT_STATUS.md) — what's done; pick unclaimed work
3. [docs/ROADMAP.md](ROADMAP.md) — phase goals

---

## Ways to contribute

| Type | Examples |
|------|----------|
| **Code** | Dashboard, SQLite, reasoner, safety checker, tests |
| **Docs** | Install guides, tutorials, translations |
| **Models** | New `models/registry/*.yaml` + HF model |
| **Devices** | ESP32 firmware, simulators |
| **Templates** | Greenhouse / crop deployment templates |
| **Issues** | Bug reports, feature ideas, discussion |

**Good first issues:** Phase 2 (dashboard + persistence), tests, docs improvements.

---

## Development rules

- **One vertical slice** per PR — small and reviewable
- Every service: `GET /health`, JSON APIs, FastAPI + Pydantic
- **Never** let the LLM directly control actuators
- Run `make test` before opening a PR
- Update [docs/PROJECT_STATUS.md](PROJECT_STATUS.md) if you complete a milestone
- Match existing code style; minimal diff

### Safety

Agriculture software can affect real crops and people. Flag unsafe model output, require human review for actuators, and document limitations.

---

## Pull request process

1. Fork the repo and create a branch: `feature/short-description`
2. Make your changes with tests if applicable
3. Ensure `./scripts/check-prerequisites.sh` and `make test` pass
4. Open a PR against `main` with:
   - What changed and why
   - How you tested it
   - Screenshots if UI-related
5. Wait for review — we aim to respond to all PRs

No force-push to `main`. No commits with secrets (`.env`, tokens, weights).

---

## Report bugs

Open a [GitHub Issue](https://github.com/YOUR_USER/pomona/issues) with:

- OS (macOS / Linux / Windows)
- Steps to reproduce
- Expected vs actual behavior
- Output of `./scripts/check-prerequisites.sh` if relevant

---

## Code of conduct

Be respectful and constructive. See [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md).

---

## Related repos

| Repo | Contribute there when… |
|------|------------------------|
| **pomona** | Platform, services, Docker, docs |
| **pomona-agronomist-llm** | Finetuning, datasets, HF upload scripts |
| **Hugging Face** | Model card, weights (via HF hub) |

Questions? Open a GitHub Discussion or Issue.
