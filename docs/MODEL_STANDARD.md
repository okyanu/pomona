# Pomona Model Standard

Every Pomona-compatible model should include a `pomona-model.yaml`.

## Example

```yaml
id: tomato-greenhouse-reasoner
name: Tomato Greenhouse Reasoner
version: 0.1.0
author: Okyanus
license: apache-2.0

type: reasoner

runtime:
  engine: rule
  format: python

language:
  - tr
  - en

domain:
  crop:
    - tomato
  environment:
    - greenhouse
  region:
    - mediterranean
    - turkey

inputs:
  required:
    - crop
    - growth_stage
    - air_temperature_c
    - humidity_pct
    - ec_ms_cm
    - ph
  optional:
    - drainage_ec
    - drainage_ph
    - soil_moisture_pct
    - leaf_image

outputs:
  schema:
    - risk_scores
    - diagnosis
    - recommendation
    - missing_data
    - confidence
    - human_review_required

hardware:
  minimum:
    ram: 1GB
  recommended:
    device:
      - raspberry_pi_5
      - mini_pc

safety:
  requires_safety_checker: true
  forbidden:
    - direct_pesticide_dosage
    - definite_diagnosis_without_evidence
    - unsafe_fertilizer_recommendation

evaluation:
  metrics:
    - agronomic_safety
    - threshold_accuracy
    - missing_data_behavior
    - recommendation_quality
```

## Model types

### advisor_llm

Conversation and explanation model.

Example:
- `Okyanus/ai-pomona-agronomist-gemma4`

### reasoner

Small verifiable decision model.

Example:
- tomato EC/pH/humidity reasoner

### vision

Image model.

Example:
- leaf disease detector

### forecaster

Time-series prediction model.

Example:
- irrigation need forecast

### tinyml

Microcontroller model.

Example:
- ESP32 anomaly detection

## Safety classes

### advisory_only

Can explain and suggest checks. Cannot trigger action.

### human_review_required

Can recommend, but user must approve.

### automation_safe

Can be used in automation after safety checker and explicit user configuration.
