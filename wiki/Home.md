# Pomona Wiki

**Open edge AI platform for agriculture** — MQTT ingest, reasoning, deterministic safety checks, and dashboards for the greenhouse. Tomato greenhouse MVP first; more crops later.

Apache-2.0 licensed. [Source →](https://github.com/okyanu/pomona)

## Start here

| Page | What it covers |
|---|---|
| [Getting Started](Getting-Started) | Clone, run, and hit the API in under 5 minutes |
| [Architecture](Architecture) | How data flows from sensor to dashboard |
| [Model Status](Model-Status) | Which reasoner/advisor models are published and safe to use |
| [Roadmap](Roadmap) | Phases, what's done, what's next |
| [Dev Log](DevLog) | Dated notes on what changed and why |
| [FAQ](FAQ) | Common questions |

## The short version

```text
Sensor / Simulator → MQTT → pomona-core → DB → model-router
   → reasoner / advisor LLM → safety-checker → automation-engine → dashboard
```

The LLM **advises** — it never directly controls actuators. A deterministic
safety-checker is the final authority on any automation action.

## Repos & releases

| Type | Where |
|---|---|
| Platform (this repo) | [github.com/okyanu/pomona](https://github.com/okyanu/pomona) |
| ML training | `pomona-agronomist-llm` (not yet published) |
| Model weights | [huggingface.co/Okyanus](https://huggingface.co/Okyanus) |
| Datasets | [huggingface.co/datasets/Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data) |

## Contributing

Fork → branch → `make test` → open a PR. See [CONTRIBUTING.md](https://github.com/okyanu/pomona/blob/main/CONTRIBUTING.md) in the main repo. Good first contributions: dashboard (Phase 2), tests, docs, simulators, crop templates.
