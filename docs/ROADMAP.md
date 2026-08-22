# Pomona roadmap

Open edge AI for controlled agriculture.

**Platform `v0.1.0-alpha.1`** · **11 phases (0–10)** · **2 done** · **6 active/partial** · **Phase 2 primary focus** · [Full tracker →](./PHASES.md)

| # | Focus | Status |
|---|--------|--------|
| 0 | Repo, docs, open source | ✅ |
| 1 | Docker, core API, MQTT, simulator | ✅ |
| 2 | Dashboard + persistence | ⏳ partial — local SQLite/dashboard/Docker/simulation/backup validation complete; production hardening remains |
| 3 | Tomato reasoner | ⏳ partial — deterministic guarded route works; local LoRA wiring pending |
| 3b | Water/irrigation reasoner | ⏳ partial — [v0.1.8 release candidate](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) published; guarded platform wiring verified locally |
| 4 | Safety checker | ⏳ partial — deterministic tomato and actuator gates implemented |
| 5 | LLM advisor ([HF](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)) | ⏳ partial — adapter/router contract exists; live backend remains optional |
| 6 | Automation (suggestions) | ⬜ |
| 7 | Public browser demo | ⬜ |
| 8 | ESP32 devices | ⬜ |
| 9 | Model registry | ⏳ partial — `models/registry/` |
| 10 | Train reasoner models | ⏳ partial — v0.1.7 LoRA on HF |

Product phases and release versions are separate. See [VERSIONING.md](./VERSIONING.md).

## Phase 8 hardware design inspiration

[OpenValve](https://github.com/fabiansteiner/OpenValve) is an open-hardware,
3D-printable, bistable pinch valve designed for small greenhouse and
irrigation systems, including gravity-fed water. It is noted here only as
design inspiration for Phase 8 actuator hardware — Pomona has not integrated,
purchased, bench tested, or adopted it, and there is no current plan to build
an adapter for it.

Whatever irrigation actuator hardware Pomona eventually targets in Phase 8,
the same non-negotiable safety principles apply:

- electrical isolation, default-safe (fail-closed) behavior, manual
  close/override, command acknowledgement, and recovery after power or
  network loss;
- maximum open duration and flow limits, leak detection, stale-sensor
  blocking, and an allowlisted irrigation-only command schema;
- every proposed command routed through the deterministic safety checker,
  with human approval required during hardware validation;
- an advisory-only model-router: no LLM output may directly operate an
  actuator;
- no nutrient, fertilizer, pesticide, or other chemical dosing.

OpenValve hardware is published under its own license; any future reference
would link to the upstream design rather than copy it into this repository.

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
| Nutrient / pH-EC `v0.1.1-correction` | Published | LoRA, GGUF, and MLX; use only through the deterministic guarded route |

Next integration work:

```text
POST /v1/reasoners/sensor-quality
POST /v1/reasoners/tomato-risk
POST /v1/reasoners/safety-triage
POST /v1/actuator-command-gate/check
```

Future model families:

```text
strawberry risk reasoner
lettuce risk reasoner
aquaponic water chemistry reasoner
daily farm summary reasoner
digital twin scenario reasoner
```

Do not let any model directly control actuators. All actuator or chemical decisions must pass deterministic safety checks and human approval paths.

Implementation detail: [PROJECT_STATUS.md](./PROJECT_STATUS.md)
