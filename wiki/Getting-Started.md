# Getting Started

**Early MVP, tested in software only** — simulated sensors, SQLite-backed REST API, deterministic rules, a monitoring dashboard and suggestion-only automation. No hardware has been bench-tested and nothing is actuated.

Full install guide (Docker + pip, all OS): [docs/INSTALL.md](https://github.com/okyanu/pomona/blob/main/docs/INSTALL.md)

## Fastest start (Docker)

```bash
git clone https://github.com/okyanu/pomona.git
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
./scripts/up.sh mqtt   # first run creates .env with a random MQTT_PASSWORD; the broker requires a login
./scripts/run-local.sh
```

## Endpoints

| Service | URL |
|---------|-----|
| Core API | http://localhost:8080 |
| Model router | http://localhost:8081 |
| MQTT | localhost:1883 |

## What works / doesn't

| Works locally | Not yet |
|---------------|---------|
| MQTT (login required) + simulator and fake greenhouse | Bench-tested ESP32 hardware (firmware compiles, not run on a board) |
| REST API + SQLite persistence | Any field data or field validation |
| Monitoring dashboard (http://localhost:3000) | Live LLM advisor by default (stub unless you enable Ollama) |
| Deterministic sensor checks, crop rules and safety checker | Actuator execution (by design: suggestions only) |
| Suggestion-only automation with manual approve/reject | Production hardening |

## Next

- [Architecture](Architecture) — how the pieces fit together
- [Model Status](Model-Status) — what's safe to plug in today
- [FAQ](FAQ) — common setup questions
