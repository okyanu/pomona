# Model Status

Pomona keeps platform code, routing, deterministic safety logic, and
metadata in GitHub. Model weights and published datasets live on
Hugging Face. See [Versioning](https://github.com/Okyanus/pomona/blob/main/docs/VERSIONING.md) for how version numbers and lifecycle labels work.

| Model | Current status | Use now? |
|-------|----------------|----------|
| Tomato risk reasoner `v0.1.7` | Published on Hugging Face | ✅ Use |
| Water/irrigation reasoner `v0.1.8` | Published release candidate | ✅ Advisory + deterministic validation |
| Sensor quality reasoner `v0.1.1-boundary` | Local candidate, not published | ✅ Use for integration |
| Safety triage reasoner `v0.1` | Local candidate, not published | ✅ Use for integration |
| Actuator command gate `v0.1` | Published research preview, below standalone release gate | ⚠️ Advisory only; deterministic checker required |
| Actuator command gate `v0.1.1-hardcases` | Regression in local eval | ❌ Do not use |
| Actuator command gate `v0.1.2-correction` | Regression in independent eval | ❌ Do not use |

## Published Hugging Face assets

| Asset | Link |
|---|---|
| Agronomist advisor LLM | [Okyanus/ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |
| Tomato risk reasoner | [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) |
| Water/irrigation reasoner | [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) |
| Actuator command gate | [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) |
| Greenhouse sensor dataset | [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) |

## Safety rule

No model lifecycle label — experimental, research preview, or release
candidate — grants actuator authority on its own. Every action still passes
through the deterministic actuator-command gate and, where required, human
approval.

## Next model families

Tracked in [Roadmap](Roadmap) and `docs/SMALL_MODEL_FACTORY.md`: nutrient/pH-EC reasoner, strawberry risk reasoner, lettuce risk reasoner.
