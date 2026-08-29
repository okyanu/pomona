# Pomona Digital Twin

Digital Twin v0 provides a bounded, forecast-only scenario API:

```text
POST /v1/digital-twin/scenarios/simulate
```

It projects temperature, humidity, and moisture trends from a normalized state
and allowlisted, bounded scenario deltas. Unknown scenario fields and invalid
sensor ranges are rejected. Responses include the validated baseline, scenario,
forecast model identifier, generation time, and horizon so previews are
reproducible and auditable.

This service never sends MQTT messages, changes actuators, or replaces live
sensor validation. Irrigation duration and ventilation are simulation inputs,
not commands.

Run locally with Docker Compose and open the API at `http://localhost:8084`.
