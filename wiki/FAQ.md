# FAQ

**Is this production-ready?**
No. Pomona is an early MVP, tested in software only. Simulated sensors, a
SQLite-backed API, deterministic rules, a monitoring dashboard and
suggestion-only automation work locally. No hardware has been bench-tested and
there is no field data. See [Roadmap](Roadmap).

**Can the LLM control my actuators directly?**
No — that is a hard rule of the architecture. The LLM only advises. A
deterministic rules make every decision, and there is no actuator execution
path: automation only raises suggestions for a person to approve or reject. See [Architecture](Architecture).

**Where do I get the models?**
Platform code, routing, and deterministic safety logic live in this GitHub
repo. Trained model weights and datasets live on Hugging Face — see
[Model Status](Model-Status).

**Which repo do I train models in?**
Not this one. ML training lives in the sibling repo
`pomona-agronomist-llm` (not yet published).
This repo (`pomona`) is the platform: Docker, MQTT, core API, model-router,
simulators.

**How do I run it locally?**
See [Getting Started](Getting-Started) — Docker quickstart takes under 5 minutes.

**How are versions numbered?**
Platform, models, and datasets each version independently
(semantic versioning + lifecycle labels like `experimental`,
`research_preview`, `release_candidate`). Full rules:
[docs/VERSIONING.md](https://github.com/okyanu/pomona/blob/main/docs/VERSIONING.md).

**How can I contribute?**
Fork → branch → `make test` → open a PR. Good first contributions: tests, docs, simulators, crop templates. See
[CONTRIBUTING.md](https://github.com/okyanu/pomona/blob/main/CONTRIBUTING.md).

**Is it open source?**
Yes — Apache-2.0, contributions welcome.
