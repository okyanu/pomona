# Pomona architecture

Local-first edge platform for greenhouse and hydroponic automation — inspired by Home Assistant, built for agriculture.

## Data flow

```text
Devices / Simulator
       ↓ MQTT
  Pomona Core          ← ingest + API (✅ today)
       ↓
  Model Router         ← deterministic specialists + optional guarded models
       ↓
  Safety Checker       ← deterministic blocking and human-review flags
       ↓
  Automation Engine    ← suggestions + recorded decisions, no execution
       ↓
  Dashboard            ← monitoring, forecast previews, manual decisions
```

**Rule:** The LLM advises — it never directly controls actuators.

## Services

| Service | Role | Status |
|---------|------|--------|
| **core** | Sensor ingest, storage, REST API | ✅ MVP |
| **model-router** | Route tasks to models / rules | ✅ MVP |
| **dashboard** | Monitoring, previews, manual suggestion decisions | ⏳ Implemented locally; Phase 2 partial |
| **safety-checker** | Block unsafe recommendations | ⏳ Deterministic checks implemented; Phase 4 partial |
| **automation-engine** | YAML rules → suggestions | ⏳ Phase 6, partial |
| **digital-twin** | Illustrative forecast scenarios, not hardware commands | ⏳ Local preview |

Core uses SQLite for sensor events. Automation uses a separate SQLite file
on a named volume in Docker Compose, with bounded history retention. Neither
the model nor a recorded approval has a hardware execution path. Local
operation does not provide authenticated reviewer identity.

## First MVP (running now)

```text
greenhouse_tomato simulator → MQTT → core → model-router (stub)
```

Run: `./scripts/up.sh` then `./scripts/sim.sh`

## More detail

Maintainers: full architecture notes in `private/planning/` (local, not in Git).

Public progress: [PROJECT_STATUS.md](./PROJECT_STATUS.md) · [PHASES.md](./PHASES.md)
