# Model registry

Metadata only — **no training code, no weights**.

Each `*.yaml` file describes a model Pomona can use at runtime. Published weights are loaded from Hugging Face; local candidate adapters stay outside GitHub until you choose to release them.

| File | Hugging Face |
|------|--------------|
| `agronomist-gemma4.yaml` | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |
| `tomato-risk-reasoner-v0.1.7.yaml` | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) — experimental; learned a training shortcut ([details](../../docs/TOMATO_RISK_REASONER.md)) |
| `water-irrigation-risk-reasoner-v0.1.yaml` | [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) — release candidate |
| `actuator-command-gate-reasoner-v0.1.yaml` | [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) — research preview; deterministic checker required |
| `safety-triage-reasoner-v0.1.yaml` | Local candidate, not published |
| `sensor-quality-reasoner-v0.1.yaml` | Local candidate, not published |
| `nutrient-ph-ec-reasoner-v0.1.yaml` | [Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-lora](https://huggingface.co/Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-lora) (+ GGUF, MLX) — evaluated on synthetic cases only; guarded route required |

Training code lives in a separate GitHub repo: `pomona-agronomist-llm` (not yet published).

Future models add a new YAML here when their task, schema, eval, and safety boundaries are clear.

Current published assets:

```text
model:   Okyanus/ai-pomona-agronomist-gemma4
model:   Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora
model:   Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora
model:   Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora
model:   Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-lora (+ -GGUF, -MLX)
dataset: Okyanus/greenhouse-sensor-data
```

Current model decision (owner's local setup; unpublished models are not available to others):

```text
research only, rules decide: tomato-risk v0.1.7 (training shortcut, see docs/TOMATO_RISK_REASONER.md)
use as release candidate with deterministic validation: water-irrigation v0.1.8
local integration tests only: sensor-quality v0.1.1-boundary
local integration tests only: safety-triage v0.1
use only through the deterministic guarded route: nutrient-ph-ec v0.1.1 correction (synthetic eval only)
use with deterministic checker: actuator-command-gate v0.1
do not use: actuator-command-gate v0.1.1-hardcases
do not use: actuator-command-gate v0.1.2-correction
```
