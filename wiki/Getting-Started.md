# Getting Started

**Early MVP** — simulated sensors, REST API, demo advisor. No dashboard yet.

Full install guide (Docker + pip, all OS): [docs/INSTALL.md](https://github.com/Okyanus/pomona/blob/main/docs/INSTALL.md)

## Fastest start (Docker — any OS)

```bash
git clone https://github.com/Okyanus/pomona.git
cd pomona
cp .env.example .env
./scripts/up.sh
./scripts/sim.sh          # new terminal
curl http://localhost:8080/health
```

No `make` required. Works on macOS, Linux, Windows (Docker Desktop).

## Alternative: pip dev

```bash
pip3 install -r requirements-dev.txt
docker compose up -d mqtt
./scripts/run-local.sh
```

## Endpoints

| Service | URL |
|---------|-----|
| Core API | http://localhost:8080 |
| Model router | http://localhost:8081 |
| MQTT | localhost:1883 |

## What works / doesn't

| Works | Not yet |
|-------|---------|
| MQTT + simulator | Web dashboard |
| REST API + in-memory store | Database persistence |
| Stub agronomist advice | Real LLM in Docker |
| | ESP32, automation, safety |

## Next

- [Architecture](Architecture) — how the pieces fit together
- [Model Status](Model-Status) — what's safe to plug in today
- [FAQ](FAQ) — common setup questions
