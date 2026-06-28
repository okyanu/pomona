# Pomona — Open Edge AI Stack for Agriculture

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Contributions welcome](https://img.shields.io/badge/contributions-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Hugging Face model](https://img.shields.io/badge/Model-Hugging%20Face-yellow)](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4)

**Open source** edge AI platform for agriculture — MQTT ingest, reasoning, safety checks, and dashboards.

Anyone can clone, use, fork, and contribute under the [Apache-2.0 license](LICENSE).

> **Early MVP.** Simulated sensors → API → demo advisor. [What to expect →](docs/GETTING_STARTED.md)

## Quickstart (any OS — Docker)

```bash
git clone https://github.com/Okyanus/pomona.git
cd pomona
cp .env.example .env
./scripts/setup.sh          # optional first-time check
./scripts/up.sh
./scripts/sim.sh            # new terminal
curl http://localhost:8080/health
```

**Requirements:** [Docker Desktop](https://www.docker.com/products/docker-desktop/)  
**Optional:** Python 3.9+ for simulator/tests

| Service | URL |
|---------|-----|
| Core API | http://localhost:8080 |
| Model router | http://localhost:8081 |
| MQTT | localhost:1883 |

Full guide: **[docs/INSTALL.md](docs/INSTALL.md)**  
**Target:** one-command full stack (UI + DB in Docker) — [docs/PLUG_AND_PLAY.md](docs/PLUG_AND_PLAY.md)

## Open source & contribute

| | |
|---|---|
| **License** | [Apache-2.0](LICENSE) — free to use and modify |
| **Contributing** | [CONTRIBUTING.md](CONTRIBUTING.md) — PRs welcome |
| **Code of conduct** | [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) |
| **Current work** | [docs/PROJECT_STATUS.md](docs/PROJECT_STATUS.md) |
| **Roadmap** | [docs/ROADMAP.md](docs/ROADMAP.md) |

**Good first contributions:** dashboard (Phase 2), tests, docs, simulators, crop templates.

Fork → branch → `make test` → open PR.

## Related open repos

| Repo | Purpose |
|------|---------|
| **pomona** (this) | Platform — run with Docker |
| [pomona-agronomist-llm](https://github.com/Okyanus/pomona-agronomist-llm) | ML training |
| [HF model](https://huggingface.co/Okyanus/ai-pomona-agronomist-gemma4) | Agronomist weights |

## Project phases

**11 phases total** · **2 completed** · **Phase 2 in progress**

| Phase | Name | Status |
|-------|------|--------|
| 0 | Project setup & open source | ✅ |
| 1 | Local MVP (Docker, core, simulator) | ✅ |
| 2 | Dashboard + database | ⏳ **now** — completes Docker plug-and-play |
| 3 | Tomato reasoner | ⬜ |
| 4 | Safety checker | ⬜ |
| 5 | LLM advisor | ⬜ |
| 6 | Automation engine | ⬜ |
| 7 | Public demo | ⬜ |
| 8 | ESP32 devices | ⬜ |
| 9 | Model registry | ⬜ |
| 10 | Fine-tune pipeline | ⬜ |

Details & update rules: **[docs/PHASES.md](docs/PHASES.md)** · [PROJECT_STATUS.md](docs/PROJECT_STATUS.md)

## AI assistants

[AGENTS.md](AGENTS.md) — Cursor, Claude, Codex

## License

Copyright 2026 Pomona Contributors. Licensed under [Apache-2.0](LICENSE).
