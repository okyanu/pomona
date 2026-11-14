# Pomona Core

Sensor events are persisted in SQLite. Set `DB_PATH` to choose the database
location; Docker Compose defaults to `/app/data/pomona.db` on the persistent
`core_data` volume.

## Persistence and backups

Normal container restarts preserve events:

```bash
docker compose down
docker compose up -d
```

Create a backup before deleting Docker volumes (the stack must be running; it uses SQLite's online backup API, so
the copy is consistent while Core writes):

```bash
./scripts/backup.sh
```

It writes a timestamped folder, `backups/YYYYMMDD-HHMMSS/`, with `core.db` (Core), `automation.db` (the automation
engine) and `audit.jsonl` (the model-router audit log, when it exists). Restore a folder (it replaces the live
data, stops and restarts each service itself, and checks every file first):

```bash
./scripts/restore.sh backups/YYYYMMDD-HHMMSS
```

`scripts/backup_core_db.sh` and `restore_core_db.sh` still work and call the two scripts above; `restore.sh` also takes
a single old Core `.db` file. The database runs in write-ahead-log mode (`pomona.db-wal` and `-shm` files beside it
in the volume), so copy it with these scripts or SQLite's backup API, never with a plain file copy.

Without Docker, use the SQLite backup API directly:

```bash
./scripts/backup_sqlite.sh data/pomona.db backups/pomona-local.db
./scripts/restore_sqlite.sh backups/pomona-local.db data/pomona-restored.db
```

Do not use `docker compose down -v` unless the database has been backed up;
that command deletes the persistent `core_data` volume.

Central API and sensor ingest for Pomona.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + MQTT status |
| POST | `/v1/sensors/events` | Ingest a sensor reading (HTTP) |
| GET | `/v1/sensors/events` | List recent readings |
| GET | `/v1/sensors/events/latest` | Most recent reading |

## Sample times

`timestamp` is required on every full packet; Core never substitutes its receipt time. Sample
times before `MIN_SAMPLE_TIME` (default `2020-01-01T00:00:00Z`) are rejected for packets,
observations and corrected observations (a device clock that was never set), and so are times more
than `MAX_FUTURE_SAMPLE_S` (default 300 s, 0 disables) ahead of Core's clock (local time labelled `Z`).
A sample time the check accepts counts as current: a clock a few minutes fast shows in the latest reading and the
device list. With the check off (0), a sample time more than 60 s ahead is stored but never current.
Stored rows are not re-checked. Everything is stored in UTC; `FARM_TIMEZONE` (an IANA name, default
`UTC`) is display only and appears in `GET /health` under `time`, with the next clock change.

## Outcome feed

When `MODEL_ROUTER_URL` and `AUTOMATION_ENGINE_URL` are both set (Docker Compose sets them),
Core forwards each new full packet (not duplicates, retained MQTT messages, future-clock or
stale-sequence readings) to model-router for a `rules_only` evaluation (`actor: core_feed`) and
then gives the resulting labels to automation-engine's alert monitor, so alerts and approval
outcomes move without the dashboard open. A background worker with a bounded queue
(`OUTCOME_FEED_QUEUE_SIZE`) keeps ingest independent: failures are logged, a full queue drops
readings and counts them in `/health` (`outcome_feed_dropped`). Each forwarded reading writes
one pipeline audit line in model-router. The feed is advisory only, with no actuator path, and
is disabled when the URLs are unset.

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
