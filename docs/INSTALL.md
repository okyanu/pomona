# Install & run (macOS, Linux, Windows)

Pomona runs in Docker, so it should run the same way on any OS with Docker. It is developed on macOS and CI runs on Linux; Windows is not tested. Pip is optional for local development.

---

## What you need

| Tool | Docker path | Pip dev path |
|------|-------------|--------------|
| **Docker Desktop** | Required | MQTT only (or full stack in Docker) |
| **Python 3.11** | Optional (simulator) | Required |
| **Git** | Clone repo | Clone repo |
| **Make** | Optional | Optional |

**No OS-specific config files.** One `.env` for everyone (copy from `.env.example`).

---

## Path A — Docker (recommended)

Developed on **macOS**, CI on **Linux**; **Windows** (Docker Desktop + WSL2) should work but is not tested.

```bash
git clone https://github.com/okyanu/pomona.git
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

**Container lockdown.** Every Pomona service runs as an unprivileged user (uid 10001;
Mosquitto as 1883) with a read-only filesystem, all Linux capabilities dropped, no
privilege escalation, and CPU/memory limits. Only the named volumes are writable
(`core_data`, `router_data`, `automation_data`). If you upgrade from an older version and
start with `docker compose up` instead of `./scripts/up.sh`, give old root-owned volumes to
the new user once:

```bash
docker compose run --rm --no-deps --user 0 --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --entrypoint chown core -R 10001:10001 /app/data
```

`./scripts/up.sh` does this automatically for core, model-router and automation-engine.

**After a crash or a power cut** every service restarts by itself (`restart: unless-stopped`; `docker compose stop` /
`./scripts/down.sh` still stops them). Each Pomona API has a health check on its own `/health`; `docker compose ps`
shows `healthy` once it is up, and the services that need Core or the model-router wait for them to be healthy.
Docker itself must start at boot (in Docker Desktop: Settings, General, start when you sign in).

### Windows notes

- Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) with WSL2
- Use **Git Bash**, **WSL**, or **PowerShell** for commands
- `make` is optional — use `./scripts/up.sh` or `docker compose` directly

---

## Path B — Pip local dev (hybrid)

Run **APIs on your machine**, **MQTT in Docker**. Good for debugging Python.

```bash
cp .env.example .env
pip3 install -r requirements-dev.txt -c constraints-dev.txt

# Start only MQTT broker in Docker (up.sh makes sure .env has a MQTT_PASSWORD first)
./scripts/up.sh mqtt

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
make bootstrap    # once: one Python 3.11 venv per service group, with the pinned versions
make test         # every suite (the same as make test-local)
# or one suite:
cd services/core && PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
```

MQTT tests may show `mqtt_connected: false` — that's OK without a broker.

### MQTT login

The Docker broker requires a login (no anonymous access). `./scripts/setup.sh` or `./scripts/up.sh` writes a
random `MQTT_PASSWORD` into `.env` when it is blank and never prints it; `MQTT_USERNAME` defaults to `pomona`.
The broker builds its password file inside the container at start, so no password file exists on the host.
Compose refuses to start the broker while `MQTT_PASSWORD` is empty. Clients (Core, `./scripts/sim.sh`,
`make fake-greenhouse`) read the same two values from `.env`; for your own client use any MQTT library with
that user name and password. Port 1883 is plain MQTT without TLS: local network only, never port-forward it.
Docker publishes 1883, 8080 and 3000 on `127.0.0.1` (this computer only) by default; to reach the broker and Core from
a real device on your network, set `POMONA_BIND_ADDRESS=0.0.0.0` in `.env` (trusted network only, set `API_KEY`).

---

## Backup and restore (Docker)

The data lives in three Docker volumes: Core's database (`core_data`), the automation engine's database
(`automation_data`: suggestions, alerts) and the model-router's audit log (`router_data`). One command backs up all of it
into a new folder `backups/<timestamp>/` (git-ignored), while the stack is running:

```bash
./scripts/backup.sh          # or: make backup
```

Each database is copied with SQLite's online backup API inside its container, so the copy is consistent even while Core
is writing (do not copy the `.db` file by hand: it can be torn, and Core's WAL file holds recent writes). The copy goes
through a temporary file in the same volume, not `/tmp`, so the free space needed is about the size of the database.
The folder holds `core.db`, `automation.db`, `audit.jsonl` (the audit log, if one exists yet) and `audit.jsonl.1` (its rotated older part, if it exists).

To restore (this **replaces** the live data: run a backup first if you may want it):

```bash
./scripts/restore.sh backups/20260101-020000     # or: make restore BACKUP=backups/20260101-020000
```

It checks every database in the folder, then for each service stops it, writes the backup into its volume, deletes the old
`-wal` / `-shm` files and starts it again. The other services keep running. A single file also works
(`./scripts/restore.sh some/core.db` restores Core only). For a database outside Docker (pip dev path) use
`make backup-local DB_PATH=... BACKUP_PATH=...` and `make restore-local`.

A nightly backup at 02:00 (use the full path of your clone, and the account that can run `docker`), keeping 14 days:

```cron
0 2 * * * cd /path/to/pomona && ./scripts/backup.sh >> backups/backup.log 2>&1 && find backups -mindepth 1 -maxdepth 1 -type d -mtime +14 -exec rm -rf {} +
```

Copy `backups/` off the machine too (another disk or a cloud drive): a backup on the same disk does not survive the disk.

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
| `MQTT_PASSWORD` | Normally leave it: setup fills in a random one. To change it, edit `.env` and restart the broker |
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
| Simulator no data in core | MQTT must be up; simulator uses `localhost:1883` and the `MQTT_USERNAME` / `MQTT_PASSWORD` from `.env` |
| `MQTT_PASSWORD is not set` from Compose | Run `./scripts/setup.sh` (or `./scripts/up.sh`), or set `MQTT_PASSWORD` in `.env` |
| `Connection Refused: not authorised` from a client | It is not using the broker's `MQTT_USERNAME` / `MQTT_PASSWORD` |
| `make: command not found` | Use `./scripts/up.sh` instead |
| Linux Ollama from container | `host.docker.internal` fixed via `extra_hosts` in compose |
| `Permission denied` / `readonly database` after upgrading | Old root-owned volume: run `./scripts/up.sh`, or the `chown` command under *Container lockdown* |
| Model router killed (exit 137) with the Hugging Face backend | Raise `MODEL_ROUTER_MEM_LIMIT` in `.env` (default 2g) |

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
