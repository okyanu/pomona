# Annotation Guide

Each record should be compact, evidence-based, and safety-bounded.

## Required Shape

```json
{
  "id": "sample-0001",
  "source_id": "manual_seed",
  "input": {},
  "expected_output": {},
  "notes": "Short rationale."
}
```

## Rules

- Use `null` for unknown sensor values instead of inventing measurements.
- Add missing fields to `missing_data`.
- Prefer safe checks such as recalibration, scouting, repeat measurement, and human review.
- Add blocked actions whenever the example might tempt an unsafe recommendation.
- Never encode direct actuator commands as the correct output.
- Never encode definitive disease diagnosis as the correct output.
