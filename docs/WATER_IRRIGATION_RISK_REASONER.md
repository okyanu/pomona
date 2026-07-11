# Pomona Water / Irrigation Risk Reasoner

The Water / Irrigation Risk Reasoner is a planned small specialist model for crop-agnostic irrigation telemetry.

Task:

```text
farm context + irrigation sensor JSON
  -> irrigation risk labels + missing/suspect fields + safe next checks
```

This model should run before any irrigation suggestion and after sensor-quality checks.

## Why This Model Exists

Water and irrigation failures are common, measurable, and safety relevant:

- low reservoir or tank level,
- dry root-zone or substrate,
- over-wet substrate,
- pump running with no flow,
- flow reported while pump/valve are off,
- stale irrigation telemetry,
- missing moisture or water-level readings.

These are good Pomona small-model tasks because outputs are strict and verifiable.

## Current Direction

The current release candidate is `v0.1.8-context-low-lock`, a LoRA adapter on `Qwen/Qwen2.5-0.5B-Instruct`.

The trainable model is intentionally limited to moisture-risk labels:

- missing moisture,
- low/high moisture,
- under/overwatering,
- stale irrigation telemetry,
- impossible moisture values,
- insufficient context.

Pump, valve, and flow conflicts remain deterministic safety-checker logic until real actuator logs exist.

## Output Labels

```json
[
  "missing_moisture",
  "low_moisture",
  "high_moisture",
  "irrigation_underwatering",
  "irrigation_overwatering",
  "stale_irrigation_data",
  "sensor_anomaly",
  "insufficient_context"
]
```

## Safety Boundary

The model is advisory only. It must not directly control pumps, valves, or irrigation schedules. Blocked actions include:

```json
[
  "autonomous_irrigation_change",
  "irrigation_schedule_change"
]
```

## Current Status

Status: v0.1.8 is published as a release candidate at [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora). It remains advisory and requires deterministic validation and human review.

Evaluation summary:

```text
leakage-free internal test: 392 cases
  label F1:             1.000
  blocked-action F1:    1.000
  human-review match:   1.000
  allowed outputs:      1.000

independent holdout: 168 cases
  label F1:             1.000
  blocked-action F1:    1.000
  human-review match:   1.000
  required fields:      1.000
```

Both sets are synthetic and rule-derived. They validate this narrow policy task and JSON contract, not real-world agronomic efficacy.

Files:

```text
datasets/pomona-water-irrigation-risk-v0.1/
scripts/datasets/build_pomona_water_irrigation_risk_dataset.py
scripts/datasets/build_pomona_water_irrigation_realderived_dataset.py
scripts/datasets/validate_pomona_water_irrigation_risk_dataset.py
scripts/datasets/validate_pomona_water_irrigation_realderived_dataset.py
models/registry/water-irrigation-risk-reasoner-v0.1.yaml
scripts/huggingface/publish_water_irrigation_reasoner_to_hf.sh
```

Candidate real-data source:

```text
datasets/sources/purdue_whin_soil_weather.yaml
```

Do not download or publish Purdue WHIN data until license terms are manually verified.
