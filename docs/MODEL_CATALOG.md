# Pomona Model Catalog

This is Pomona's GitHub-facing model card index. It records model family
status, lineage, runtime formats, and safety boundaries. Weights are not stored
in this repository.

All published models and the dataset are also collected in one place on
Hugging Face: [Pomona — Local AI for Safer Greenhouse Decision Support](https://huggingface.co/collections/Okyanus/pomona-local-ai-for-safer-greenhouse-decision-support-6a89931ffcc2f7a3f777f3b9).

Try the guarded tomato reasoner without installing anything:
[Pomona Greenhouse Demo](https://huggingface.co/spaces/Okyanus/pomona-greenhouse-demo).

## Current Families

| Family | Version | Status | Canonical artifact | Runtime role |
|---|---:|---|---|---|
| Agronomist assistant | Gemma4 | Published, experimental; no published evaluation | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) | Broad advisory explanation |
| Tomato risk | v0.1.7 | Published, experimental (learned a training shortcut; see [caveat](TOMATO_RISK_REASONER.md#evaluation-snapshot)) | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) | Tomato greenhouse risk labels |
| Water / irrigation risk | v0.1.8 | Published release candidate | [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) | Moisture and irrigation triage |
| Actuator command gate | v0.1 | Published research preview | [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) | Advisory command classification; deterministic gate is final |
| Sensor quality | v0.1.1-boundary | Unpublished local candidate | Local adapter only | Telemetry quality classification |
| Safety triage | v0.1 | Unpublished local candidate | Local adapter only | Action safety classification |
| Nutrient / pH-EC | v0.1.1 correction | LoRA plus guarded GGUF/MLX published | LoRA, GGUF/Ollama, MLX | pH/EC risk labels and fertigation blocking |

The agronomist model has no published evaluation: no benchmark, holdout or scores
are recorded in this repo or its registry file, so its quality is not yet measured. Only the weights are on Hugging Face; its
training repo, `pomona-agronomist-llm`, is not yet published (see
[REPOS.md](REPOS.md)). Treat it as experimental and advisory only.

## Model Count

- **4 published model families**: Agronomist, Tomato, Water/Irrigation, and Actuator Gate.
- **2 active unpublished model families**: Sensor Quality and Safety Triage. Nutrient/pH-EC v0.1.1 is published with guarded runtime formats.
- **Historical rejected experiments** remain local and are not release candidates, including Tomato v0.2.1-v0.2.4, Water v0.1.1-v0.1.7, and rejected Actuator Gate attempts.
- Water v0.1.8 also has published GGUF/Ollama and MLX deployment formats. These are conversions of the canonical LoRA, not separate trained families.

## Nutrient / pH-EC v0.1.1

The published adapter uses `Qwen/Qwen2.5-0.5B-Instruct` with a PEFT LoRA
adapter and explicit derived pH/EC state features. On a 140-case held-out set
it scored `1.0` for valid JSON, allowed labels/actions, label F1,
blocked-action F1, and human-review match (exact object match `0.0`, because
rationale wording varies). **That held-out set is synthetic:** it was generated
from Pomona's own rule templates, so the expected labels are what the rules say.
It is a self-consistency test, not a measure of real-world accuracy.

Harder measurements are much lower. The published GGUF, re-measured on
2026-10-25 on the same 140 cases without the guard, scored label F1 `0.5214`;
without the `derived_signals` input block it fell to about `0.14`-`0.19`. On
7 packets shaped like real pipeline input, the unguarded model scored label F1
about `0.21` and none passed the output validator. The guarded route's `1.0`
comes from the deterministic rules correcting the model's output afterwards.
On 120 real lab analyses (AGC2) the rules themselves flagged 55 cases that
contradict commercial rockwool practice; see
[NUTRIENT_PH_EC_REASONER.md](NUTRIENT_PH_EC_REASONER.md).

The model is advisory only. It must never dose nutrients, alter pH/EC, change
fertigation, or control equipment. Pomona's deterministic rules and human
review remain authoritative.

## Runtime Formats

For accepted candidates, Pomona can prepare PEFT LoRA, GGUF/Ollama, and MLX
deployment formats. Nutrient GGUF and MLX builds are prepared by local scripts;
the published Hugging Face copies are experimental runtime artifacts. Every
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

See the [model registry](https://github.com/okyanu/pomona/blob/main/models/registry/README.md) and
[LOCAL_MODEL_RUNTIMES.md](LOCAL_MODEL_RUNTIMES.md).
