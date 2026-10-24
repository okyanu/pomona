# Automation Engine

Runs YAML-based automation rules and produces suggestions from guarded risk
labels. **Suggestions only — no direct actuator control.** Approving a
suggestion records a decision; there is no execution path to any hardware.

```text
POST /v1/automation/evaluate
GET  /v1/automation/suggestions
POST /v1/automation/suggestions/{id}/approve
POST /v1/automation/suggestions/{id}/reject
```

## Rules

Defined in [app/rules.yaml](app/rules.yaml). Each rule maps one or more
risk labels to a human-executable suggestion:

- `high_ph` / `low_ph` -> check the water/dosing system
- `high_ec` / `low_ec` -> review nutrient dosing
- `fungal_pressure` -> consider ventilation, inspect canopy
- `water_level_risk` -> check the irrigation system

`load_rules` rejects any rule whose `action` matches Pomona's forbidden
actuator/chemical vocabulary (`direct_pesticide_dosage`,
`autonomous_fertigation_change`, `direct_actuator_control`,
`definitive_disease_diagnosis`, `unsafe_chemical_recommendation`) at
startup — a rules-file edit alone cannot make this service unsafe.

## Local suggestion history

Docker Compose stores suggestions in SQLite on the `automation_data` named
volume. Rebuilding/restarting containers preserves it; deleting the volume
(for example with `docker compose down -v`) removes it.

For host/pip use, set `AUTOMATION_DB_PATH=data/automation.db`. When unset,
storage remains ephemeral for demos/serverless deployments. A serverless
temporary filesystem is not durable storage.

`MAX_SUGGESTIONS` (default 200) bounds completed decision history. Pending
suggestions are never evicted by this limit and can grow until reviewed.
An optional `event_id` reuses the same retained event/rule/action suggestion
across retries, including after a restart with persistent storage. Once a
completed row is pruned, its retry key is no longer retained. This is not an
unlimited or tamper-proof audit log. Back up the SQLite file while the service
is stopped, or use SQLite's online backup API while running.

Approve/reject accept an optional JSON body: `{"reviewer":"Local operator"}`.
This label is **self-reported, not authenticated**. Creation time, decision
time, context, and the first decision are retained; later decisions cannot
overwrite it. No approval ever executes hardware. Keep the unauthenticated
service on a trusted local network.

## Alerts (wait and recover)

Suggestions are made when a person presses *Evaluate*. Alerts follow every reading instead:
the dashboard sends each new reading's risk labels to `POST /v1/automation/alerts/observe`
(`farm_id`, `zone_id`, optional `device_id`, `sample_time` with a timezone, `risk_labels`).

| State | Meaning |
|---|---|
| waiting (`pending`) | A rule's label appeared; it must last `raise_after_seconds` before an alert is raised. If it disappears first, nothing is recorded. |
| `active` | Raised. One `raised` event per incident. |
| `recovering` | The label is gone; it must stay away `clear_after_seconds`. If it comes back, the same incident continues. |
| (cleared) | One `recovered` event; the alert is closed. |

Defaults are 600 s to raise and 900 s to clear (`ALERT_RAISE_AFTER_SECONDS`,
`ALERT_CLEAR_AFTER_SECONDS`); a rule in `rules.yaml` can set its own `raise_after_seconds` /
`clear_after_seconds` (humidity uses 30 / 30 minutes, because it swings with every vent and
irrigation pulse). Time is the sensor's sample time, so retries, replays and late packets
never move an alert. `GET /v1/automation/alerts?farm_id=&zone_id=` lists open alerts and the
last raised / recovered events. Alerts are advisory: they never create suggestions or touch
hardware.

## Outcome confirmation (after an approval)

Approval records a decision; it does **not** mean the suggested check or change
happened. After an approval, `observe` also judges each new reading (sample time,
same farm/zone/device as the suggestion) and the suggestion carries
`outcome_status`, `outcome_deadline` and `outcome_evidence`:

| `outcome_status` | Meaning |
|---|---|
| `awaiting` | Watching until `outcome_deadline` (approval + `OUTCOME_RESPONSE_WINDOW_SECONDS`, default 7200; a rule may set `response_window_seconds`, 1 s to 7 days). |
| `confirmed` | `OUTCOME_CONFIRM_READINGS` (default 3) consecutive trusted readings after the approval had none of the rule's labels. This is all it means. |
| `not_recovered` | The window ended with at least that many trusted readings, but no clean run. |
| `unconfirmed` | The window ended with too few trusted readings to tell (including no readings at all). |

`POST /v1/automation/alerts/observe` accepts optional `data_quality_labels`; a reading
with any of them is untrusted and counted only as `untrusted_readings`. Readings sampled
before the approval, repeated or older samples, and samples more than 60 s ahead of the
service clock are ignored. Rejected, expired and pre-existing suggestions have no outcome
(`null`). Advice cards expose the same data under `outcome`. There is no actuator path.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8085
```

Or via the full stack: `./scripts/up.sh` (port `8085`).
