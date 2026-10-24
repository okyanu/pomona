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

Create a local backup before deleting Docker volumes:

```bash
./scripts/backup_core_db.sh
```

Restore a backup after stopping the core service:

```bash
./scripts/restore_core_db.sh backups/pomona-YYYYMMDD-HHMMSS.db
```

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
observations and corrected observations (a device clock that was never set). Stored rows are
not re-checked.

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
