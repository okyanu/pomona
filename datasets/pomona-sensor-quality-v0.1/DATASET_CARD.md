# Pomona Sensor Quality v0.1 Dataset Card

## Summary

This dataset scaffold supports a small Pomona specialist model that classifies whether farm sensor input is complete, plausible, stale, conflicting, or needs human review.

## Intended Use

- preflight sensor quality checks,
- missing-data detection,
- impossible reading detection,
- sensor drift or unit mismatch warnings,
- safe next-check generation before risk or safety reasoning.

## Not Intended For

- direct actuator control,
- crop disease diagnosis,
- pesticide or fertigation decisions,
- replacing deterministic validation rules.

## Status

Seed scaffold plus local generated training builder. Not trained or published yet.

Default generated split:

```text
records=2112
train=1692
validation=210
test=210
```

Generated split files live under `datasets/processed/` and are not committed to GitHub.

## License

Pomona-authored examples are Apache-2.0 unless otherwise stated.
