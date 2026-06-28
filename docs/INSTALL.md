# Install & run (macOS, Linux, Windows)

Pomona runs the **same way on every OS** if you use Docker. Pip is optional for local development.

---

## What you need

| Tool | Docker path | Pip dev path |
|------|-------------|--------------|
| **Docker Desktop** | Required | MQTT only (or full stack in Docker) |
| **Python 3.9+** | Optional (simulator) | Required |
| **Git** | Clone repo | Clone repo |
| **Make** | Optional | Optional |

**No OS-specific config files.** One `.env` for everyone (copy from `.env.example`).

---

## Path A — Docker (recommended)

Works on **macOS, Linux, Windows** (Docker Desktop + WSL2 on Windows).

```bash
git clone https://github.com/Okyanus/pomona.git
cd pomona
cp .env.example .env
./scripts/setup.sh          # optional: installs pip deps + checks tools
./scripts/up.sh             # starts MQTT + core + model-router
./scripts/sim.sh            # new terminal — fake sensor data
curl http://localhost:8080/health
curl http://localhost:8081/health
```

**Without bash scripts** (same thing):

```bash
cp .env.example .env
docker compose up -d --build
python3 examples/simulators/greenhouse_tomato.py
```

Stop:

```bash
./scripts/down.sh
# or: docker compose down
```

### Windows notes

- Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2
- Use **Git Bash**, **WSL**, or **PowerShell** for commands
- `make` is optional — use `./scripts/up.sh` or `docker compose` directly

---

## Path B — Pip local dev (hybrid)

Run **APIs on your machine**, **MQTT in Docker**. Good for debugging Python.

```bash
cp .env.example .env
pip3 install -r requirements-dev.txt

# Start only MQTT broker in Docker
docker compose up -d mqtt

# Run core + model-router on host (foreground)
./scripts/run-local.sh
```

New terminal:

```bash
./scripts/sim.sh
curl http://localhost:8080/health
```

---

## Path C — Tests only (no Docker)

```bash
pip3 install -r requirements-dev.txt
make test
# or:
cd services/core && PYTHONPATH=. pytest tests/ -v
cd services/model-router && PYTHONPATH=. pytest tests/ -v
```

MQTT tests may show `mqtt_connected: false` — that's OK without a broker.

---

## Configuration

| File | Purpose |
|------|---------|
| `.env.example` | Template — copy to `.env` |
| `.env` | Your local settings (**never commit**) |
| `docker-compose.yml` | Service definitions (same all OS) |

You rarely need to edit `.env` for basic use. Defaults work out of the box.

### Optional `.env` changes

| Variable | When to change |
|----------|----------------|
| `POMONA_LLM_BACKEND=ollama` | Using local Ollama |
| `HF_TOKEN` | Gated HF models (advanced) |
| `SIM_INTERVAL_SEC` | Faster/slower simulator |

---

## Endpoints (after `./scripts/up.sh`)

| Service | URL |
|---------|-----|
| Core API | http://localhost:8080 |
| Health | http://localhost:8080/health |
| Sensor events | http://localhost:8080/v1/sensors/events |
| Model router | http://localhost:8081 |
| Advisor (stub) | POST http://localhost:8081/v1/advisor/explain |
| MQTT | `localhost:1883` |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `Cannot connect to Docker daemon` | Start Docker Desktop |
| `Connection refused` on :8080 | Wait 10s after `up.sh`, check `docker compose ps` |
| Simulator no data in core | MQTT must be up; simulator uses `localhost:1883` |
| `make: command not found` | Use `./scripts/up.sh` instead |
| Linux Ollama from container | `host.docker.internal` fixed via `extra_hosts` in compose |

Run diagnostics:

```bash
./scripts/check-prerequisites.sh
```

---

## What cloners should expect

**Works:** simulated greenhouse data → REST API → demo advisor text  
**Not yet:** dashboard UI, database persistence, real LLM in Docker, ESP32

See [GETTING_STARTED.md](./GETTING_STARTED.md).

---

## Related repos

| Repo | Needed to run platform? |
|------|-------------------------|
| `pomona` (this) | Yes |
| `pomona-agronomist-llm` | No — only for retraining |
| Hugging Face model | No — stub mode works offline |
