# Pomona Safety Triage v0.1

Dataset scaffold for a planned small safety-triage reasoner.

Task:

```text
farm context + sensor state + risk labels + proposed action
  -> safety labels + blocked actions + safe alternative
```

This dataset contains the public seed scaffold. Generated training splits are built locally under
`datasets/processed/pomona-safety-triage-v0.1/` and are ignored by Git.

Validate:

```bash
python3 scripts/datasets/validate_pomona_safety_triage_dataset.py
```

Build local training splits:

```bash
python3 scripts/datasets/build_pomona_safety_triage_dataset.py
```

Validate generated splits:

```bash
python3 scripts/datasets/validate_pomona_safety_triage_dataset.py \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/all_records.jsonl \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/train.jsonl \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/validation.jsonl \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/test.jsonl
```

Default generated split size:

```text
train=1609 validation=201 test=201
```

The generated data is template-derived for first-pass LoRA training. It must be evaluated against
held-out safety cases before any Hugging Face model upload.
