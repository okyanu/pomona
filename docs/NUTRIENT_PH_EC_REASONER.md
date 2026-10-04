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

## Real commercial lab data check (2026-10-04)

`scripts/datasets/build_nutrient_cases_from_agc2.py` turns the 60 lab analyses of the Wageningen
Autonomous Greenhouse Challenge, 2nd edition (cherry tomato on rockwool, CC0; local raw files, see
`datasets/sources/4tu_agc2_cherry_tomato.yaml`) into 120 candidate cases (feed and drain of each
sample) in `datasets/interim/agc2_nutrient_candidate_cases.jsonl` (gitignored). Expected output is
what the deterministic rules say today.

The rules flag 78 of 120 (low_ph 47, high_ec 50, high_ph 1). In 55 of those, the label contradicts
usual commercial practice, so the cases are marked `needs_owner_review` and are not in the
committed eval set:

- **Feed pH 5.0-5.3 reads as `low_ph` (16 cases).** Rockwool feed solution is normally run around
  pH 5.0-5.5.
- **Drain EC 4.5-6.5 mS/cm reads as `high_ec` (39 cases).** Growers push root-zone salinity on
  purpose for fruit quality; drain EC runs above feed EC.

Takeaway: the thresholds (pH <= 5.3 low, EC >= 4.5 high) fit a general or hobby hydroponic
reservoir, not a commercial rockwool drain. Because the rules block fertigation changes whenever
a label is present, these flags would raise review requests on a normal crop. If Pomona is meant to
cover rockwool or substrate tomato, give it a solution-type-specific range (feed vs drain) instead
of changing the shared thresholds. Not changed: owner decision.
