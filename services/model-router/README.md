# Pomona Model Router

Routes tasks to registered Pomona models. Currently implements the **Agronomist Advisor** backed by [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4).

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + backend info |
| GET | `/v1/models` | List models from `pomona-model.yaml` registry |
| GET | `/v1/models/{id}` | Model metadata |
| POST | `/v1/advisor/explain` | Sensor-aware advisory explanation |

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

## Run locally

```bash
cd services/model-router
pip install -r requirements.txt
MODELS_DIR=../../models POMONA_LLM_BACKEND=stub uvicorn app.main:app --port 8081
```
