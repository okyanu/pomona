# Phases

**Platform version: `v0.1.0-alpha.1`** · **Total: 11 phases (Phase 0 → Phase 10)**

| | Count |
|---|-------|
| ✅ Completed | **2** (Phase 0, Phase 1) |
| ⏳ Active / partial | **6** (Phases 2, 3, 4, 5, 9, 10) |
| ⬜ Remaining | **3** (Phases 6–8) |

> **Source of truth for phase status.** When a phase finishes, update this file first, then [ROADMAP.md](./ROADMAP.md), [PROJECT_STATUS.md](./PROJECT_STATUS.md), and [README.md](../README.md).

---

## Status table

| Phase | Name | Status |
|-------|------|--------|
| **0** | Project setup & open source | ✅ Done |
| **1** | Local MVP (Docker, core, simulator) | ✅ Done |
| **2** | Dashboard + database | ⏳ **In progress** |
| **3** | Tomato greenhouse reasoner | ⏳ Partial — HF adapter + deterministic/API route; runtime LoRA wiring pending |
| **4** | Safety checker | ⏳ Partial — deterministic tomato and actuator gates implemented; full chain pending |
| **5** | Agronomist LLM adapter | ⏳ Partial — HF adapter + model-router contract; live backend wiring pending |
| **6** | Automation engine | ⬜ Planned |
| **7** | Public browser demo | ⬜ Planned |
| **8** | ESP32 / real devices | ⬜ Planned |
| **9** | Model registry standard | ⏳ Partial — public YAML registry and HF lifecycle metadata |
| **10** | Fine-tune pipeline | ⏳ Partial — dataset builders, validators, Colab training, and clean evaluation |

**Legend:** ✅ Done · ⏳ Active or partial · ⬜ Planned

Phase status measures product completion. It is intentionally separate from
platform and model versions; see [VERSIONING.md](./VERSIONING.md).

---

## What works after Phase 1

- `./scripts/up.sh` — MQTT + core + model-router
- `./scripts/sim.sh` — greenhouse sensor simulator
- REST API + demo advisor (stub)

**Next milestone (Phase 2):** Web dashboard + SQLite persistence.

---

## When you complete a phase — update these files

1. **`docs/PHASES.md`** (this file) — change ⬜/⏳ to ✅, set next phase to ⏳
2. **`docs/ROADMAP.md`** — sync the status column
3. **`docs/PROJECT_STATUS.md`** — add deliverables + completion date
4. **`README.md`** — sync the phase table under "Project phases"
5. **`private/DAILY_LOG.md`** — optional personal note (local only)

Partial progress: use "⏳ partial" in PHASES + note in PROJECT_STATUS only.

Detailed deliverables (maintainer): `private/planning/ROADMAP.full.md`
