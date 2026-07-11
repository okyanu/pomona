# FAQ

**Is this production-ready?**
No. Pomona is an early MVP (Phase 2 of 11). Simulated sensors, an in-memory
API, and a stub advisor work today; dashboard and database persistence are
in progress. See [Roadmap](Roadmap).

**Can the LLM control my actuators directly?**
No — that is a hard rule of the architecture. The LLM only advises. A
deterministic safety-checker is the final authority on any action, and
some actions additionally require human approval. See [Architecture](Architecture).

**Where do I get the models?**
Platform code, routing, and deterministic safety logic live in this GitHub
repo. Trained model weights and datasets live on Hugging Face — see
[Model Status](Model-Status).

**Which repo do I train models in?**
Not this one. ML training lives in the sibling repo
[pomona-agronomist-llm](https://github.com/Okyanus/pomona-agronomist-llm).
This repo (`pomona`) is the platform: Docker, MQTT, core API, model-router,
simulators.

**How do I run it locally?**
See [Getting Started](Getting-Started) — Docker quickstart takes under 5 minutes.

**How are versions numbered?**
Platform, models, and datasets each version independently
(semantic versioning + lifecycle labels like `experimental`,
`research_preview`, `release_candidate`). Full rules:
[docs/VERSIONING.md](https://github.com/Okyanus/pomona/blob/main/docs/VERSIONING.md).

**How can I contribute?**
Fork → branch → `make test` → open a PR. Good first contributions: dashboard
(Phase 2), tests, docs, simulators, crop templates. See
[CONTRIBUTING.md](https://github.com/Okyanus/pomona/blob/main/CONTRIBUTING.md).

**Is it open source?**
Yes — Apache-2.0, contributions welcome.
