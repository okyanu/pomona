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

## Suggestions are in-memory (v0.1)

Suggestions and their approval status live only in process memory, matching
the platform's other stateless specialist services. Restarting the service
clears them.

## Run locally

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
PYTHONPATH=. .venv/bin/uvicorn app.main:app --port 8085
```

Or via the full stack: `./scripts/up.sh` (port `8085`).
