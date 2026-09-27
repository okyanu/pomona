# Pomona Project Status

Living record of completed work. **Update when a phase completes** — see checklist in [PHASES.md](./PHASES.md).

## Phase progress (summary)

| | |
|---|---|
| **Total phases** | 11 (Phase 0 – Phase 10) |
| **Completed** | Phase 0 ✅, Phase 1 ✅ |
| **Primary focus** | Phase 2 ⏳ |
| **Active / partial** | Phases 2, 3, 4, 5, 6, 7, 9, 10 |
| **Platform version** | `v0.1.0-alpha.1` |
| **Canonical tracker** | [PHASES.md](./PHASES.md) |

Agents: read [PHASES.md](./PHASES.md) before starting work.

Local checkpoint (2026-09-25): removed unsupported root-moisture proxy, added
offline twin-versus-persistence replay, persisted advice-card evidence and an
offline exact-source retrieval prototype. Unit suite: 198 passed, 1 skipped;
local integration passed. No field calibration, full RAG, model release or phase
completion claimed. See [twin](./DIGITAL_TWIN.md), [cards](./ADVICE_CARDS.md) and
[retrieval experiment](./LOCAL_ADVICE_RETRIEVAL.md).

Local checkpoint (2026-09-27): first real-hardware step prepared: a two-zone
[watercress pilot](./WATERCRESS_PILOT.md) with SD-card logger firmware (not yet
bench-tested), a CSV importer into Core observations, and plant-log templates.
Monitoring only; no watercress reasoner or actuator path. Unit suite: 203
passed, 1 skipped.

Local checkpoint (2026-09-16): validation, MQTT reliability, suggestion expiry
and evaluation hygiene are implemented and unit-tested. See
[reliability hardening](./RELIABILITY_HARDENING.md) for limits and outstanding
checks. This checkpoint does not complete a phase or approve a model release.

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

## Small Reasoner Checkpoint ⏳ Local integration next

**Goal:** Use narrow specialist models with deterministic safety guardrails inside the Pomona platform.

| Reasoner | Status | Decision |
|----------|--------|----------|
| Tomato risk `v0.1.7` | Published on Hugging Face | Use with deterministic tomato rules |
| Water/irrigation `v0.1.8` | Published release candidate | Advisory; deterministic validation and human review required |
| Sensor quality `v0.1.1-boundary` | Local candidate, not published | Use for first integration |
| Safety triage `v0.1` | Local candidate, not published | Use for first integration |
| Actuator command gate `v0.1` | Published research preview | Below standalone gate; deterministic checker is final authority |
| Actuator command gate `v0.1.1-hardcases` | Local regression | Do not use |
| Actuator command gate `v0.1.2-correction` | Independent-eval regression | Do not use |

Published Hugging Face assets (checked 2026-09-27):

```text
model:   Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora
model:   Okyanus/pomona-tomato-risk-reasoner-v0.1.7-GGUF   (research preview, 2026-09-27)
model:   Okyanus/pomona-tomato-risk-reasoner-v0.1.7-MLX    (research preview, 2026-09-27)
model:   Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora
model:   Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-GGUF
model:   Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-MLX
model:   Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-lora
model:   Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-GGUF
model:   Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-MLX
model:   Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora
model:   Okyanus/ai-pomona-agronomist-gemma4
dataset: Okyanus/greenhouse-sensor-data
space:   Okyanus/pomona-greenhouse-demo
```

Sensor-quality and safety-triage adapters remain unpublished. Sensor-quality
training is paused (2026-09-27): two controlled retrains failed the holdout gate
on exact time/threshold checks that the deterministic rules already perform; see
`models/registry/sensor-quality-reasoner-v0.1.yaml`.

Endpoint status:

```text
services/model-router:
  done: POST /v1/reasoners/sensor-quality
  done: POST /v1/reasoners/tomato-risk (rules + guarded/model-only local Ollama GGUF)
  done: POST /v1/reasoners/water-irrigation-risk (guarded local runtime supported)
  done: POST /v1/reasoners/nutrient-ph-ec (schema and semantic validation + guarded local Ollama runtime)
  done: POST /v1/reasoners/safety-triage (deterministic fallback; model runtime pending)
  next: improve tomato model-only quality and wire the remaining specialist runtimes

services/safety-checker:
  keep as deterministic final authority: POST /v1/actuator-command-gate/check
```

Future models after platform integration:

```text
nutrient / pH-EC reasoner
crop-specific reasoners
digital twin scenario reasoner
```

No model weights are committed to GitHub. Local adapters stay under `private/` and publishable weights belong on Hugging Face.

---

## Phase 2 — Dashboard ⏳ In progress

### Local zone-monitoring checkpoint (2026-09-05)

Farm/zone URL selection, device last-seen/quality panel, scoped 100-record
history pages and CSV downloads are implemented locally. Scope follows the
guarded views and suggestion evaluation; cross-zone review requests are rejected
when scoped. Legacy unscoped audit summaries are hidden rather than mislabeled.
Partial sensor observations remain monitoring-only, with no state fusion or
actuator execution. Regression tests cover scope forwarding, history parameters,
cross-zone suggestion filtering, escaped rendering, and outage recovery.
Simulator soak and physical sensor trials are still pending.

