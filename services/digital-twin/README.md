# Pomona Digital Twin

Digital Twin v0 provides a bounded, forecast-only scenario API:

```text
POST /v1/digital-twin/scenarios/simulate
```

It projects temperature, humidity, and moisture trends from a normalized state
and scenario deltas. It never sends MQTT messages, changes actuators, or
replaces live sensor validation.

Run locally with Docker Compose and open the API at `http://localhost:8084`.
