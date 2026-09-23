# What's next — models, Hugging Face, and platform

Local note for sequencing after the 2026-09-23 pattern work. Not a release
authorization. Weights stay on Hugging Face; platform code stays on GitHub.

## Do next (trust / models) — higher priority than new HF uploads

1. **Sensor-quality training notebook** — render prompts from raw JSONL
   (`scripts/datasets/sensor_quality_contract.render_prompt`), not from
   `datasets.load_dataset` rows. **Local Colab notebooks updated 2026-09-23**
   (pilot, boundary, prepared-train). Then one combined retrain (omitted keys +
   graded pH + temporal labels if you choose to teach them) — owner GPU step.
2. **Evaluate unpublished SQI adapters** on the frozen 2026-09-16 reviewed
   bundle / neutral holdout before any HF publish. Deterministic rules remain
   the live gate until a model beats them on stuck/baseline cases.
3. **Tomato / water runtimes** — keep guarded Ollama/GGUF paths; improve tomato
   checkpoint quality (Phase 3) before expanding Agronomist live wiring
   (Phase 5).

## Hugging Face — when (not yet)

| Artifact | Status | Next HF action |
|----------|--------|----------------|
| Water irrigation v0.1.8 | Published RC | None unless a regression fix ships |
| Tomato risk v0.1.7 | Published | Quality hardening first; no blind re-upload |
| Nutrient pH-EC | Published + GGUF/MLX | Runtime eval only unless labels change |
| Sensor quality | Local only | Publish only after notebook fix + holdout pass + owner approve |
| Safety triage | Local only | Same bar as SQI |
| Greenhouse demo Space | Live | Optional: surface advice-card copy later |

Publishing still requires `make publish-check` and explicit owner upload approval
([PUBLISHING.md](./PUBLISHING.md), [MODEL_CATALOG.md](./MODEL_CATALOG.md)).

## Platform — after commit (if you choose)

- Commit the local pattern + follow-on work when ready.
- Optional: broker reconnect/soak, suggestion supersession polish.
- Phase 8 ESP32 remains later; no actuator autonomy.

## Explicitly not next

- ThingsBoard / MPC / LLM valve control.
- Uploading SQI or safety-triage weights without a fresh eval.
- Training on zone-ID-leaky or loader-normalized prompts.