**Goal:** Web UI + SQLite persistence.

See `private/planning/ROADMAP.full.md` for deliverables (local).

### Current local checkpoint (2026-07-21)

| Deliverable | Status | Verification |
|---|---|---|
| SQLite sensor-event persistence | ✅ local | restart recovery in `make local-check` |
| Read-only dashboard | ✅ local | HTML and API assertions pass |
| Guarded pipeline view | ✅ local | high-risk and routine scenarios pass |
| Summary-only audit view | ✅ local | payload redaction test passes |
| Backup and restore scripts | ✅ local | SQLite online-backup round-trip passes |
| Docker Compose deployment smoke test | ✅ local | all six services healthy; benchmark assertions pass |
| Optional sensor-ingestion API-key auth (2026-08-25) | ✅ local | `Authorization: Bearer <API_KEY>` required on `POST /v1/sensors/events` only when `API_KEY` is set; verified 401/201 against the live Docker stack; default (unset) behavior unchanged |

The local Docker, MQTT simulation, backup/recovery, and pre-hardware safety
checks are complete. This is still not a production or hardware validation
result; real device testing remains a separate milestone. Authentication
exists only on core's ingestion endpoint so far — model-router,
safety-checker, digital-twin, and dashboard remain unauthenticated.

---

## Phase 6 — Automation engine ⏳ Partial

**Goal:** Move from recommendation to human-approved suggestion, never
autonomous action.

### Current checkpoint (2026-08-29)

| Deliverable | Status | Verification |
|---|---|---|
| YAML automation rule format (`services/automation-engine/app/rules.yaml`) | ✅ | validated at startup; rejects forbidden actions and duplicate IDs |
| `POST /v1/automation/evaluate` | ✅ | verified against a live Docker container |
| Manual approve/reject workflow | ✅ | verified live: evaluate -> approve -> pending count drops |
| Rules: high humidity/fungal fan suggestion, high/low EC alert, pH out-of-range alert, water-level check | ✅ | all 5 covered by tests |
| Public deployment ([automation-engine-fawn.vercel.app](https://automation-engine-fawn.vercel.app)) | ✅ | live on Vercel, documentation-style landing page at `/` |
| Dashboard integration (evaluate, list, approve/reject) | ✅ local | proxy and JavaScript regression tests |
| SQLite suggestion history (2026-09-05 local checkpoint) | ✅ local | reopen recovery, retention, first-decision-wins tests; named Compose volume |
| Request feedback and reviewer labels | ✅ local | busy buttons, visible failures; reviewer labels are self-reported, not verified |

Local Compose stores suggestions and decisions in SQLite. Host/pip users
enable persistence with `AUTOMATION_DB_PATH`; without it, storage remains
ephemeral (including the existing serverless demo). The latest 200 completed
decisions are retained by default; pending suggestions are not pruned and can
grow until reviewed. This is not an unlimited
audit archive. These local changes do not update public deployments until
explicitly published. There is no execution path from an
approved suggestion to any actuator or hardware — approval only records a
decision. `load_rules` refuses to start if any rule's action matches
Pomona's forbidden actuator/chemical vocabulary, so a rules-file edit alone
cannot make this service unsafe.

---

## Phase 7 — Public browser demo ⏳ Partial

**Goal:** Let people try Pomona from a browser without cloning or running Docker.

### Current checkpoint (2026-08-22)

| Deliverable | Status | Verification |
|---|---|---|
| Static guarded demo ([Space](https://huggingface.co/spaces/Okyanus/pomona-greenhouse-demo)) | ✅ live | 3 preset scenarios verified against the platform's own deterministic logic |
| Linked from HF Collection, README, model catalog, `llms.txt` | ✅ | — |
| Mobile layout | ✅ | verified at 375×812; single-column, no overflow, readable |
| Accessibility labels | ✅ | all form inputs now have `label for=` associations; preset group has `role="group"` |
| Full platform playground (dashboard + all reasoners, not just tomato) | ⬜ | not started |

The demo runs a client-side JavaScript port of the exact deterministic tomato
rules in `services/model-router/app/tomato_reasoner.py`, kept free by using a
static Hugging Face Space (Gradio/Docker Spaces require a paid tier). It will
be extended to call the live model-router API once a public backend exists.

---

## When a phase completes — update checklist

1. [PHASES.md](./PHASES.md) — status table + completed count
2. [ROADMAP.md](./ROADMAP.md) — status column
3. [PROJECT_STATUS.md](./PROJECT_STATUS.md) — deliverables section (this file)
4. [README.md](https://github.com/okyanu/pomona/blob/main/README.md) — "Project phases" table
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
- Update [PHASES.md](./PHASES.md), [PROJECT_STATUS.md](./PROJECT_STATUS.md), and [README.md](https://github.com/okyanu/pomona/blob/main/README.md) when a phase completes
- Owner notes go in `private/` (gitignored)
