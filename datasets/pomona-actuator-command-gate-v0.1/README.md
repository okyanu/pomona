# Pomona Actuator Command Gate v0.1

Small generated dataset scaffold for Pomona's actuator command gate reasoner.

Task:

```text
farm context + proposed command + sensor/risk context
  -> command decision JSON
```

This dataset is generated from deterministic Pomona safety templates. It is intended for a narrow LoRA adapter that classifies proposed actions as `allowed`, `blocked`, or `needs_human_approval`.

The model is advisory only. Deterministic safety-checker rules are the final authority.

## Files

```text
schema/input.schema.json
schema/output.schema.json
schema/labels.schema.json
data/samples.jsonl
data/eval_cases.jsonl
```

Generated train/validation/test splits live under `datasets/processed/` and are ignored by Git.
