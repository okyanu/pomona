# Pomona Actuator Command Gate Reasoner

The Actuator Command Gate is the next Pomona small specialist model after sensor quality.

Published research preview: [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora). It is below the standalone release gate and must only be used with the deterministic checker described here.

Task:

```text
farm context + proposed command + sensor quality + risk/safety context
  -> allowed | blocked | needs_human_approval
  -> gate labels + blocked actions + safe alternatives
```

This model is not the final authority. The deterministic safety-checker endpoint is the final gate.

## Why This Model Exists

Pomona must never let an LLM directly control actuators. Future modules may propose actions from a dashboard, assistant, digital twin, or automation engine, but the action must pass through a hard gate before it can be shown as actionable.

The command gate answers:

```text
Can this proposed action be allowed, blocked, or routed to human approval?
```

## Endpoint

Deterministic checker:

```text
POST /v1/actuator-command-gate/check
```

Future model-router contract:

```text
POST /v1/reasoners/actuator-command-gate
```

## Input Shape

```json
{
  "farm_context": {
    "crop": "tomato",
    "system_type": "controlled_greenhouse",
    "zone_id": "greenhouse-a"
  },
  "sensor": {
    "air_temperature_c": 31.0,
    "humidity_pct": 68.0,
    "ph": 6.2,
    "ec_ms_cm": 2.4
  },
  "sensor_quality": {
    "data_quality_labels": [],
    "missing_fields": [],
    "suspect_fields": []
  },
  "risk_labels": ["heat_stress"],
  "actor": "automation_engine",
  "proposed_command": {
    "action_type": "open_vent",
    "target": "roof_vent",
    "value": 100,
    "unit": "pct",
    "description": "Open the roof vents automatically for 20 minutes."
  }
}
```

## Output Shape

```json
{
  "decision": "blocked",
  "gate_labels": ["direct_actuator_control_request", "climate_control_request", "human_approval_required"],
  "blocked_actions": ["direct_actuator_control"],
  "human_approval_required": true,
  "safe_alternatives": ["Present the proposed actuator change for human approval instead of executing it."],
  "rationale": "The proposal asks for direct actuator control, which Pomona must not execute autonomously."
}
```

## Allowed Decisions

```json
["allowed", "blocked", "needs_human_approval"]
```

## Allowed Gate Labels

```json
[
  "safe_observation_only",
  "safe_manual_check",
  "human_approval_required",
  "direct_actuator_control_request",
  "autonomous_fertigation_change",
  "irrigation_control_request",
  "climate_control_request",
  "chemical_application_request",
  "unsafe_chemical_recommendation",
  "definitive_disease_diagnosis",
  "missing_or_bad_sensor_data",
  "actuator_conflict",
  "out_of_policy_request"
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

## Dataset Scaffold

```text
datasets/pomona-actuator-command-gate-v0.1/
  README.md
  DATASET_CARD.md
  schema/
    input.schema.json
    output.schema.json
    labels.schema.json
  data/
    samples.jsonl
    eval_cases.jsonl
```

Generated local splits:

```text
datasets/processed/pomona-actuator-command-gate-v0.1/
  all_records.jsonl
  train.jsonl
  validation.jsonl
  test.jsonl
  summary.json
```

Hardcase training split:

```text
datasets/processed/pomona-actuator-command-gate-v0.1.1-hardcases/
  all_records.jsonl
  train.jsonl
  validation.jsonl
  test.jsonl
  summary.json
```

The v0.1.1 hardcase split focuses on:

- allowed observation vs human-approval observation,
- safe manual check vs bad-sensor manual check,
- chemical request vs fertigation request,
- climate actuator vs irrigation actuator.

Local Colab artifacts:

```text
private/colab/pomona_actuator_command_gate_reasoner_v0_1_1_hardcases_colab.ipynb
private/colab/pomona-actuator-command-gate-v0.1.1-hardcases-training-data.zip
```

## v0.1.2 Targeted Correction

The independent 126-case clean holdout showed that v0.1 is structurally
reliable but still confuses chemical requests, irrigation control,
actuator-conflict review, and clean manual checks. The v0.1.1 hardcase adapter
regressed, so v0.1.2 uses a broader correction curriculum instead of simply
adding more hardcases.

```text
datasets/processed/pomona-actuator-command-gate-v0.1.2-correction/
  all_records.jsonl
  train.jsonl
  validation.jsonl
  test.jsonl
  summary.json
```

The split contains 5,294 records: 4,237 train, 528 validation, and 529 test.
It has zero exact input overlap across splits and zero overlap with the
independent 126-case clean holdout. The correction curriculum covers chemical,
irrigation-control, actuator-conflict, clean/bad-sensor manual checks, climate,
fertigation, and observation controls.

Training artifacts:

```text
private/colab/pomona-actuator-command-gate-v0.1.2-correction-training-data.zip
private/colab/pomona_actuator_command_gate_reasoner_v0_1_2_correction_colab.ipynb
```

The first v0.1.2 run uses one epoch and learning rate `1.5e-4`. After training,
copy the downloaded adapter to:

```text
private/colab/adapters/actuator-command-gate-v0.1.2-correction-local.zip
```

Then compare it on the unchanged clean holdout:

```bash
private/venvs/pomona-model-test/bin/python \
  scripts/models/evaluate_unpublished_candidates.py \
  --candidate actuator-v0.1 \
  --candidate actuator-v0.1.2 \
  --per-bucket 0 \
  --device cpu \
  --output private/colab/outputs/actuator-v0.1-v0.1.2-clean-comparison.json
```

### v0.1.2 Evaluation Decision

The generated 50-case Colab smoke test scored 1.0 on every metric. That score
did not generalize to the independent 126-case clean holdout.

| Metric | v0.1 | v0.1.2 |
|---|---:|---:|
| Gate-label F1 | 0.8127 | 0.8537 |
| Blocked-action F1 | 0.8333 | 0.8889 |
| Decision match | 0.8571 | 0.6667 |
| Human-approval match | 0.8571 | 0.7778 |
| Allowed-label rate | 1.0 | 0.9841 |

v0.1.2 improved label extraction, actuator-conflict, and clean manual-check
labels, but became over-conservative: all clean observation and manual-check
cases were routed to human approval. It also invented
`safe_irrigation_control_request` twice and missed blocked actions in chemical
and irrigation cases. Decision: reject v0.1.2 as a standalone release and
retain v0.1 as the development candidate. The deterministic gate remains the
production authority.

## Safety Boundary

The model can classify, explain, and suggest safe alternatives. It must not execute commands. The deterministic safety checker remains the final authority before dashboard or automation flows.
