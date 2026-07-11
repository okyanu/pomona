#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADAPTER_ZIP="${ADAPTER_ZIP:-${ROOT_DIR}/private/colab/adapters/pomona-safety-triage-reasoner-v0.1-lora-clean.zip}"
HF_REPO_ID="${HF_REPO_ID:-Okyanus/pomona-safety-triage-reasoner-v0.1-lora}"
HF_REPO_DIR="${HF_REPO_DIR:-${HOME}/Desktop/hf-repos/pomona-safety-triage-reasoner-v0.1-lora}"

if [ ! -f "${ADAPTER_ZIP}" ]; then
  echo "Adapter zip not found: ${ADAPTER_ZIP}" >&2
  exit 1
fi

mkdir -p "${HF_REPO_DIR}"
cd "${HF_REPO_DIR}"

rm -f adapter_config.json adapter_model.safetensors chat_template.jinja tokenizer.json tokenizer_config.json README.md labels.json sample_input.json sample_output.json eval_summary.json

unzip -j -o "${ADAPTER_ZIP}" \
  adapter_config.json \
  adapter_model.safetensors \
  chat_template.jinja \
  tokenizer.json \
  tokenizer_config.json \
  >/dev/null

cat > labels.json <<'JSON'
{
  "safety_labels": [
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
  ],
  "blocked_actions": [
    "direct_pesticide_dosage",
    "autonomous_fertigation_change",
    "direct_actuator_control",
    "definitive_disease_diagnosis",
    "unsafe_chemical_recommendation"
  ]
}
JSON

cat > sample_input.json <<'JSON'
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
  "risk_labels": [
    "fungal_pressure",
    "actuator_conflict"
  ],
  "proposed_action": "Apply pesticide now and close the energy screen.",
  "actor": "assistant_model"
}
JSON

cat > sample_output.json <<'JSON'
{
  "safety_labels": [
    "human_review_required",
    "direct_actuator_control_request",
    "pesticide_dosage_request",
    "unsafe_chemical_recommendation"
  ],
  "blocked_actions": [
    "direct_pesticide_dosage",
    "direct_actuator_control",
    "unsafe_chemical_recommendation"
  ],
  "safe_alternative": "Inspect canopy conditions, verify humidity trend, and ask a human operator before any treatment or actuator change.",
  "human_review_required": true,
  "rationale": "The proposal includes pesticide use and direct actuator control without verified diagnosis or human approval."
}
JSON

cat > eval_summary.json <<'JSON'
{
  "local_eval": {
    "split": "pomona-safety-triage-v0.1 test subset",
    "cases": 50,
    "valid_json_rate": 1.0,
    "allowed_labels_rate": 1.0,
    "allowed_blocked_actions_rate": 1.0,
    "safety_f1_avg": 0.99,
    "blocked_f1_avg": 1.0,
    "human_review_match_rate": 1.0,
    "exact_match_rate": 0.86
  },
  "notes": "Evaluation uses template-derived held-out cases. Treat this as a schema and guardrail behavior check, not real-world agronomy validation."
}
JSON

cat > README.md <<'MD'
---
license: apache-2.0
base_model: Qwen/Qwen2.5-0.5B-Instruct
library_name: peft
pipeline_tag: text-generation
tags:
  - pomona
  - agriculture
  - safety
  - lora
  - action-classification
  - greenhouse
  - small-reasoner
datasets:
  - Okyanus/pomona-safety-triage-v0.1
---

# Pomona Safety Triage Reasoner v0.1 LoRA

This is a compact Pomona safety-triage LoRA adapter for classifying proposed farm actions.

It is trained for a narrow JSON-output task:

```text
farm context + sensor state + risk labels + proposed action + actor
  -> safety labels + blocked actions + safe alternative + human_review_required + rationale
```

It is **not** a general chat model, **not** an agronomist replacement, and **not** a final safety authority. Use it with Pomona's deterministic safety checker and human approval workflows.

## Base Model

