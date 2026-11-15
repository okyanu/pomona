# Contributing to Pomona

Thank you for helping make Pomona open source. **Contributions are welcome** — code, docs, issues, models, and device templates.

## Open source

| Item | Detail |
|------|--------|
| **License** | [Apache-2.0](LICENSE) — use, modify, and distribute with attribution |
| **Platform repo** | This repo (`pomona`) — Docker stack, services, docs |
| **ML repo** | `pomona-agronomist-llm` (not yet published) — training pipeline |
| **Model weights** | [Hugging Face](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |

You do not need permission to fork, experiment, or open a PR.

---

## Quick start for contributors

```bash
git clone https://github.com/<your-github-user>/pomona.git
cd pomona
cp .env.example .env
./scripts/setup.sh
./scripts/up.sh
make bootstrap   # once: one Python 3.11 venv per service group (services/*/.venv)
make test        # every suite
```

Or by hand (Python 3.11, from the repo root; the pins are in `constraints-dev.txt`):

```bash
python3.11 -m venv services/core/.venv
services/core/.venv/bin/pip install -r services/core/requirements.txt -r services/dashboard/requirements.txt \
  -r services/safety-checker/requirements.txt -r services/digital-twin/requirements.txt \
  -r examples/simulators/requirements.txt -c constraints-dev.txt pytest httpx pyyaml
# the same for services/model-router (-r services/model-router/requirements.txt)
# and services/automation-engine (-r services/automation-engine/requirements.txt)
```

`make test` and `make test-local` are the same full suite.

**Updating a dependency:** edit the version in that service's `requirements.txt` (the file you edit by hand), then run
`make lock` (needs `pip install uv`) to regenerate the exact pins, `services/*/constraints.txt` and `constraints-dev.txt`.
Commit the requirements and the regenerated constraints together; `make lock UPGRADE=1` moves every pin to the newest version.

Read before coding:

1. [docs/architecture.md](docs/architecture.md) — system design and safety boundaries
2. [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) — what's done; pick unclaimed work
3. [docs/ROADMAP.md](docs/ROADMAP.md) — phase goals

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

**Good first issues:** tests, docs improvements, simulators, crop templates, dashboard polish.

---

## Development rules

- **One vertical slice** per PR — small and reviewable
- Every service: `GET /health`, JSON APIs, FastAPI + Pydantic
- **Never** let the LLM directly control actuators
- Run `make test` before opening a PR
- Update [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) if you complete a milestone
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
5. Wait for review (one maintainer, so it may take a while)

No force-push to `main`. No commits with secrets (`.env`, tokens, weights).

---

## Report bugs

Open a [GitHub Issue](https://github.com/okyanu/pomona/issues) with:

- OS (macOS / Linux / Windows)
- Steps to reproduce
- Expected vs actual behavior
- Output of `./scripts/check-prerequisites.sh` if relevant

---

## Code of conduct

Be respectful and constructive. See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

---

## Related repos

| Repo | Contribute there when… |
|------|------------------------|
| **pomona** | Platform, services, Docker, docs |
| **pomona-agronomist-llm** | Finetuning, datasets, HF upload scripts |
| **Hugging Face** | Model card, weights (via HF hub) |

Questions? Open a GitHub Discussion or Issue.
