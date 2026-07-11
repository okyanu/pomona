# Pomona Sensor Quality Reasoner

The Sensor Quality Reasoner is the next planned small specialist model in Pomona's small-model factory.

Task:

```text
farm context + sensor JSON -> data quality labels + missing fields + suspect fields + safe next checks
```

This model answers a question that should happen before risk or action reasoning:

```text
Is this sensor data usable enough to reason from?
```

## Why This Model Exists

Pomona should not classify crop risk from bad telemetry. Missing pH, impossible humidity, stale timestamps, unit mismatches, sensor drift, and conflicting readings can make downstream models unsafe or misleading.

This model is crop-agnostic and useful across:

- tomato,
- strawberry,
- lettuce,
- hydroponic systems,
- substrate greenhouses,
- soil farms,
- future aquaponic or oceanic farm systems,
- digital twin inputs.

## Input Shape

```json
{
  "farm_context": {
    "crop": "tomato",
    "system_type": "controlled_greenhouse",
    "zone_id": "greenhouse-a"
  },
  "sensor": {
    "air_temperature_c": 24.0,
    "humidity_pct": 68.0,
    "ph": 6.2,
    "ec_ms_cm": 2.4,
    "substrate_moisture_pct": 45.0,
    "timestamp": "2026-07-07T10:00:00Z"
  },
  "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
}
```

## Output Shape

```json
{
  "data_quality_labels": [],
  "missing_fields": [],
  "suspect_fields": [],
  "safe_next_checks": ["continue routine monitoring"],
  "human_review_required": false,
  "rationale": "Critical sensor readings are present and inside plausible ranges."
}
```

## Allowed Labels

```json
[
  "missing_ph",
  "missing_ec",
  "missing_temperature",
  "missing_humidity",
  "missing_moisture",
  "impossible_ph",
  "impossible_ec",
  "impossible_temperature",
  "impossible_humidity",
  "stale_reading",
  "unit_mismatch",
  "sensor_drift_possible",
  "conflicting_readings",
  "insufficient_context"
]
```

## Relationship To Other Models

Recommended reasoning order:

```text
sensor quality reasoner
  -> tomato/crop risk reasoner
  -> safety triage reasoner
  -> deterministic safety checker
  -> dashboard / human approval
```

## Current Status

Status: scaffold, local dataset builders, and Colab training artifacts.

Generated train/validation/test files live under `datasets/processed/` and are ignored by Git.

Local generated artifacts:

- `datasets/processed/pomona-sensor-quality-v0.1/`: first balanced generated split.
- `datasets/processed/pomona-sensor-quality-v0.1.1-boundary/`: boundary-focused split for improving label confusion.
- `private/colab/pomona-sensor-quality-v0.1.1-boundary-training-data.zip`: local Colab upload zip.
- `private/colab/pomona_sensor_quality_reasoner_v0_1_1_boundary_colab.ipynb`: local Colab training notebook.

The v0.1.1 boundary split adds contrast cases for:

- `unit_mismatch` vs `conflicting_readings`,
- `impossible_*` vs `sensor_drift_possible`,
- `missing_*` vs `insufficient_context`,
- normal complete packets vs `stale_reading`.

Do not publish the first v0.1 sensor-quality adapter until it improves on boundary evaluation.
