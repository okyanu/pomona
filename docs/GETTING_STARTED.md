# Getting started

**Early MVP** — simulated sensors, REST API, demo advisor. No dashboard yet.

Full install guide (Docker + pip, all OS): **[INSTALL.md](./INSTALL.md)**

## Fastest start (Docker — any OS)

```bash
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

## AI assistants

Read [AGENTS.md](../AGENTS.md) (Cursor, Claude, Codex).

## Contribute

Open source under Apache-2.0. See [CONTRIBUTING.md](../CONTRIBUTING.md).

## Related repos

| Repo | Purpose |
|------|---------|
| `pomona` (this) | Run platform |
| `pomona-agronomist-llm` | Train LLM (optional) |
| [HF model](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) | Weights (optional) |

Personal notes: `private/` (gitignored).
