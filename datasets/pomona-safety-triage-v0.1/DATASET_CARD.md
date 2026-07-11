# Pomona Safety Triage v0.1 Dataset Card

## Summary

This dataset scaffold supports a planned Pomona small specialist model for safety triage. It classifies whether a proposed farm action is safe, blocked, or requires human review.

## Intended Use

Use for early prototyping of:

- action safety classification,
- blocked-action detection,
- safe alternative generation,
- human review requirement detection.

## Not Intended For

- autonomous actuator control,
- pesticide dosage recommendations,
- definitive disease diagnosis,
- replacing human agronomist review,
- production safety approval without deterministic checks.

## Status

Local generated training set available. Not trained or published yet.

Default generated split:

```text
records=2011
train=1609
validation=201
test=201
```

Build and validate locally:

```bash
python3 scripts/datasets/build_pomona_safety_triage_dataset.py
python3 scripts/datasets/validate_pomona_safety_triage_dataset.py \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/all_records.jsonl \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/train.jsonl \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/validation.jsonl \
  --jsonl datasets/processed/pomona-safety-triage-v0.1/test.jsonl
```

Generated split files live under `datasets/processed/` and are not committed to GitHub.

## Limitations

- Generated examples are template-derived and should be treated as first-pass synthetic training data.
- Not trained yet.
- Requires deterministic safety checker as final gate.
- Not a pesticide, chemical, fertigation, or actuator-control authority.

## License

Pomona-authored examples are Apache-2.0 unless otherwise stated.
