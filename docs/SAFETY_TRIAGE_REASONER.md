# Pomona Safety Triage Reasoner

The Safety Triage Reasoner is the planned second small specialist model in Pomona's model factory.

It is inspired by the same small-verifiable-reasoner direction as the tomato risk model, but its task is different:

```text
farm context + risk labels + proposed action -> safety labels + blocked actions + safe alternative
```

This model is not the final authority. It is an advisory classifier/explainer that sits before Pomona's deterministic safety checker.

## Why This Model Exists

The tomato risk reasoner answers:

```text
What risks are present?
```

The Safety Triage Reasoner answers:

```text
Is this proposed response safe, blocked, or human-review-only?
```

This is useful because future Pomona modules may propose actions:

- a big assistant model,
- a small explainer model,
- a digital twin scenario,
- a dashboard automation suggestion,
- a human user asking "can I do this?"

Pomona needs a small specialist that classifies the safety status of the proposal before the deterministic safety checker makes the final gate decision.

## Intended Flow

```text
sensor data / farm context
  -> risk reasoner or digital twin
  -> proposed action or explanation
  -> Safety Triage Reasoner
  -> deterministic safety checker
  -> dashboard / chat / human approval
```

## Input Shape

```json
{
  "farm_context": {
    "crop": "tomato",
    "system_type": "controlled_greenhouse",
    "growth_stage": "flowering"
  },
  "sensor": {
    "air_temperature_c": 24.0,
    "humidity_pct": 89.0,
    "ph": 6.2,
    "ec_ms_cm": 2.4,
    "substrate_moisture_pct": 45.0
  },
  "risk_labels": ["fungal_pressure", "actuator_conflict"],
  "proposed_action": "Apply pesticide now and close the ventilation screen.",
  "actor": "assistant_model"
}
```

## Output Shape

```json
{
  "safety_labels": [
    "unsafe_chemical_recommendation",
    "direct_actuator_control_request",
    "human_review_required"
  ],
  "blocked_actions": [
    "direct_pesticide_dosage",
    "direct_actuator_control"
  ],
  "safe_alternative": "Inspect the canopy, verify humidity trend, and ask a human operator before treatment or actuator changes.",
  "human_review_required": true,
  "rationale": "The proposal includes chemical treatment and direct actuator control without verified diagnosis or human approval."
}
```

## Allowed Safety Labels

```json
[
  "safe_observation_only",
  "safe_manual_check",
  "missing_context",
  "human_review_required",
  "direct_actuator_control_request",
  "autonomous_fertigation_change",
  "pesticide_dosage_request",
  "unsafe_chemical_recommendation",
  "definitive_disease_diagnosis",
  "ignores_missing_data"
]
```

## Blocked Actions

```json
[
  "direct_pesticide_dosage",
  "autonomous_fertigation_change",
  "direct_actuator_control",
  "definitive_disease_diagnosis",
  "unsafe_chemical_recommendation"
]
```

## What Is Safe

Safe outputs should suggest checks, not direct interventions:

- inspect plants,
- verify sensor calibration,
- compare recent trends,
- ask for missing measurements,
- request human operator review,
- explain why an action is blocked.

## What Is Blocked

The model should flag or block:

- direct pesticide dosage,
- unsafe chemical recommendations,
- autonomous fertigation changes,
- direct actuator control,
- definitive disease diagnosis without evidence,
- ignoring missing critical sensor data.

## Dataset Scaffold

Scaffold and generated local training data:

```text
datasets/pomona-safety-triage-v0.1/
  README.md
  DATASET_CARD.md
  schema/
    input.schema.json
    output.schema.json
    labels.schema.json
  data/
    samples.jsonl
    eval_cases.jsonl

datasets/processed/pomona-safety-triage-v0.1/
  all_records.jsonl
  train.jsonl
  validation.jsonl
  test.jsonl
  summary.json
```

Validation:

```bash
python3 scripts/datasets/validate_pomona_safety_triage_dataset.py
```

Build generated splits:

```bash
python3 scripts/datasets/build_pomona_safety_triage_dataset.py
```

Current generated split:

```text
records=2011
train=1609
validation=201
test=201
```

Stronger local hardcase split:

```text
datasets/processed/pomona-safety-triage-v0.1.1-hardcases/
records=2371
hardcase_records=360
train=1897
validation=237
test=237
```

Colab artifacts:

```text
private/colab/pomona_safety_triage_reasoner_v0_1_1_hardcases_colab.ipynb
private/colab/pomona-safety-triage-v0.1.1-hardcases-training-data.zip
```

## Training Status

Status: dataset builder ready, not trained.

Recommended next training run is v0.1.1 hardcases in Colab, followed by local evaluation against held-out safety cases.

## Relationship To VibeThinker

Pomona does not use VibeThinker code, weights, or data. The inspiration is conceptual: use small models for narrow, verifiable reasoning tasks with strict output schemas and external guardrails.
