# Architecture

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

**Hard rule:** the LLM advises — it never directly controls actuators.

## Services

| Service | Role | Status |
|---------|------|--------|
| **core** | Sensor ingest, storage, REST API | ✅ MVP |
| **model-router** | Route tasks to models / rules | ✅ MVP |
| **dashboard** | Live data and alerts | ⏳ Phase 2 |
| **safety-checker** | Block unsafe recommendations | ⏳ Phase 4 |
| **automation-engine** | YAML rules → suggestions | ⏳ Phase 6 |

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

## Model integration chain

```text
sensor-quality
  -> tomato-risk
  -> safety-triage
  -> deterministic actuator-command gate
  -> dashboard / human approval
```

Every reasoner/advisor output passes through a **deterministic** safety
checker before it can ever reach an actuator. See [Model Status](Model-Status).

## More detail

Full architecture notes: [docs/architecture.md](https://github.com/Okyanus/pomona/blob/main/docs/architecture.md) · [docs/PROJECT_STATUS.md](https://github.com/Okyanus/pomona/blob/main/docs/PROJECT_STATUS.md)
