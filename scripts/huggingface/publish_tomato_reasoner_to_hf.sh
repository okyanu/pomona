#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADAPTER_ZIP="${ADAPTER_ZIP:-${ROOT_DIR}/private/colab/adapters/v0.1.7-risk-label-list-normalfix.zip}"
HF_REPO_ID="${HF_REPO_ID:-Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora}"
HF_REPO_DIR="${HF_REPO_DIR:-${HOME}/Desktop/hf-repos/pomona-tomato-risk-reasoner-v0.1.7-lora}"

if [ ! -f "${ADAPTER_ZIP}" ]; then
  echo "Adapter zip not found: ${ADAPTER_ZIP}" >&2
  exit 1
fi

mkdir -p "${HF_REPO_DIR}"

if [ ! -d "${HF_REPO_DIR}/.git" ]; then
  echo "Hugging Face repo checkout missing: ${HF_REPO_DIR}" >&2
  echo "Create and clone it first:" >&2
  echo "  hf repo create ${HF_REPO_ID} --type model --public --exist-ok" >&2
  echo "  git clone https://huggingface.co/${HF_REPO_ID} ${HF_REPO_DIR}" >&2
  exit 1
fi

cd "${HF_REPO_DIR}"
git lfs install --local
git lfs track "*.safetensors"

rm -f adapter_config.json adapter_model.safetensors chat_template.jinja tokenizer.json tokenizer_config.json training_args.bin README.md labels.json sample_input.json

unzip -j -o "${ADAPTER_ZIP}" \
  adapter_config.json \
  adapter_model.safetensors \
  chat_template.jinja \
  tokenizer.json \
  tokenizer_config.json \
  training_args.bin \
  >/dev/null

cat > labels.json <<'JSON'
[
  "high_ph",
  "low_ph",
  "high_ec",
  "low_ec",
  "heat_stress",
  "cold_stress",
  "fungal_pressure",
  "nutrient_uptake_issue",
  "sensor_anomaly",
  "missing_critical_data",
  "water_level_risk",
  "actuator_conflict"
]
JSON

