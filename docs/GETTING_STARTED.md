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

## The MQTT broker needs a login

The broker does not accept anonymous clients. `./scripts/up.sh` (and `./scripts/setup.sh`) put a random
`MQTT_PASSWORD` into your `.env` the first time; the user name is `MQTT_USERNAME` (default `pomona`). Core and
`./scripts/sim.sh` read them from `.env`; any other client you point at the broker (an ESP32, `mosquitto_pub`)
needs the same pair. The password is never printed. If you start Compose yourself and `MQTT_PASSWORD` is blank,
it stops and tells you to run `./scripts/setup.sh`.

Port 1883 is plain MQTT (no TLS): keep it on your local network and never port-forward it. See
[SECURITY.md](https://github.com/okyanu/pomona/blob/main/SECURITY.md).

## Alternative: pip dev

```bash
pip3 install -r requirements-dev.txt
./scripts/setup.sh          # once: makes .env with a random MQTT_PASSWORD
./scripts/up.sh mqtt        # the broker only
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

## Contribute

Open source under Apache-2.0. See [CONTRIBUTING.md](https://github.com/okyanu/pomona/blob/main/CONTRIBUTING.md).

## Related repos

| Repo | Purpose |
|------|---------|
| `pomona` (this) | Run platform |
| `pomona-agronomist-llm` | Train LLM (optional) |
| [HF model](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) | Weights (optional) |

Personal notes: `private/` (gitignored).
