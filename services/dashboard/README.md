# Pomona Dashboard

## Local zone monitoring

Enter both **Farm ID** and **Zone ID**, then choose **Open zone**. Selection is
stored in the page URL and reloads the page, preventing in-flight results from
the previous zone from repainting the new view. Without a selection the browser
does not request recommendations. IDs must match ingested telemetry exactly.

The selected scope follows readings, risk, pipeline, explanations, forecast
previews, suggestion evaluation, history, and device-health requests. Global
service/runtime health remains global. Legacy audit summaries have no zone
identity and are hidden in scoped views. Suggestions without matching scope
metadata are also hidden; filtering is **not authentication**.

Device status reports last receipt, inferred recent/silent availability,
stale sample status, and sender-reported quality. It does not certify sensor
calibration or connectivity. Modular observations remain monitoring-only.

Choose full packets or modular observations for history. Pages contain up to
100 records; increase offset by 100 for older pages. The CSV link uses the same
scope, type, and offset. Live ingestion/retention can move offset pages; pause
ingestion when a consistent multi-page export is required. Existing sparklines
show the latest full packets, not the selected historical offset.

Core outages visibly mark recommendations unavailable and block review clicks.
Refresh cycles do not overlap, and selecting a zone reloads all panels. No
approval or forecast preview executes hardware. Public deployments are unchanged
until explicitly published.

Web UI for monitoring and operating a Pomona deployment.

The dashboard is available at `http://localhost:3000`.

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
- `GET /api/automation` — suggestion history
- `POST /api/automation/evaluate` — create suggestions from the latest guarded pipeline
- `POST /api/automation/suggestions/{id}/approve` or `/reject` — record a decision, never run hardware
- `GET /` — live sensor overview page

The dashboard does not execute model output or control actuators. Deterministic
safety checks remain authoritative; manual suggestion decisions are recorded
by the automation engine. Reviewer labels are optional and unverified. Failed
requests are shown explicitly and action buttons are disabled during requests.
Digital Twin scenarios are forecast-only and must be checked against live
sensors before any operational decision.

To run the local Core, Model Router, and Dashboard validation path without
Docker, use `./scripts/run_local_validation.sh`. It uses temporary SQLite and
process files and removes them when the check finishes.

## Rendering regression tests

Dashboard tests require Node.js 22 on PATH in addition to the Python test
dependencies. Run `make test-local` from the repository root. CI installs
Node for the dashboard test job; Node is not a production dependency.

The regression harness executes the served JavaScript with mocked API data
containing HTML and attribute-injection payloads. It checks that API/model
values are escaped at HTML sinks while tables, badges, and approval links
remain intact. Plain `textContent` values are not HTML-escaped.
This does not add authentication or change actuator safety rules.