- Base: `Qwen/Qwen2.5-0.5B-Instruct`
- Adapter type: PEFT LoRA
- Output format: JSON object

## Output Schema

```json
{
  "safety_labels": [],
  "blocked_actions": [],
  "safe_alternative": "",
  "human_review_required": true,
  "rationale": ""
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

## Allowed Blocked Actions

```json
[
  "direct_pesticide_dosage",
  "autonomous_fertigation_change",
  "direct_actuator_control",
  "definitive_disease_diagnosis",
  "unsafe_chemical_recommendation"
]
```

## Intended Use

Use this adapter as an advisory classifier before deterministic safety enforcement:

```text
proposed action
  -> Pomona Safety Triage Reasoner
  -> deterministic safety checker
  -> dashboard / human approval
```

Good use cases:

- classify whether a proposed farm action is observation-only, manual-check, blocked, or human-review-required,
- detect pesticide/chemical recommendation requests,
- detect autonomous fertigation or recipe changes,
- detect direct actuator-control requests,
- flag definitive disease diagnosis from insufficient evidence,
- produce a safe alternative action.

## Not Intended For

Do not use this model to:

- control actuators,
- prescribe pesticides or chemical dosages,
- autonomously change fertigation recipes,
- make definitive crop disease diagnoses,
- replace a qualified human grower or agronomist,
- bypass Pomona deterministic safety rules.

## Example Input

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
  "proposed_action": "Apply pesticide now and close the energy screen.",
  "actor": "assistant_model"
}
```

Example output:

```json
{
  "safety_labels": [
    "human_review_required",
    "direct_actuator_control_request",
    "pesticide_dosage_request",
    "unsafe_chemical_recommendation"
  ],
  "blocked_actions": [
    "direct_pesticide_dosage",
    "direct_actuator_control",
    "unsafe_chemical_recommendation"
  ],
  "safe_alternative": "Inspect canopy conditions, verify humidity trend, and ask a human operator before any treatment or actuator change.",
  "human_review_required": true,
  "rationale": "The proposal includes pesticide use and direct actuator control without verified diagnosis or human approval."
}
```

## Local Evaluation Snapshot

On a local held-out subset of 50 template-derived safety-triage test cases:

```text
valid_json_rate:               1.00
allowed_labels_rate:           1.00
allowed_blocked_actions_rate:  1.00
safety_f1_avg:                 0.99
blocked_f1_avg:                1.00
human_review_match_rate:       1.00
exact_match_rate:              0.86
```

These are template-derived local eval cases, so they should be interpreted as a schema and guardrail behavior check, not as real-world field validation.

## Motivation: Small Verifiable Reasoners

This model is part of Pomona's small-model factory experiment: small specialist models for narrow, verifiable agriculture tasks, wrapped by deterministic safety logic.

This direction is conceptually inspired by small-reasoner work such as VibeThinker-style models, where narrow tasks, strict output formats, and verifiable evaluation matter more than general chat ability.

Pomona does **not** use VibeThinker code, weights, or training data.

## Related Pomona Artifacts

- Platform repo: `Okyanus/pomona`
- Related model: `Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora`
- Planned dataset scaffold: `Okyanus/pomona-safety-triage-v0.1`

## Limitations

- Synthetic/template-derived training data.
- Not yet validated on human-labeled farm incidents.
- May produce correct labels while wording differs from expected text.
- Requires deterministic safety checker as the final gate.
- Advisory only.
MD

echo "Prepared Hugging Face model folder: ${HF_REPO_DIR}"
find "${HF_REPO_DIR}" -maxdepth 1 -type f -print | sort

if command -v git >/dev/null 2>&1; then
  git status || true
fi

if [ "${PUSH_TO_HF:-0}" = "1" ]; then
  hf repo create "${HF_REPO_ID}" --type model --public --exist-ok
  hf upload "${HF_REPO_ID}" "${HF_REPO_DIR}" . --repo-type model
else
  echo "PUSH_TO_HF is not 1; not uploading to Hugging Face."
fi
