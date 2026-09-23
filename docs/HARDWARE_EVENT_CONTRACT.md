# Hardware Sensor Event Contract

This is the pre-hardware contract for ESP32 and other sensor devices. It is
local documentation only; no device connection or actuator control is enabled
by this contract.

## Transport

MQTT topic:

```text
pomona/{farm_id}/{zone_id}/sensor/{device_id}/state
```

The MQTT payload must be one JSON object matching
`schemas/sensor-event.schema.json`. The same object can be submitted to
`POST /v1/sensors/events` for HTTP testing.

## Canonical payload

```json
{
  "device_id": "esp32-greenhouse-01",
  "farm_id": "demo-farm",
  "zone_id": "greenhouse-a",
  "crop": "tomato",
  "growth_stage": "flowering",
  "system_type": "greenhouse_substrate",
  "air_temperature_c": 31.2,
  "humidity_pct": 88.0,
  "ec_ms_cm": 3.4,
  "ph": 7.5,
  "soil_moisture_pct": 42.0,
  "timestamp": "2026-07-21T10:00:00Z",
  "source": "esp32"
}
```

## Boundary rules

| Field | Unit | Accepted range |
|---|---|---:|
| `air_temperature_c` | Celsius | -40 to 80 |
| `humidity_pct` | percent | 0 to 100 |
| `ec_ms_cm` | mS/cm | 0 to 20 |
| `ph` | pH scale | 0 to 14 |
| `soil_moisture_pct` | percent | 0 to 100 |

Supported deployment profiles are represented by `system_type`, for example
`soil`, `greenhouse_substrate`, `hydroponic`, and `aquaponic`. The transport
contract is shared, but each profile needs its own expected fields and rules.

Core rejects malformed packets and values outside these transport ranges. A
value inside the transport range can still be agronomically suspicious; the
Sensor Quality reasoner remains responsible for stale, conflicting, drift, or
crop-specific checks.

## Hardware safety boundary

### Modular observation API (monitoring only)

Temperature-only nodes can use `POST /v1/sensors/observations`, or MQTT topic
`pomona/{farm_id}/{zone_id}/sensor/{device_id}/observation`. The existing
full-packet `/state` topic and `/v1/sensors/events` requirements are unchanged.

```json
{
  "device_id": "temperature-node-01",
  "farm_id": "demo-farm",
  "zone_id": "greenhouse-a",
  "sensor_id": "air-temperature-01",
  "measurement": "air_temperature_c",
  "unit": "C",
  "value": 24.5,
  "quality": "valid",
  "timestamp": "2026-09-05T10:00:00Z",
  "sequence": 1,
  "boot_id": "boot-01",
  "firmware": "prototype-0.1"
}
```

Supported measurements are air/water temperature (`C`), humidity and soil
moisture (`%`), pH (`pH`), EC (`mS/cm`), and low-level contact (`boolean`, 0/1).
Contact polarity remains a device-specific convention, not an irrigation rule.
Quality may be `valid`, `missing`, `suspect`, `conflicting`, or `disconnected`.
Missing values must not be marked valid. Optional `calibration_timestamp` and
sample timestamps require timezones. Quality/calibration are sender-reported,
not evidence of validation; sequence/boot metadata are stored, not deduplicated.
Core overwrites `received_at` with its own receipt time.

These records are **not fused into reasoner inputs**. No synthetic pH/EC values
are filled in. A validated state-assembly policy is a later task.

### Scoped history and device visibility

- `GET /v1/sensors/events` and `/events/latest` accept `farm_id` and `zone_id`.
- `GET /v1/sensors/observations` accepts the same filters, `limit`, and `offset`.
- `GET /v1/sensors/devices` reports last receipt, sample age, and `recent` or
  `silent` (default threshold 120 seconds). This is inferred availability, not
  proof of connectivity. Old migrated records do not invent a last-seen time.
- `GET /v1/sensors/export.csv?kind=observations&farm_id=demo-farm&zone_id=greenhouse-a`
  exports a bounded CSV; `kind=events` exports full packets. Maximum page size
  is 10,000; offset pages newest records first, chronological within a page.
  Pause ingestion for a consistent multi-page export: offsets can shift during
  writes or retention cleanup. Spreadsheet formula-like strings are escaped.

Retention defaults to seven days by server receipt time and at most 100,000
records per farm/zone **per record type**, whichever limit is reached first.
Cleanup runs on ingest, not on a timer. Configure `RETENTION_DAYS`, `MAX_EVENTS`,
and `DEVICE_TIMEOUT_SECONDS`. Legacy rows without receipt times remain subject
to the count limit; device last-seen metadata is retained separately. This is
not a global disk quota: many zones/devices can increase storage usage.
Back up SQLite before upgrading; the schema migration adds scope columns and
observation/presence tables. No authentication change accompanies these APIs;
keep the MVP on a trusted local network.

The dashboard accepts a farm/zone selection and displays device health plus
100-record history pages, with CSV download for the same selection and offset.
Full-packet trend sparklines remain separate from the modular observation table;
modular observations are not assembled into recommendations.

### Command boundary

Sensor events are observation data only. They cannot authorize a pump, valve,
fertigation, climate, pesticide, or diagnostic command. Proposed actions must
go through the guarded pipeline and deterministic Safety Checker. Hardware
integration must begin in dry-run mode with commands logged but not executed.
