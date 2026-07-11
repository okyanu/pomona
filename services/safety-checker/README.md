# Safety Checker

Filters model and automation output before it reaches users or actuators.

**Implemented baseline:**

- Deterministic tomato greenhouse risk rules in `app/tomato_rules.py`
- FastAPI service endpoint at `POST /v1/tomato-risk/check`
- Golden eval scorer in `scripts/datasets/evaluate_tomato_risk_rules.py`
- Unit tests in `tests/test_tomato_rules.py`
- API tests in `tests/test_safety_checker_api.py`

**Current API behavior:**

- Accept normalized Pomona tomato greenhouse input under an `input` key
- Return deterministic `risk_labels`
- Return `missing_data`
- Return `safe_next_checks`
- Return blocked unsafe action categories
- Set `human_review_required` when risks or blocked actions are present

**Current status:** Rule baseline and service API implemented. Model-output filtering and rewrite behavior are still planned.

## API

```bash
curl -s http://localhost:8082/v1/tomato-risk/check \
  -H 'Content-Type: application/json' \
  -d '{
    "input": {
      "system_type": "controlled_greenhouse",
      "crop": "tomato",
      "growth_stage": "fruiting",
      "air_temperature_c": 24.0,
      "humidity_pct": 90.0,
      "ph": 6.2,
      "ec_ms_cm": 2.4,
      "substrate_temperature_c": 23.0,
      "substrate_moisture_pct": 45.0,
      "actuator_states": {},
      "symptoms": []
    }
  }'
```

## Local checks

```bash
python3 scripts/datasets/validate_pomona_dataset.py
python3 scripts/datasets/evaluate_tomato_risk_rules.py
services/core/.venv/bin/python -m pytest services/safety-checker/tests -q
```

The rule baseline is intentionally small. It is not a full agronomist model; it provides a deterministic safety floor for pH, EC, temperature, humidity, missing data, sensor anomalies, water risk, and actuator conflicts.
