# Pomona Dashboard

Web UI for monitoring and operating a Pomona deployment.

The first read-only dashboard slice is available at `http://localhost:3000`.

It reads the latest persisted sensor events from `pomona-core` and exposes:

- `GET /health`
- `GET /api/overview`
- `GET /api/pipeline` — unified deterministic-first pipeline for the latest event
- The dashboard page shows each specialist's labels, source, and review state separately.
- `GET /api/audit` — recent pipeline audit summaries without sensor payloads
- `GET /api/risk` — guarded Sensor Quality -> Water/Irrigation -> Actuator Safety result
- `GET /api/safety` — read-only Safety Triage result for the dashboard monitoring action
- `GET /api/services` — core, model-router, and safety-checker health status
- `GET /api/runtimes` — local rules, Ollama, and MLX availability summary
- `GET /api/digital-twin` and `POST /api/digital-twin` — bounded forecast-only preview from the latest event; POST accepts validated scenario deltas and returns a guarded pipeline check
- `GET /api/explanation` — advisory Agronomist note from the guarded sensor context
- `GET /` — live sensor overview page

The dashboard does not execute model output or control actuators. Safety and
approval decisions remain in the model-router and safety-checker services.
Digital Twin scenarios are forecast-only and must be checked against live
sensors before any operational decision.

To run the local Core, Model Router, and Dashboard validation path without
Docker, use `./scripts/run_local_validation.sh`. It uses temporary SQLite and
process files and removes them when the check finishes.
