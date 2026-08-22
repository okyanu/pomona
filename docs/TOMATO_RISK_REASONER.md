# Pomona Tomato Risk Reasoner

Pomona's first small-purpose reasoner: a compact LoRA adapter that reads a
tomato sensor reading from a substrate/soil greenhouse or a hydroponic
(`controlled_greenhouse`) system and returns a bounded list of risk labels.

```text
sensor JSON -> risk label JSON list -> deterministic safety guardrails -> dashboard/API output
```

| Field | Value |
|---|---|
| Hugging Face | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) |
| Base model | `Qwen/Qwen2.5-0.5B-Instruct` |
| Adapter format | PEFT LoRA (safetensors) |
| Task | Tomato greenhouse sensor JSON to a JSON list of risk labels |
| Dataset | [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) |
| Safety mode | Must run behind Pomona's deterministic tomato rules; advisory only |

## Allowed labels

```json
["high_ph", "low_ph", "high_ec", "low_ec", "heat_stress", "cold_stress",
 "fungal_pressure", "nutrient_uptake_issue", "sensor_anomaly",
 "missing_critical_data", "water_level_risk", "actuator_conflict"]
```

## Try it — guarded platform route (works today)

This is the path Pomona actually runs right now. LoRA inference is not yet
wired into the platform runtime, so `hybrid_guarded` mode falls back to the
deterministic tomato rules and says so explicitly in `fallback_reason` — this
card will update the moment that changes.

```bash
git clone https://github.com/Okyanus/pomona.git
cd pomona
cp .env.example .env
./scripts/up.sh

python3 examples/tomato_risk_quickstart.py
```

That script sends the committed
[examples/scenarios/arizona_tomato.json](../examples/scenarios/arizona_tomato.json)
scenario to `POST /v1/reasoners/tomato-risk` with no extra dependencies and no
files under `private/`. The equivalent raw request:

```bash
curl -s -X POST http://localhost:8081/v1/reasoners/tomato-risk \
  -H "Content-Type: application/json" \
  -d '{
    "mode": "hybrid_guarded",
    "input": {
      "system_type": "greenhouse_substrate",
      "crop": "tomato",
      "growth_stage": "fruiting",
      "air_temperature_c": 33.0,
      "humidity_pct": 80.0,
      "substrate_moisture_pct": 27.0,
      "ph": 5.2,
      "ec_ms_cm": 3.8,
      "substrate_temperature_c": 27.0
    }
  }'
```

Real output from this exact request:

```json
{
  "risk_labels": ["low_ph", "heat_stress", "nutrient_uptake_issue"],
  "missing_data": [],
  "safe_next_checks": [
    "repeat pH measurement with a calibrated meter",
    "review greenhouse temperature trend and ventilation state"
  ],
  "blocked_actions": ["autonomous_fertigation_change", "direct_actuator_control"],
  "human_review_required": true,
  "model_id": "pomona-tomato-risk-reasoner-v0.1.7",
  "mode": "hybrid_guarded",
  "source": "deterministic_rules",
  "fallback_reason": "LoRA runtime is not configured yet; used deterministic rules fallback."
}
```

## Try it — the LoRA adapter directly (research use)

To exercise the model outside Pomona's guardrails, load the published adapter
directly from Hugging Face:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

base = "Qwen/Qwen2.5-0.5B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(base)
model = AutoModelForCausalLM.from_pretrained(base)
model = PeftModel.from_pretrained(model, "Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora")
```

Treat any output from this path as unverified model-only output: it has not
passed through Pomona's deterministic tomato rules or safety checker.

## Hardware

`Qwen2.5-0.5B-Instruct` is small enough to run on CPU only; a few GB of RAM is
enough to load the base model plus adapter. No GPU is required for the
guarded platform route above, since that route is deterministic rules today.

## Evaluation snapshot

| | Model-only | Hybrid guarded |
|---|---:|---:|
| Golden eval risk F1 | 0.667 | 1.000 |
| Staged test risk F1 | 0.924 | 1.000 |

Hybrid scores are measured on rule-derived evaluation data. They show the
guardrail integration works — not that the model is a complete agronomist.
Full metadata: [models/registry/tomato-risk-reasoner-v0.1.7.yaml](../models/registry/tomato-risk-reasoner-v0.1.7.yaml).

## Limitations

- Model-only inference is not yet wired into the Pomona runtime; today's
  guarded route is deterministic rules, not the LoRA.
- Evaluated on rule-derived and staged data, not independent field trials.
- Tomato greenhouse only — not validated for other crops or systems.
- Rationale/explanation wording is not exact-matched against any reference;
  only the label and blocked-action outputs are scored.

## Safety boundaries

This model must not be used for:

- direct pesticide dosage,
- autonomous fertigation changes,
- direct actuator control,
- definitive disease diagnosis,
- unsafe chemical recommendations.

Pomona's deterministic rule checker and safety checker sit between any model
output and automation. No LLM output operates equipment directly.

## Ecosystem links

- Platform: [github.com/Okyanus/pomona](https://github.com/Okyanus/pomona)
- Model: [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- Dataset: [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)
- Model catalog: [docs/MODEL_CATALOG.md](MODEL_CATALOG.md)
- Small model factory pattern: [docs/SMALL_MODEL_FACTORY.md](SMALL_MODEL_FACTORY.md)

## Future use

This model is the first checkpoint in the
[small model factory](SMALL_MODEL_FACTORY.md). Future Pomona reasoners follow
the same pattern:

```text
narrow task -> small adapter -> deterministic guardrails -> hybrid evaluation
```
