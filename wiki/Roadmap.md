# Roadmap

**Platform `v0.1.0-alpha.1`** · **11 phases (0–10)** · **2 done** · **8 active/partial** (synced from docs/ROADMAP.md, 2026-11-07)

Phase status tracks product completion; it is intentionally separate from
platform/model version numbers — see [Versioning](https://github.com/okyanu/pomona/blob/main/docs/VERSIONING.md).

| # | Focus | Status |
|---|--------|--------|
| 0 | Project setup & open source | ✅ |
| 1 | Local MVP (Docker, core, simulator) | ✅ |
| 2 | Dashboard + persistence | ⏳ partial — local SQLite, dashboard, Docker validation done; hardening remains |
| 3 | Tomato reasoner | ⏳ partial — [HF LoRA](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) published but experimental (learned a training shortcut); deterministic rules decide |
| 3b | Water/irrigation reasoner | ⏳ partial — [v0.1.8 release candidate](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) published (synthetic evaluation only); guarded platform wiring verified locally |
| 4 | Safety checker | ⏳ partial — deterministic tomato and actuator gates implemented |
| 5 | LLM advisor | ⏳ partial — adapter and router contract exist; live wiring pending |
| 6 | Automation (suggestions) | ⏳ partial — YAML rules, suggestions, manual approve/reject |
| 7 | Public browser demo | ⏳ partial — [static guarded demo](https://huggingface.co/spaces/Okyanus/pomona-greenhouse-demo) and [Try to fool Pomona](https://huggingface.co/spaces/Okyanus/try-to-fool-pomona) live |
| 8 | ESP32 devices | ⬜ — logger firmware compiles; not yet bench-tested, no field data |
| 9 | Model registry | ⏳ partial — `models/registry/` |
| 10 | Train reasoner models | ⏳ partial — small LoRAs on HF; evaluations so far are on generated data |

## Next integration work

```text
POST /v1/reasoners/safety-triage
POST /v1/actuator-command-gate/check
```

## Future model families

- Strawberry risk reasoner
- Lettuce risk reasoner

## Details

Full phase tracker with update rules: [docs/PHASES.md](https://github.com/okyanu/pomona/blob/main/docs/PHASES.md) · [docs/PROJECT_STATUS.md](https://github.com/okyanu/pomona/blob/main/docs/PROJECT_STATUS.md)
