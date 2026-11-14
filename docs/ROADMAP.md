# Pomona roadmap

Open edge AI for controlled agriculture.

**Platform `v0.1.0-alpha.1`** · **11 phases (0–10)** · **2 done** · **8 active/partial** · **Phase 2 primary focus** · [Full tracker →](./PHASES.md)

Phases 0 and 1 are done; phases 2, 3, 4, 5, 6, 7, 9 and 10 are partial (some pieces exist, which does not mean the phase is being worked on now); Phase 8 (ESP32 devices) is still planned: logger firmware compiles; not yet bench-tested, no field data. Phase 2 stays the primary focus: local SQLite, dashboard, Docker, simulation and backup validation are complete and optional sensor-ingestion API-key auth was added, but authentication elsewhere, signed device identity and production observability remain. The tomato adapter (v0.1.7) learned a training shortcut (answers `[]` on 146 of 153 varied benchmark cases) and needs a retrain, so the deterministic rules decide. The full phase table is in [PHASES.md](./PHASES.md); the maintainer's current plan is in [NEXT_90_DAYS.md](./NEXT_90_DAYS.md).

Product phases and release versions are separate. See [VERSIONING.md](./VERSIONING.md).

## Key milestones

Tracked two ways: what's **sustainable** (works without ongoing hand-holding)
and what's still **manual toil** (needs a person, a script, or a decision
every time). Closing the second list is how the first list stays true.

### Sustainable — shipped and self-maintaining

- Deterministic rules make every decision; models only advise and there is
  no actuator execution path. Rule code does not drift the way a model can,
  but it can have defects (the actuator gate was a denylist until it became
  deny-by-default on 2026-11-07) and its thresholds are not field-calibrated.
- 5 models + 1 dataset published on Hugging Face, bundled in one
  [Collection](https://huggingface.co/collections/Okyanus/pomona-local-ai-for-safer-greenhouse-decision-support-6a89931ffcc2f7a3f777f3b9).
- Free, static public demo Space — no server to run, no paid tier, no
  hosting bill.
- CI ([`.github/workflows/ci.yml`](https://github.com/okyanu/pomona/blob/main/.github/workflows/ci.yml)) runs all six
  Python service test suites on every push/PR.
- `make local-check` verifies the platform without Docker — lowers the bar
  for anyone else to confirm a change works.
- First tagged GitHub release
  ([`v0.1.0-alpha.1`](https://github.com/okyanu/pomona/releases/tag/v0.1.0-alpha.1)).

### Manual toil — open items

- Keep the combined local and per-service CI suites aligned as new services
  and shared contracts are added. Run `make test-local` to verify the current
  baseline across all six Python services.
- Sensor quality, safety triage and the actuator gate still use deterministic
  fallback in the platform (no model path). Tomato, water/irrigation and
  nutrient/pH-EC have guarded local Ollama paths with schema-constrained
  decoding, but the tomato v0.1.7 GGUF is below standalone quality (0.60 F1 on
  the 15-case golden smoke suite), so deterministic rules stay authoritative:
  `hybrid_guarded` mode validates model output but discards it in favor of
  rules, and only `model_only` (evaluation) surfaces raw model output.
- One maintainer, one set of GitHub/HF credentials. No documented continuity
  or handoff process if that becomes unavailable.
- Naming drift between the dataset, hardware contract and deployed code (for
  example the `hydroponic` / `hydroponic_greenhouse` / `controlled_greenhouse`
  system types) is not caught automatically; only manual review finds it.

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
| Platform (this repo) | [okyanu/pomona](https://github.com/okyanu/pomona) | — |
| Agronomist training | `pomona-agronomist-llm` (not yet published) | [ai-pomona-agronomist-gemma4](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) |
| Tomato risk reasoner | [registry YAML](https://github.com/okyanu/pomona/blob/main/models/registry/tomato-risk-reasoner-v0.1.7.yaml) | [pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) |
| Water/irrigation reasoner | [registry YAML](https://github.com/okyanu/pomona/blob/main/models/registry/water-irrigation-risk-reasoner-v0.1.yaml) | [pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) |
| Actuator command gate | [registry YAML](https://github.com/okyanu/pomona/blob/main/models/registry/actuator-command-gate-reasoner-v0.1.yaml) | [pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora) — research preview |
| Greenhouse sensor dataset | [datasets/pomona-tomato-risk-v0.1/](https://github.com/okyanu/pomona/tree/main/datasets/pomona-tomato-risk-v0.1) | [greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) |

## Small Reasoner Roadmap

GitHub contains platform code, deterministic safety logic, docs, schemas, and metadata. Hugging Face contains model weights and clean published dataset artifacts.

Current best model set:

| Reasoner | Status | Notes |
|----------|--------|-------|
| Tomato risk `v0.1.7` | Published, experimental | Learned a training shortcut; research only, deterministic tomato rules decide |
| Sensor quality `v0.1.1-boundary` | Local, not published | Candidate for first integration tests; trained to label missing/suspect/stale/conflicting packets (generated data only) |
| Safety triage `v0.1` | Local candidate, failed its publish gate; not published | Local tests only; trained to classify unsafe proposed actions (generated data only); rules do the work |
| Water / irrigation risk `v0.1.8` | Published release candidate | Advisory; deterministic validation and human review required |
| Actuator command gate `v0.1` | Published research preview | Below standalone gate; deterministic checker remains final authority |
| Actuator command gate `v0.1.1-hardcases` | Rejected | Local eval regression; do not use |
| Actuator command gate `v0.1.2-correction` | Rejected | Held-out eval regression; do not use |
| Nutrient / pH-EC `v0.1.1-correction` | Published | LoRA, GGUF, and MLX; evaluated on synthetic cases only; use only through the deterministic guarded route |

Integration endpoints (all four exist; see [PROJECT_STATUS.md](./PROJECT_STATUS.md) for what each does):

```text
POST /v1/reasoners/sensor-quality
POST /v1/reasoners/tomato-risk
POST /v1/reasoners/safety-triage            (deterministic fallback; model runtime pending)
POST /v1/actuator-command-gate/check        (safety-checker; deterministic final authority)
```

Still to do: wire the remaining specialist model runtimes and improve tomato model-only quality.

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
