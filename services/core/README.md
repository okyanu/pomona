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
