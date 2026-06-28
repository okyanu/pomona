# Pomona Project Status

Living record of completed work. **Update when a phase completes** — see checklist in [PHASES.md](./PHASES.md).

## Phase progress (summary)

| | |
|---|---|
| **Total phases** | 11 (Phase 0 – Phase 10) |
| **Completed** | Phase 0 ✅, Phase 1 ✅ |
| **In progress** | Phase 2 ⏳ |
| **Canonical tracker** | [PHASES.md](./PHASES.md) |

Agents: read [PHASES.md](./PHASES.md) before starting work.

---

## Phase 0 — Positioning and repo setup ✅

**Goal:** Make the project understandable in 60 seconds.

### 0a. Monorepo reorganization (2026-06-24)

| Action | Result |
|--------|--------|
| Created `services/` | Platform services |
| Moved planning markdown → `docs/` | ROADMAP, plans, standards |
| Note | Later **split-first**: ML code → `pomona-agronomist-llm` repo |

### 0c. Multi-repo split (2026-06-24)

| Action | Result |
|--------|--------|
| Extracted ML training | `../pomona-agronomist-llm/` (sibling Git repo) |
| Platform keeps | `models/registry/*.yaml` metadata only |
| Script | `scripts/split/extract-ml-repo.sh` |
| Docs | `docs/REPOS.md` — full repo catalog |

### 0b. Phase 0 completion (2026-06-24)

| Deliverable | Status |
|-------------|--------|
| Monorepo structure | ✅ |
| README | ✅ |
| `docs/architecture.md` | ✅ |
| `docs/ROADMAP.md` | ✅ |
| `docs/DAILY_LOG.md` | ✅ |
| `docs/CURSOR_RULES.md` | ✅ |
| `docs/HF_MODEL_CARD_TODO.md` | ✅ |
| `LICENSE` (Apache-2.0) | ✅ |
| Root `.gitignore` | ✅ |
| This status file | ✅ |
| GitHub remote | ⏳ User action — see `docs/GITHUB.md` |

**Success condition met:** A visitor can read README + architecture and understand Pomona.

---

## Phase 1 — Local MVP skeleton ✅

**Goal:** Run the first local system; simulated greenhouse data visible in logs/API.

| Deliverable | Status | Location |
|-------------|--------|----------|
| `docker-compose.yml` | ✅ | Root |
| Mosquitto MQTT broker | ✅ | `infra/mosquitto/` |
| FastAPI `pomona-core` | ✅ | `services/core/` |
| `/health` endpoint | ✅ | `GET /health` |
| `/v1/sensors/events` | ✅ | `POST /v1/sensors/events` |
| MQTT ingest | ✅ | Subscribes to `pomona/+/+/sensor/+/state` |
| In-memory sensor store | ✅ | Last 500 events |
| Sensor simulator | ✅ | `examples/simulators/greenhouse_tomato.py` |
| `.env.example` | ✅ | Root |
| `Makefile` | ✅ | Root |

**Success condition:** `docker compose up -d` + simulator → readings in core logs and `GET /v1/sensors/events`.

**Not in Phase 1 (deferred):**
- PostgreSQL / SQLite persistence → Phase 2 / Week 2 Day 8
- Dashboard → Phase 2
- Reasoner, safety, automation → Phases 3–6

---

## Phase 1b — GitHub-safe repo + Hugging Face integration ✅

**Goal:** Publish-ready repo; plug-and-play Docker/pip; link HF agronomist model.

| Deliverable | Status | Location |
|-------------|--------|----------|
| Strict `.gitignore` / `.dockerignore` | ✅ | Root — excludes assets, checkpoints, weights, secrets |
| `docs/GITHUB.md` | ✅ | Publish checklist + HF token setup |
| `pomona-model.yaml` | ✅ | `models/registry/agronomist-gemma4.yaml` |
| Model-router service | ✅ | `services/model-router/` — `/v1/advisor/explain` |
| HF model linked | ✅ | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |
| `pyproject.toml` + `scripts/setup.sh` | ✅ | Pip install path |
| GitHub Actions CI | ✅ | `.github/workflows/ci.yml` |
| Ollama compose profile | ✅ | `docker compose --profile ollama` |

**Backends:** `stub` (default), `ollama`, `huggingface` (local GPU via deploy/app.py)

---

## Phase 2 — Dashboard ⏳ In progress

**Goal:** Web UI + SQLite persistence.

See `private/planning/ROADMAP.full.md` for deliverables (local).

---

## When a phase completes — update checklist

1. [PHASES.md](./PHASES.md) — status table + completed count
2. [ROADMAP.md](./ROADMAP.md) — status column
3. [PROJECT_STATUS.md](./PROJECT_STATUS.md) — deliverables section (this file)
4. [README.md](../README.md) — "Project phases" table
5. `private/DAILY_LOG.md` — optional (local)

---

## Quick reference for agents

**Current focus:** Phase 2 — database persistence + dashboard skeleton.

**Do not:**
- Let the LLM directly control actuators
- Build Kubernetes or multi-cloud infra
- Expand beyond tomato greenhouse for v0.1

**Always:**
- Read `AGENTS.md` and `docs/CURSOR_RULES.md` before coding
- Add `/health` to every new service
- Return JSON from every API endpoint
- Update [PHASES.md](./PHASES.md), [PROJECT_STATUS.md](./PROJECT_STATUS.md), and [README.md](../README.md) when a phase completes
- Owner notes go in `private/` (gitignored)
