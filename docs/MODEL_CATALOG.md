# Pomona Model Catalog

This is Pomona's GitHub-facing model card index. It records model family
status, lineage, runtime formats, and safety boundaries. Weights are not stored
in this repository.

## Current Families

| Family | Version | Status | Canonical artifact | Runtime role |
|---|---:|---|---|---|
| Agronomist assistant | Gemma4 | Published | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) | Broad advisory explanation |
| Tomato risk | v0.1.7 | Published | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) | Tomato greenhouse risk labels |
| Water / irrigation risk | v0.1.8 | Published release candidate | [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) | Moisture and irrigation triage |
| Actuator command gate | v0.1 | Published research preview | [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) | Advisory command classification; deterministic gate is final |
| Sensor quality | v0.1.1-boundary | Unpublished local candidate | Local adapter only | Telemetry quality classification |
| Safety triage | v0.1 | Unpublished local candidate | Local adapter only | Action safety classification |
| Nutrient / pH-EC | v0.1.1 correction | LoRA plus guarded GGUF/MLX published | LoRA, GGUF/Ollama, MLX | pH/EC risk labels and fertigation blocking |

## Model Count

- **4 published model families**: Agronomist, Tomato, Water/Irrigation, and Actuator Gate.
- **2 active unpublished model families**: Sensor Quality and Safety Triage. Nutrient/pH-EC v0.1.1 is published with guarded runtime formats.
- **Historical rejected experiments** remain local and are not release candidates, including Tomato v0.2.1-v0.2.4, Water v0.1.1-v0.1.7, and rejected Actuator Gate attempts.
- Water v0.1.8 also has published GGUF/Ollama and MLX deployment formats. These are conversions of the canonical LoRA, not separate trained families.

## Nutrient / pH-EC v0.1.1

The current local candidate uses `Qwen/Qwen2.5-0.5B-Instruct` with a PEFT LoRA
adapter and explicit derived pH/EC state features. On the independent 140-case
holdout it achieved valid JSON, allowed labels/actions, label F1,
blocked-action F1, and human-review match of `1.0`. Rationale wording varies,
so exact object matching is `0.0`; this is not a reason to bypass deterministic
validation.

The model is advisory only. It must never dose nutrients, alter pH/EC, change
fertigation, or control equipment. Pomona's deterministic rules and human
review remain authoritative.

## Runtime Formats

For accepted candidates, Pomona can prepare PEFT LoRA, GGUF/Ollama, and MLX
deployment formats. Nutrient GGUF and MLX builds are prepared by local scripts
only for local testing and are not published by this repository. Every
conversion requires a fresh runtime evaluation. A conversion is not a new
trained model family.

Publication state is tracked separately from technical maturity. A local
release candidate is not public until the owner explicitly approves its
Hugging Face upload.

See [PUBLISHING_SCHEMA.md](PUBLISHING_SCHEMA.md) for the required states and
owner-approval workflow.

## Safety Rule

```text
sensor packet -> specialist model -> schema/label validation
  -> deterministic Pomona safety rules -> human approval -> optional automation
```

See [UNPUBLISHED_MODEL_RELEASES.md](UNPUBLISHED_MODEL_RELEASES.md), the
[model registry](../models/registry/README.md), and
[LOCAL_MODEL_RUNTIMES.md](LOCAL_MODEL_RUNTIMES.md).
