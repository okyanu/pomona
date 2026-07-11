# Model registry

Metadata only — **no training code, no weights**.

Each `*.yaml` file describes a model Pomona can use at runtime. Published weights are loaded from Hugging Face; local candidate adapters stay outside GitHub until you choose to release them.

| File | Hugging Face |
|------|--------------|
| `agronomist-gemma4.yaml` | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |
| `tomato-risk-reasoner-v0.1.7.yaml` | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) |
| `water-irrigation-risk-reasoner-v0.1.yaml` | [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) — release candidate |
| `actuator-command-gate-reasoner-v0.1.yaml` | [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) — research preview; deterministic checker required |
| `safety-triage-reasoner-v0.1.yaml` | Local candidate, not published |
| `sensor-quality-reasoner-v0.1.yaml` | Local candidate, not published |
| `water-irrigation-risk-reasoner-v0.1.yaml` | Local scaffold, not trained or published |

Training code lives in a separate GitHub repo: [pomona-agronomist-llm](https://github.com/Okyanus/pomona-agronomist-llm).

Future models add a new YAML here when their task, schema, eval, and safety boundaries are clear.

Current published assets:

```text
model:   Okyanus/ai-pomona-agronomist-gemma4
model:   Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora
model:   Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora
model:   Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora
dataset: Okyanus/greenhouse-sensor-data
```

Current local model decision:

```text
use: tomato-risk v0.1.7
use as release candidate with deterministic validation: water-irrigation v0.1.8
use: sensor-quality v0.1.1-boundary
use: safety-triage v0.1
use with deterministic checker: actuator-command-gate v0.1
do not use: actuator-command-gate v0.1.1-hardcases
do not use: actuator-command-gate v0.1.2-correction
```
