# Simulators

MQTT simulators for local development without hardware.

## Greenhouse tomato simulator

Publishes pH, EC, humidity, temperature, and soil moisture for a demo tomato greenhouse.

### Prerequisites

1. Start the stack: `make up` (from repo root)
2. Install deps: `make install-sim`

### Run

```bash
make sim
```

Or manually:

```bash
MQTT_HOST=localhost python3 examples/simulators/greenhouse_tomato.py
```

Environment variables (see `.env.example`):

| Variable | Default |
|----------|---------|
| `MQTT_HOST` | `localhost` |
| `MQTT_PORT` | `1883` |
| `SIM_FARM_ID` | `demo-farm` |
| `SIM_ZONE_ID` | `greenhouse-a` |
| `SIM_DEVICE_ID` | `sim-greenhouse-01` |
| `SIM_INTERVAL_SEC` | `5` |

### Verify

```bash
make health
make events
docker compose logs -f core
```
