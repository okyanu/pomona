# Pomona Water Irrigation Risk v0.1

Dataset scaffold for a crop-agnostic water and irrigation risk reasoner.

Task:

```text
farm context + irrigation sensor JSON
  -> irrigation_risk_labels + missing_fields + suspect_fields + safe_next_checks
```

This model is advisory only. It should never directly control pumps, valves, or schedules. Deterministic safety-checker rules and human approval remain the final authority.

Validate:

```bash
python3 scripts/datasets/validate_pomona_water_irrigation_risk_dataset.py
```

Build local generated splits:

```bash
python3 scripts/datasets/build_pomona_water_irrigation_risk_dataset.py
```
