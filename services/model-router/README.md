# Pomona Model Router

Routes tasks to registered Pomona models.

Currently implements:

- **Agronomist Advisor** backed by [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)
- **Tomato Risk Reasoner** contract for [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- **Sensor Quality Reasoner** contract for local/unpublished `pomona-sensor-quality-reasoner-v0.1`

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + backend info |
| GET | `/v1/models` | List models from `pomona-model.yaml` registry |
| GET | `/v1/models/{id}` | Model metadata |
| POST | `/v1/advisor/explain` | Sensor-aware advisory explanation |
| POST | `/v1/reasoners/sensor-quality` | Sensor packet quality labels with rules-only fallback |
| POST | `/v1/reasoners/tomato-risk` | Tomato risk labels with rules-only fallback |

## Backends (`POMONA_LLM_BACKEND`)

| Value | Description |
|-------|-------------|
| `huggingface` | HF Inference API — set `HF_TOKEN` in `.env` (see [HF_USAGE.md](../../docs/HF_USAGE.md)) |
| `ollama` | Local Ollama on host |
| `stub` | Default — offline demo, no GPU |

## Example

```bash
curl -s http://localhost:8081/v1/advisor/explain \
  -H 'Content-Type: application/json' \
  -d @models/registry/examples/advisor-input.json
```

Tomato risk reasoner:

```bash
curl -s http://localhost:8081/v1/reasoners/tomato-risk \
  -H 'Content-Type: application/json' \
  -d '{
    "mode": "hybrid_guarded",
    "input": {
      "system_type": "controlled_greenhouse",
      "crop": "tomato",
      "growth_stage": "fruiting",
      "air_temperature_c": 31.0,
      "humidity_pct": 89.0,
      "ph": 7.4,
      "ec_ms_cm": 4.8,
      "substrate_temperature_c": 24.0,
      "substrate_moisture_pct": 44.0,
      "actuator_states": {"screen_energy_pct": 90},
      "symptoms": []
    }
  }'
```

Sensor quality reasoner:

```bash
curl -s http://localhost:8081/v1/reasoners/sensor-quality \
  -H 'Content-Type: application/json' \
  -d '{
    "mode": "hybrid_guarded",
    "input": {
      "farm_context": {
        "crop": "tomato",
        "system_type": "controlled_greenhouse",
        "zone_id": "greenhouse-a"
      },
      "sensor": {
        "air_temperature_c": 23.0,
        "backup_air_temperature_c": 35.0,
        "humidity_pct": 102.0,
        "ph": null,
        "ec_ms_cm": 2.1,
        "timestamp": "2026-07-07T10:00:00Z"
      },
      "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
    }
  }'
```

Modes:

| Mode | Status |
|------|--------|
| `rules_only` | Uses deterministic tomato rules now |
| `hybrid_guarded` | Falls back to deterministic rules until local LoRA inference is wired |
| `model_only` | Returns `501` until local LoRA inference is wired |

## Run locally

```bash
cd services/model-router
pip install -r requirements.txt
MODELS_DIR=../../models POMONA_LLM_BACKEND=stub uvicorn app.main:app --port 8081
```
