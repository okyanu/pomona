# Local Validation

Pomona can be validated without Docker or remote model publication.

## Commands

Run the service contract tests:

```bash
make test-local
```

Run the isolated four-service smoke test:

```bash
make local-validation
```

Run both checks before a human-reviewed commit:

```bash
make local-check
```

Run the complete pre-hardware scenario gate:

```bash
make pre-hardware-validation
```

This adds explicit simulated cases for missing data, stale telemetry, impossible
sensor values, nutrient risk, and unsafe chemical commands. It is a dry-run
contract check only: no actuator command is sent to hardware.

## What The Smoke Test Starts

The runner starts Core, Model Router, Safety Checker, and Dashboard on temporary
localhost ports. It uses temporary SQLite, audit, and log files and removes
them when it exits.

It verifies:

- sensor event ingestion through Core;
- SQLite event recovery after restarting Core;
- high-risk tomato output with blocked irrigation, fertigation, and actuator actions;
- routine hydroponic lettuce output with no blocked actions or human review;
- independent deterministic Safety Checker rejection;
- Dashboard pipeline, audit, service-status, runtime-status, and HTML views;
- audit summaries do not expose sensor payloads.

The routine hydroponic scenario uses `__CURRENT_TIMESTAMP__` so the fixture
does not become stale as calendar time advances. Explicit stale-data cases use
fixed timestamps and remain time-sensitive by design.

## Scope And Limits

This is a software and contract validation checkpoint. It does not prove field
agronomic accuracy, hardware reliability, sensor calibration, production
latency, or safe autonomous operation. The LLM remains advisory and the
deterministic Safety Checker remains the final authority.

With Docker running, validate the ESP32-shaped MQTT path:

```bash
make hardware-simulation-validation
```

This publishes two tagged observation packets, verifies Core persistence and
the dashboard guarded result, then checks the dry-run actuator endpoint. It
does not publish an actuator command and does not execute hardware.

Validate the running Docker database backup and recovery path:

```bash
make backup-recovery-validation
```

This backs up Core's live SQLite database, restarts Core, verifies the latest
event, and restores the backup into a temporary database for verification. It
does not replace the live database during restore.

The benchmark report from the software-validation scenarios is written to the
ignored path `private/colab/outputs/software_validation_benchmark.json`.

## Docker

Check the Compose file without starting containers:

```bash
make docker-config
```

The normal Docker path remains:

```bash
./scripts/up.sh
```

Docker Desktop must be running for that path. The no-Docker runner is useful for
local development when Docker is unavailable; it does not replace the Docker
deployment smoke test.

## Local SQLite Recovery

Create and restore a consistent SQLite backup without Docker:

```bash
./scripts/backup_sqlite.sh data/pomona.db backups/pomona-local.db
./scripts/restore_sqlite.sh backups/pomona-local.db data/pomona-restored.db
```

The scripts use SQLite's online backup API and do not delete the source database.
