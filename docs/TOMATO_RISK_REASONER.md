# Pomona Tomato Risk Reasoner

Pomona's first small-purpose reasoner: a compact LoRA adapter that reads a
tomato sensor reading from a substrate/soil greenhouse (`system_type:
greenhouse_substrate`) or a hydroponic, recirculating-solution system
(`system_type: controlled_greenhouse`) and returns a bounded list of risk
labels. The deterministic rules also accept `hydroponic_greenhouse` and
`hydroponic` as equivalent to `controlled_greenhouse`, since both the
training dataset and the hardware event contract have historically used
different spellings for the same hydroponic category.

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

The default, out-of-the-box path below runs deterministic rules only —
`REASONER_BACKEND=rules` is the safe default, so `hybrid_guarded` falls back
to the rules and says so explicitly in `fallback_reason`.

Local Ollama inference *is* wired into the runtime (schema-constrained JSON
decoding, output validated against the same safety invariants as the
rules), but it's off unless you explicitly set `REASONER_BACKEND=ollama` and
have `pomona-tomato-risk:v0.1.7-local` built and running in Ollama locally
— see [LOCAL_MODEL_RUNTIMES.md](LOCAL_MODEL_RUNTIMES.md). Even then,
`hybrid_guarded` validates the model's output but deliberately keeps
deterministic rules as the final answer; only `model_only` mode (evaluation
only) surfaces raw model output. The current local Ollama build scores 0.60
label F1 on the 15-case golden smoke suite, well below the rules' 1.0 — a
reason deterministic rules stay authoritative, not a reason to skip trying it.

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
  "model_id": "pomona-tomato-risk-reasoner-v0.1.7",
  "mode": "hybrid_guarded",
  "backend": "rules",
  "source": "deterministic_rules",
  "risk_labels": ["low_ph", "heat_stress", "nutrient_uptake_issue"],
  "missing_data": [],
  "safe_next_checks": [
    "repeat pH measurement with a calibrated meter",
    "review greenhouse temperature trend and ventilation state"
  ],
  "blocked_actions": ["autonomous_fertigation_change", "direct_actuator_control"],
  "human_review_required": true,
  "fallback_reason": "Tomato runtime is disabled; used deterministic rules fallback."
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

- Local Ollama inference is wired but off by default; `model_only` mode
  (evaluation only) currently scores 0.60 label F1 on the 15-case golden
  smoke suite, so `hybrid_guarded` still discards model output in favor of
  deterministic rules.
- Evaluated on rule-derived and staged data, not independent field trials.
- Tomato greenhouse or hydroponic (`greenhouse_substrate` /
  `controlled_greenhouse`) only — not validated for other crops or systems.
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
