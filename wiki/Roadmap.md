# Roadmap

**Platform `v0.1.0-alpha.1`** · **11 phases (0–10)** · **2 done** · **8 active/partial** (synced from docs/ROADMAP.md, 2026-11-07)

Phase status tracks product completion; it is intentionally separate from
platform/model version numbers — see [Versioning](https://github.com/okyanu/pomona/blob/main/docs/VERSIONING.md).

Phases 0 and 1 are done; phases 2, 3, 4, 5, 6, 7, 9 and 10 are partial (some pieces exist, which does not mean the phase is being worked on now); Phase 8 (ESP32 devices) is still planned: logger firmware compiles; not yet bench-tested, no field data. Local SQLite, dashboard and Docker validation are done for Phase 2; hardening remains. The published tomato adapter is experimental (it learned a training shortcut) and the deterministic rules decide; the water/irrigation v0.1.8 release candidate is published (synthetic evaluation only). The full phase table is in [docs/PHASES.md](https://github.com/okyanu/pomona/blob/main/docs/PHASES.md); the maintainer's current plan is in [docs/NEXT_90_DAYS.md](https://github.com/okyanu/pomona/blob/main/docs/NEXT_90_DAYS.md).

## Integration endpoints

All four exist in the platform: `POST /v1/reasoners/sensor-quality`, `/v1/reasoners/tomato-risk` and
`/v1/reasoners/safety-triage` (model-router; safety-triage uses a deterministic fallback, model runtime pending), and
`POST /v1/actuator-command-gate/check` (safety-checker; deterministic final authority). Still to do: wire the remaining
specialist model runtimes and improve tomato model-only quality.

## Future model families

- Strawberry risk reasoner
- Lettuce risk reasoner

## Details

Full phase tracker with update rules: [docs/PHASES.md](https://github.com/okyanu/pomona/blob/main/docs/PHASES.md) · [docs/PROJECT_STATUS.md](https://github.com/okyanu/pomona/blob/main/docs/PROJECT_STATUS.md)
