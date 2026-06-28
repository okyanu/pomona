# Phases

**Total: 11 phases (Phase 0 → Phase 10)**

| | Count |
|---|-------|
| ✅ Completed | **2** (Phase 0, Phase 1) |
| ⏳ In progress | **1** (Phase 2) |
| ⬜ Remaining | **8** (Phases 3–10) |

> **Source of truth for phase status.** When a phase finishes, update this file first, then [ROADMAP.md](./ROADMAP.md), [PROJECT_STATUS.md](./PROJECT_STATUS.md), and [README.md](../README.md).

---

## Status table

| Phase | Name | Status |
|-------|------|--------|
| **0** | Project setup & open source | ✅ Done |
| **1** | Local MVP (Docker, core, simulator) | ✅ Done |
| **2** | Dashboard + database | ⏳ **In progress** |
| **3** | Tomato greenhouse reasoner | ⬜ Planned |
| **4** | Safety checker | ⬜ Planned |
| **5** | Agronomist LLM adapter | ⬜ Planned (partial: model-router stub/HF) |
| **6** | Automation engine | ⬜ Planned |
| **7** | Public browser demo | ⬜ Planned |
| **8** | ESP32 / real devices | ⬜ Planned |
| **9** | Model registry standard | ⬜ Planned (partial: `models/registry/`) |
| **10** | Fine-tune pipeline | ⬜ Planned (ML repo) |

**Legend:** ✅ Done · ⏳ In progress · ⬜ Planned

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