cat > sample_input.json <<'JSON'
{
  "system_type": "controlled_greenhouse",
  "crop": "tomato",
  "growth_stage": "flowering",
  "air_temperature_c": 24.0,
  "humidity_pct": 89.0,
  "co2_ppm": 600,
  "light_lux": null,
  "light_ppfd": 350,
  "ph": 6.2,
  "ec_ms_cm": 2.4,
  "tds_ppm": null,
  "water_temperature_c": 21.0,
  "substrate_temperature_c": 23.0,
  "substrate_moisture_pct": 45.0,
  "actuator_states": {
    "screen_energy_pct": 90
  },
  "symptoms": []
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
  - tomato
  - greenhouse
  - lora
  - risk-classification
  - safety
datasets:
  - Okyanus/pomona-tomato-risk-v0.1
---

# Pomona Tomato Risk Reasoner v0.1.7 LoRA

This is Pomona's first compact tomato greenhouse risk-label reasoner. It is a LoRA adapter trained for a narrow task:

```text
Pomona tomato greenhouse sensor JSON -> JSON list of risk labels
```

It is **not** a general chat model and it is **not** safe as a standalone controller. Use it with Pomona's deterministic tomato safety/rule checker.

## Motivation: Small Verifiable Reasoners

This model is part of Pomona's small-model factory experiment: instead of relying on one large general-purpose LLM for every agriculture task, Pomona trains compact specialists for narrow, verifiable jobs and wraps them with deterministic safety logic.

This direction is inspired by recent small-reasoner work such as:

- [VibeThinker-1.5B: Tiny Model, Big Logic](https://arxiv.org/abs/2511.06221)
- [VibeThinker-3B: Exploring the Frontier of Verifiable Reasoning in Small Language Models](https://arxiv.org/abs/2606.16140)

Pomona does **not** use VibeThinker code, weights, or training data. The connection is conceptual: VibeThinker-style work suggests that small models can become useful when the task is narrow, the output is verifiable, and evaluation is strict. Pomona applies that idea to agriculture by pairing a small LoRA reasoner with deterministic tomato safety rules.

In this release, the small model handles the learned risk-label classification behavior, while Pomona's rule checker enforces hard thresholds for missing data, impossible sensor values, water risk, fungal pressure, and actuator conflicts.

## Base Model

- Base: `Qwen/Qwen2.5-0.5B-Instruct`
- Adapter type: PEFT LoRA
- Output format: JSON list of risk labels

## Allowed Labels

```json
[
  "high_ph",
  "low_ph",
  "high_ec",
  "low_ec",
  "heat_stress",
  "cold_stress",
  "fungal_pressure",
  "nutrient_uptake_issue",
  "sensor_anomaly",
  "missing_critical_data",
  "water_level_risk",
  "actuator_conflict"
]
```

## Recommended Use

```text
sensor input
  -> v0.1.7 adapter predicts risk labels
  -> Pomona deterministic rule checker validates/corrects labels
  -> guarded hybrid output is used by API/dashboard
```

Do not use this adapter for direct pesticide dosage, autonomous fertigation changes, direct actuator control, definitive disease diagnosis, or unsafe chemical recommendations.

## Example Input

```json
{
  "system_type": "controlled_greenhouse",
  "crop": "tomato",
  "growth_stage": "flowering",
  "air_temperature_c": 24.0,
  "humidity_pct": 89.0,
  "co2_ppm": 600,
  "light_ppfd": 350,
  "ph": 6.2,
  "ec_ms_cm": 2.4,
  "water_temperature_c": 21.0,
  "substrate_temperature_c": 23.0,
  "substrate_moisture_pct": 45.0,
  "actuator_states": {
    "screen_energy_pct": 90
  },
  "symptoms": []
}
```

Expected guarded Pomona output:

```json
["fungal_pressure", "actuator_conflict"]
```

## Local Pomona Usage

In the Pomona platform repository:

```bash
cd ~/Desktop/pomona
./private/colab/run_hybrid_tomato_reasoner.sh
./private/colab/run_hybrid_tomato_reasoner_batch.sh
```

The local runner prints:

- `model_only`
- `rules_only`
- `hybrid_guarded`
- `raw_model_output`

## Evaluation Snapshot

Best standalone adapter from the local iteration:

```text
v0.1.7 staged risk F1: 0.924 on its original staged test
v0.1.7 golden risk F1: 0.667
```

Hybrid guarded evaluation with Pomona deterministic tomato rules:

```text
golden eval:
  model-only risk F1: 0.667
  hybrid risk F1:     1.000
  corrections:        5 / 15

v0.1.7 staged test:
  model-only risk F1: 0.902
  hybrid risk F1:     1.000
  corrections:        59 / 473
```

The hybrid score is measured on a rule-derived eval set, so it should be interpreted as a guardrail integration check, not as an independent real-world agronomy benchmark. Future releases should add human-reviewed field cases.

## Limitations

- Narrow tomato greenhouse risk-label classifier only.
- Not a chat model.
- Threshold reasoning is imperfect without Pomona guardrails.
- Does not replace agronomist review.
- Does not authorize autonomous actuator or chemical actions.

## Intended Role In Pomona

This adapter is one small specialist in the Pomona small-model factory:

```text
small task model + deterministic safety rules = practical local AI component
```

The platform repository keeps code, schemas, docs, and rule logic. Hugging Face stores model adapter weights.

## Citation / References

If you discuss the design motivation, cite the VibeThinker papers as related small-reasoner inspiration, not as the source of this model:

```bibtex
@article{xu2025vibethinker15b,
  title = {Tiny Model, Big Logic: Diversity-Driven Optimization Elicits Large-Model Reasoning Ability in VibeThinker-1.5B},
  author = {Xu, Sen and Zhou, Yi and Wang, Wei and Min, Jixin and Yin, Zhibin and Dai, Yingwei and Liu, Shixi and Pang, Lianyu and Chen, Yirong and Zhang, Junlin},
  journal = {arXiv preprint arXiv:2511.06221},
  year = {2025}
}

@article{xu2026vibethinker3b,
  title = {VibeThinker-3B: Exploring the Frontier of Verifiable Reasoning in Small Language Models},
  author = {Xu, Sen and Liu, Shixi and Wang, Wei and Min, Jixin and Dai, Yingwei and Yin, Zhibin and Chen, Yirong and Zhou, Xin and Zhang, Junlin},
  journal = {arXiv preprint arXiv:2606.16140},
  year = {2026}
}
```
MD

git status

if [ "${PUSH_TO_HF:-0}" = "1" ]; then
  hf upload "${HF_REPO_ID}" "${HF_REPO_DIR}" . --repo-type model
else
  echo "PUSH_TO_HF is not 1; not committing or pushing to Hugging Face."
fi
