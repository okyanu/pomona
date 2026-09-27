# Documentation

Public docs for contributors and users.

## Start here

| Doc | Audience |
|-----|----------|
| [PLUG_AND_PLAY.md](./PLUG_AND_PLAY.md) | **Full Docker stack vision (UI + DB)** |
| [INSTALL.md](./INSTALL.md) | Docker + pip install (all OS) |
| [CONTRIBUTING.md](https://github.com/okyanu/pomona/blob/main/CONTRIBUTING.md) | **How to contribute (open source)** |
| [CODE_OF_CONDUCT.md](https://github.com/okyanu/pomona/blob/main/CODE_OF_CONDUCT.md) | Community standards |
| [HF_USAGE.md](./HF_USAGE.md) | **Why stub default + how to use HF model** |
| [GETTING_STARTED.md](./GETTING_STARTED.md) | Quick run + expectations |
| [PROJECT_STATUS.md](./PROJECT_STATUS.md) | What's done / current phase |
| [NEXT_MODELS_AND_HF.md](./NEXT_MODELS_AND_HF.md) | Sequenced next steps for models / Hugging Face |
| [REPOS.md](./REPOS.md) | Platform vs ML vs Hugging Face |
| [GitHub Wiki](https://github.com/okyanu/pomona/wiki) | Reader-friendly summaries linking back here |

## Architecture & roadmap

| Doc | Purpose |
|-----|---------|
| [PHASES.md](./PHASES.md) | **Phase tracker — update when phases complete** |
| [ROADMAP.md](./ROADMAP.md) | Roadmap summary + Hugging Face links |
| [VERSIONING.md](./VERSIONING.md) | Platform, model, dataset, and lifecycle version rules |
| [architecture.md](./architecture.md) | Architecture (short) |
| [SMALL_MODEL_FACTORY.md](./SMALL_MODEL_FACTORY.md) | Repeatable pipeline for narrow specialist models |
| [TOMATO_RISK_REASONER.md](./TOMATO_RISK_REASONER.md) | First tomato risk reasoner notes |
| [SAFETY_TRIAGE_REASONER.md](./SAFETY_TRIAGE_REASONER.md) | Planned safety triage small model |
| [SENSOR_QUALITY_REASONER.md](./SENSOR_QUALITY_REASONER.md) | Planned sensor quality small model |

## Later patterns (local design drafts)

Unimplemented design notes. Do not treat as phase commitments. Index:
[LATER_PATTERNS_BACKLOG.md](./LATER_PATTERNS_BACKLOG.md).

| Doc | Purpose |
|-----|---------|
| [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md) | Stuck / flatline / baseline-drift SQI (Plexus-style) |
| [CALIBRATION_PROVENANCE.md](./CALIBRATION_PROVENANCE.md) | Calibration events + tagged corrections (Hurst-style) |
| [ADVICE_CARDS.md](./ADVICE_CARDS.md) | HITL advice cards (CottonBot-style) |
| [DIGITAL_TWIN.md](./DIGITAL_TWIN.md) | Advisory calibrate → estimate twin (Frontzek-style) |
| [LOCAL_ADVICE_RETRIEVAL.md](./LOCAL_ADVICE_RETRIEVAL.md) | Offline exact-excerpt retrieval prototype |
| [WATERCRESS_PILOT.md](./WATERCRESS_PILOT.md) | Two-zone watercress monitoring pilot (SD logger + importer) |

## Maintainer-only (local, not in Git)

Private experiments, raw data notes, adapter zips, publish checklists, and internal ML run logs live on the maintainer machine under `private/` and other gitignored paths. They are not part of the public GitHub repo.
