# Pomona Core

Central API and sensor ingest for Pomona.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + MQTT status |
| POST | `/v1/sensors/events` | Ingest a sensor reading (HTTP) |
| GET | `/v1/sensors/events` | List recent readings |
| GET | `/v1/sensors/events/latest` | Most recent reading |

## Run locally (without Docker)

```bash
cd services/core
python3 -m pip install -r requirements.txt
MQTT_HOST=localhost uvicorn app.main:app --reload --port 8080
```

## Run tests

```bash
make test
```

## MQTT topic

Subscribes to: `pomona/+/+/sensor/+/state`

Example publish topic: `pomona/demo-farm/greenhouse-a/sensor/sim-greenhouse-01/state`
