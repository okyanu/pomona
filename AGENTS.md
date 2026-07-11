# AGENTS.md — AI coding agent guide (Cursor, Claude, Codex)

This file is the **single entry point** for AI assistants working on Pomona.

Human quickstart: [docs/GETTING_STARTED.md](docs/GETTING_STARTED.md)

---

## Project summary

**Pomona** is an open edge AI platform for agriculture (tomato greenhouse MVP).

- **This repo (`pomona`)**: platform — Docker, MQTT, core API, model-router, simulators
- **Sibling repo (`pomona-agronomist-llm`)**: ML training — not in this clone after split
- **Hugging Face**: [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) — weights only

**Current phase:** 2 — dashboard + SQLite persistence (see [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md))

**Maturity:** Early MVP. Works: `./scripts/up.sh`, simulator, REST API, stub advisor. Missing: dashboard UI, DB persistence, real LLM in router, reasoner, safety, automation, ESP32.

---

## Read first (in order)

1. [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) — what's done; do not redo
2. [docs/PHASES.md](docs/PHASES.md) — current phase (short)
3. [docs/architecture.md](docs/architecture.md) — system design (short)
4. [docs/REPOS.md](docs/REPOS.md) — which repo owns what
5. [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md) — timetable, Codex/Cursor workflow, future model planning

Detailed deliverables: `private/planning/` on maintainer machine (gitignored).

Personal owner notes live in `private/` (gitignored) — not in public docs.

Use [docs/EXECUTION_PLAN.md](docs/EXECUTION_PLAN.md) as the active task board: read it before "what next" work, remove completed active items, and add dated decisions/work log entries.

---

## Hard rules

### Architecture

```text
Sensor / Simulator → MQTT → pomona-core → DB → model-router
  → reasoner / advisor LLM → safety-checker → automation-engine → dashboard
```

**Never** let the LLM directly control actuators.

### Code style

- Working vertical slices over perfect abstractions
- Python + FastAPI; type hints; Pydantic schemas
- Every service: `GET /health`, JSON responses
- Config via environment variables
- Docker Compose (not Kubernetes)
- Minimal diff; match existing patterns
- One test for core reasoning logic when adding rules

### Service names

`pomona-core`, `pomona-dashboard`, `pomona-model-router`, `pomona-safety-checker`, `pomona-automation-engine`

### Safety (always enforce)

Block or flag: pesticide dosage, definite diagnosis without evidence, fertilizer overdose, unsafe actuator commands, ignoring missing sensor data.

### Publishing

- Platform code → GitHub `pomona` only
- Weights → Hugging Face only (never commit `.safetensors`)
- Personal files → `private/` (gitignored)
- Run `make publish-check` before any push

---

## Repo layout

```text
services/core/           ✅ FastAPI + MQTT ingest
services/model-router/   ✅ stub/ollama advisor
services/dashboard/      ⏳ Phase 2
models/registry/         YAML metadata → HF models
examples/simulators/     greenhouse_tomato.py
private/                 gitignored owner notes
docs/                    public documentation
```

---

## Local commands

```bash
cp .env.example .env
./scripts/setup.sh   # first time
./scripts/up.sh      # Docker full stack (mac/linux/windows)
./scripts/sim.sh     # simulator (2nd terminal)
curl http://localhost:8080/health
make test            # optional — pytest
./scripts/down.sh
```

Install details: [docs/INSTALL.md](docs/INSTALL.md)

---

## Sensor event schema

```json
{
  "device_id": "esp32-greenhouse-01",
  "farm_id": "demo-farm",
  "zone_id": "greenhouse-a",
  "crop": "tomato",
  "growth_stage": "flowering",
  "air_temperature_c": 31.2,
  "humidity_pct": 88,
  "ec_ms_cm": 3.4,
  "ph": 7.5,
  "soil_moisture_pct": 42,
  "timestamp": "2026-06-24T10:00:00Z"
}
```

MQTT topic: `pomona/{farm_id}/{zone_id}/sensor/{device_id}/state`

---

## Open source

Apache-2.0 — contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Workflow for agents

1. Read [PHASES.md](docs/PHASES.md) and PROJECT_STATUS — pick **one** task aligned with current phase
2. Implement smallest working slice
3. Run `make test`; if Docker available, `make up` + `make sim`
4. When a **phase completes**, update [PHASES.md](docs/PHASES.md), [PROJECT_STATUS.md](docs/PROJECT_STATUS.md), [README.md](README.md), [ROADMAP.md](docs/ROADMAP.md)
5. Update `private/DAILY_LOG.md` for owner notes (optional, local only)
6. **Do not commit** unless the user asks

## What NOT to build yet

- Kubernetes / cloud infra
- Per-service GitHub repos
- LLM direct actuator control
- Scope beyond tomato greenhouse for v0.1

---

## Related files

| Tool | File |
|------|------|
| Cursor | [.cursor/rules/pomona.mdc](.cursor/rules/pomona.mdc) |
| GitHub Copilot / Codex | [.github/copilot-instructions.md](.github/copilot-instructions.md) |
| Extended rules | [docs/CURSOR_RULES.md](docs/CURSOR_RULES.md) |
