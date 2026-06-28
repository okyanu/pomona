# Pomona architecture

Local-first edge platform for greenhouse and hydroponic automation — inspired by Home Assistant, built for agriculture.

## Data flow

```text
Devices / Simulator
       ↓ MQTT
  Pomona Core          ← ingest + API (✅ today)
       ↓
  Model Router         ← advisor / reasoner (✅ stub today)
       ↓
  Safety Checker       ← filter unsafe output (planned)
       ↓
  Automation Engine    ← suggested actions only (planned)
       ↓
  Dashboard            ← UI (planned)
```

**Rule:** The LLM advises — it never directly controls actuators.

## Services

| Service | Role | Status |
|---------|------|--------|
| **core** | Sensor ingest, storage, REST API | ✅ MVP |
| **model-router** | Route tasks to models / rules | ✅ MVP |
| **dashboard** | Live data and alerts | ⏳ Phase 2 |
| **safety-checker** | Block unsafe recommendations | ⏳ Phase 4 |
| **automation-engine** | YAML rules → suggestions | ⏳ Phase 6 |

## First MVP (running now)

```text
greenhouse_tomato simulator → MQTT → core → model-router (stub)
```

Run: `./scripts/up.sh` then `./scripts/sim.sh`

## More detail

Maintainers: full architecture notes in `private/planning/` (local, not in Git).

Public progress: [PROJECT_STATUS.md](./PROJECT_STATUS.md) · [PHASES.md](./PHASES.md)
