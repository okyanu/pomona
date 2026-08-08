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

Sensor events are observation data only. They cannot authorize a pump, valve,
fertigation, climate, pesticide, or diagnostic command. Proposed actions must
go through the guarded pipeline and deterministic Safety Checker. Hardware
integration must begin in dry-run mode with commands logged but not executed.
