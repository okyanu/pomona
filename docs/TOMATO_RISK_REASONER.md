# Pomona Tomato Risk Reasoner

Pomona's first small-purpose reasoner is a compact tomato greenhouse risk-label model.

```text
sensor JSON -> risk label JSON list -> deterministic safety guardrails -> dashboard/API output
```

## Current Model

| Field | Value |
|---|---|
| Hugging Face | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) |
| Base model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Adapter | PEFT LoRA |
| Task | Tomato greenhouse sensor JSON to risk-label JSON list |
| Best local adapter | `v0.1.7-risk-label-list-normalfix` |
| Dataset | [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) |
| Safety mode | Must be used with Pomona deterministic tomato rules |

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

## Hybrid Architecture

The small model is useful, but it is not the final authority for safety-critical thresholds.

```text
sensor state
  -> small LoRA model predicts labels
  -> tomato rule checker validates/corrects labels
  -> guarded labels move to API/dashboard
```

This keeps the system local-first and cheap while still enforcing exact safety boundaries in code.

## Local Test

The local adapter and helper scripts live under `private/` and are not committed to GitHub.

```bash
cd ~/Desktop/pomona

./private/colab/run_hybrid_tomato_reasoner.sh
./private/colab/run_hybrid_tomato_reasoner_batch.sh
```

The batch test writes:

```text
private/colab/outputs/tomato_risk_batch_outputs.jsonl
private/colab/outputs/tomato_risk_big_llm_validation_prompts.jsonl
```

## Evaluation Snapshot

Model-only:

```text
v0.1.7 staged risk F1: 0.924 on its original staged test
v0.1.7 golden risk F1: 0.667
```

Hybrid guarded:

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

The hybrid scores are measured on rule-derived evaluation data. They show that the guardrail integration works, not that the model is a complete agronomist.

## Safety Boundaries

This model must not be used for:

- direct pesticide dosage,
- autonomous fertigation changes,
- direct actuator control,
- definitive disease diagnosis,
- unsafe chemical recommendations.

Pomona's rule checker and future safety checker must remain between model output and any automation layer.

## Future Use

This model is the first checkpoint in the [small model factory](./SMALL_MODEL_FACTORY.md). Future Pomona models should follow the same pattern:

```text
narrow task -> small adapter -> deterministic guardrails -> hybrid evaluation
```
