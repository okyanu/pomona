# Pomona roadmap

Open edge AI for controlled agriculture.

**Platform `v0.1.0-alpha.1`** · **11 phases (0–10)** · **2 done** · **6 active/partial** · **Phase 2 primary focus** · [Full tracker →](./PHASES.md)

| # | Focus | Status |
|---|--------|--------|
| 0 | Repo, docs, open source | ✅ |
| 1 | Docker, core API, MQTT, simulator | ✅ |
| 2 | Dashboard + persistence | ⏳ **now** |
| 3 | Tomato reasoner | ⏳ partial — [HF LoRA](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) published; platform wiring pending |
| 3b | Water/irrigation reasoner | ⏳ partial — [v0.1.8 release candidate](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) published; platform wiring pending |
| 4 | Safety checker | ⏳ partial — deterministic tomato and actuator gates implemented |
| 5 | LLM advisor ([HF](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)) | ⏳ partial — adapter and router contract exist; live wiring pending |
| 6 | Automation (suggestions) | ⬜ |
| 7 | Public browser demo | ⬜ |
| 8 | ESP32 devices | ⬜ |
| 9 | Model registry | ⏳ partial — `models/registry/` |
| 10 | Train reasoner models | ⏳ partial — v0.1.7 LoRA on HF |

Product phases and release versions are separate. See [VERSIONING.md](./VERSIONING.md).

## Repos and releases

| What | GitHub | Hugging Face |
|------|--------|--------------|
| Platform (this repo) | [Okyanus/pomona](https://github.com/Okyanus/pomona) | — |
| Agronomist training | [Okyanus/pomona-agronomist-llm](https://github.com/Okyanus/pomona-agronomist-llm) | [ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |
| Tomato risk reasoner | [registry YAML](../models/registry/tomato-risk-reasoner-v0.1.7.yaml) | [pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) |
| Water/irrigation reasoner | [registry YAML](../models/registry/water-irrigation-risk-reasoner-v0.1.yaml) | [pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) |
| Actuator command gate | [registry YAML](../models/registry/actuator-command-gate-reasoner-v0.1.yaml) | [pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) — research preview |
| Greenhouse sensor dataset | [datasets/pomona-tomato-risk-v0.1/](../datasets/pomona-tomato-risk-v0.1/) | [greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) |

## Small Reasoner Roadmap

GitHub contains platform code, deterministic safety logic, docs, schemas, and metadata. Hugging Face contains model weights and clean published dataset artifacts.

Current best model set:

| Reasoner | Status | Notes |
|----------|--------|-------|
| Tomato risk `v0.1.7` | Published | Best tomato risk-label adapter; use with deterministic tomato rules |
| Sensor quality `v0.1.1-boundary` | Local, not published | Good enough for first integration; detects missing/suspect/stale/conflicting sensor packets |
| Safety triage `v0.1` | Local, not published | Good enough for first integration; classifies unsafe proposed actions |
| Water / irrigation risk `v0.1.8` | Published release candidate | Advisory; deterministic validation and human review required |
| Actuator command gate `v0.1` | Published research preview | Below standalone gate; deterministic checker remains final authority |
| Actuator command gate `v0.1.1-hardcases` | Rejected | Local eval regression; do not use |
| Actuator command gate `v0.1.2-correction` | Rejected | Independent-eval regression; do not use |

Next integration work:

```text
POST /v1/reasoners/sensor-quality
POST /v1/reasoners/tomato-risk
POST /v1/reasoners/safety-triage
POST /v1/actuator-command-gate/check
```

Future model families:

```text
nutrient / pH-EC reasoner
strawberry risk reasoner
lettuce risk reasoner
aquaponic water chemistry reasoner
daily farm summary reasoner
digital twin scenario reasoner
```

Do not let any model directly control actuators. All actuator or chemical decisions must pass deterministic safety checks and human approval paths.

Implementation detail: [PROJECT_STATUS.md](./PROJECT_STATUS.md)
