# Pomona Model Router

Routes tasks to registered Pomona models.

Currently implements:

- **Agronomist Advisor** backed by [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)
- **Tomato Risk Reasoner** contract for [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- **Sensor Quality Reasoner** contract for local/unpublished `pomona-sensor-quality-reasoner-v0.1`
- **Actuator Command Gate** advisory contract backed by the deterministic safety rules
- **Safety Triage Reasoner** advisory contract backed by the deterministic safety rules
- **Nutrient / pH-EC Reasoner** deterministic-first scaffold
- **Shared Reasoner Chain** combining sensor quality, water/irrigation risk, and deterministic actuator safety
- **Integrated Software Pipeline** combining sensor quality, water/irrigation, nutrient/pH-EC, tomato/crop rules, agronomist explanation, actuator safety, and audit output

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + backend info |
| GET | `/v1/models` | List models from `pomona-model.yaml` registry |
| GET | `/v1/models/{id}` | Model metadata |
| GET | `/v1/runtimes` | Local rules, Ollama, and MLX availability |
| POST | `/v1/advisor/explain` | Sensor-aware advisory explanation |
| POST | `/v1/reasoners/sensor-quality` | Sensor packet quality labels with rules-only fallback |
| POST | `/v1/reasoners/tomato-risk` | Tomato risk labels with rules-only fallback |
| POST | `/v1/reasoners/water-irrigation-risk` | Water/irrigation labels via rules, Ollama, or MLX |
| POST | `/v1/reasoners/actuator-command-gate` | Advisory actuator/chemical gate via deterministic rules |
| POST | `/v1/reasoners/safety-triage` | Advisory safety labels and blocked actions |
| POST | `/v1/reasoners/nutrient-ph-ec` | pH/EC risk labels with deterministic fallback |
| POST | `/v1/reasoners/shared-chain` | Quality -> water risk -> actuator safety chain |
| POST | `/v1/pipeline/evaluate` | Full offline guarded software-validation pipeline |
| GET | `/v1/pipeline/audit` | Recent local pipeline summaries without sensor payloads |

`/v1/advisor/explain` accepts optional `guarded_context` from the reasoner chain.
When present, the advisor explains that validated context and must not invent
actions outside its safe checks. All advisor output remains advisory-only.

## Backends (`POMONA_LLM_BACKEND`)

| Value | Description |
|-------|-------------|
| `huggingface` | HF Inference API — set `HF_TOKEN` in `.env` (see [HF_USAGE.md](../../docs/HF_USAGE.md)) |
| `ollama` | Local Ollama on host |

Specialist reasoners can use `rules`, `ollama`, or `mlx` independently of the
advisor backend. See [Local Model Runtimes](../../docs/LOCAL_MODEL_RUNTIMES.md).
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

Shared reasoner chain:

```bash
curl -s http://localhost:8081/v1/reasoners/shared-chain \
  -H 'Content-Type: application/json' \
  -d '{
    "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "greenhouse-a"},
    "sensor": {"air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": 6.2, "ec_ms_cm": 0.18, "substrate_moisture_pct": 24.0, "substrate_temperature_c": 23.0},
    "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"],
    "proposed_command": {"action_type": "start_irrigation"},
    "mode": "hybrid_guarded"
  }'
```

Full software-validation pipeline:

```bash
curl -s http://localhost:8081/v1/pipeline/evaluate \
  -H 'Content-Type: application/json' \
  -d @examples/scenarios/arizona_tomato.json
```

The pipeline is deterministic-first and offline-capable. It returns each
specialist result, an agronomist explanation, the final actuator decision, and
a `pipeline_id`. Audit summaries are appended to the ignored local path
`data/pomona-pipeline-audit.jsonl`. The scenarios under
`examples/scenarios/` are simulated validation cases, not greenhouse results.

Run the complete local simulation and benchmark:

```bash
PORT=8081 ./scripts/run_software_validation.sh
```

The benchmark writes `private/colab/outputs/software_validation_benchmark.json`.
It records machine metadata, worktree state, JSON/schema success, expected
blocked-action and human-review assertions, and local HTTP latency. It is a
simulated validation artifact, not field-ground-truth accuracy or a deployment
performance claim.

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
## Dry-run actuator commands

`POST /v1/actuator-commands/dry-run` evaluates a proposed command through the
deterministic actuator gate and writes a redacted audit summary. The response
always includes `dry_run: true` and `execution_performed: false`; this endpoint
has no hardware driver and cannot execute equipment commands.
