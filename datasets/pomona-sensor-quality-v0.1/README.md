# Pomona Sensor Quality v0.1

Dataset scaffold for a crop-agnostic sensor quality reasoner.

Task:

```text
farm context + sensor JSON
  -> data_quality_labels + missing_fields + suspect_fields + safe_next_checks
```

Validate:

```bash
python3 scripts/datasets/validate_pomona_sensor_quality_dataset.py
```

Build local generated splits:

```bash
python3 scripts/datasets/build_pomona_sensor_quality_dataset.py
```
