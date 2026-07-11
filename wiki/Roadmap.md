# Roadmap

**Platform `v0.1.0-alpha.1`** · **11 phases (0–10)** · **2 done** · **6 active/partial**

Phase status tracks product completion; it is intentionally separate from
platform/model version numbers — see [Versioning](https://github.com/Okyanus/pomona/blob/main/docs/VERSIONING.md).

| # | Focus | Status |
|---|--------|--------|
| 0 | Project setup & open source | ✅ |
| 1 | Local MVP (Docker, core, simulator) | ✅ |
| 2 | Dashboard + persistence | ⏳ **now** |
| 3 | Tomato reasoner | ⏳ partial — [HF LoRA](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora) published; platform wiring pending |
| 3b | Water/irrigation reasoner | ⏳ partial — [v0.1.8 release candidate](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora) published; platform wiring pending |
| 4 | Safety checker | ⏳ partial — deterministic tomato and actuator gates implemented |
| 5 | LLM advisor | ⏳ partial — adapter and router contract exist; live wiring pending |
| 6 | Automation (suggestions) | ⬜ |
| 7 | Public browser demo | ⬜ |
| 8 | ESP32 devices | ⬜ |
| 9 | Model registry | ⏳ partial — `models/registry/` |
| 10 | Train reasoner models | ⏳ partial — v0.1.7 LoRA on HF |

## Next integration work

```text
POST /v1/reasoners/safety-triage
POST /v1/actuator-command-gate/check
```

## Future model families

- Nutrient / pH-EC reasoner
- Strawberry risk reasoner
- Lettuce risk reasoner

## Details

Full phase tracker with update rules: [docs/PHASES.md](https://github.com/Okyanus/pomona/blob/main/docs/PHASES.md) · [docs/PROJECT_STATUS.md](https://github.com/Okyanus/pomona/blob/main/docs/PROJECT_STATUS.md) · [docs/EXECUTION_PLAN.md](https://github.com/Okyanus/pomona/blob/main/docs/EXECUTION_PLAN.md)
