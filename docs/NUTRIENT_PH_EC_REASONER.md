# Pomona Nutrient / pH-EC Reasoner

The Nutrient / pH-EC Reasoner is a deterministic-first scaffold for hydroponic
and greenhouse substrate readings. It identifies pH/EC boundary risks and
missing data, then proposes verification steps.

Endpoint:

```text
POST /v1/reasoners/nutrient-ph-ec
```

It returns `nutrient_risk_labels`, missing fields, safe checks, blocked actions,
and a human-review flag. Any pH/EC risk blocks
`autonomous_fertigation_change`. The endpoint is advisory only; it never doses
nutrients, changes pH/EC, or controls equipment.

Current labels:

```text
high_ph, low_ph, high_ec, low_ec, nutrient_uptake_issue,
sensor_anomaly, missing_critical_data
```

This is a rules scaffold, not a trained model and not evidence of real-world
agronomic efficacy. A dataset and model should be created only after the rule
thresholds and independent evaluation cases are reviewed.

## Try the published GGUF locally with Ollama

The trained LoRA is also published as a GGUF, pullable directly from Hugging
Face without any local build step:

```bash
ollama pull hf.co/Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-GGUF
```

Verified on a clean pull (2026-08-22): **994 MB download**, roughly 8.5
minutes on a ~2 MB/s connection, **~1.1 GB RAM** while loaded (Ollama reported
100% GPU offload on Apple Silicon), and well under 2 seconds per inference
once loaded.

Model-only output is not guaranteed schema-perfect. In one verified test
run, the raw model added an unexpected top-level key instead of using
`nutrient_risk_labels`, and `missing_fields` incorrectly listed a field the
model itself had just populated. This is exactly why Pomona never exposes
model-only output directly: `POST /v1/reasoners/nutrient-ph-ec` always
validates and corrects through the deterministic rules layer before a
response is guarded and returned.
