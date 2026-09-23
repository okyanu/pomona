# Sensor Quality Reasoner: input contract

This defines the one input format that training data, evaluation, and the
deployed deterministic fallback (`services/model-router/app/sensor_quality.py`)
must agree on. It exists because the 2026-09-07 paired diagnostic
(`private/SENSOR_QUALITY_PAIRED_RESULTS_2026_09_07.md`) found the historical
training/evaluation pipeline silently violated it in two ways: the training
data never demonstrated one of the two missing-value forms the system prompt
promises to treat equivalently, and the `datasets` library reformatted
records before they were turned into prompts, invalidating a prior
omitted-vs-null comparison. This document does not itself change any
training data, adapter, or deployed behavior.

## Canonical serializer

Prompts must be built by `render_prompt()` in
`scripts/datasets/sensor_quality_contract.py`, which renders one record's raw
`input` dict (decoded straight from a JSONL line via `json.loads`, never
through `datasets.load_dataset` or pandas) as:

```
<|im_start|>system
{SYSTEM_PROMPT}
<|im_end|>
<|im_start|>user
Classify this farm sensor packet for data quality.
{json.dumps(user, separators=(",", ":"), sort_keys=True, default=str)}
<|im_end|>
<|im_start|>assistant
```

`user` is the four top-level keys (`farm_context`, `sensor`,
`expected_fields`, `current_time`), each defaulted only if the *top-level*
key itself is absent from `input`. Sub-fields inside `farm_context`/`sensor`
are never defaulted -- they pass through omitted or present exactly as given.
`sort_keys=True` makes prompt text independent of dict key order; there is no
other normalization.

This module was extracted from, and is verified against,
`private/colab/sensor_quality_paired_diagnostic.py`'s `render()` (itself
audited against `pomona_sensor_quality_verified_baseline_eval.ipynb`'s
`SYSTEM_PROMPT`, hash `74dab26c...4f9ace4`). Any notebook that builds
sensor-quality prompts should match this module byte-for-byte; the checked-in
hash constant (`SYSTEM_PROMPT_SHA256`) and `scripts/datasets/tests/test_sensor_quality_contract.py`
catch silent drift between them.

## Timestamps

Canonical format is second-precision UTC ISO 8601 with a literal `Z`
suffix: `YYYY-MM-DDTHH:MM:SSZ` (see `iso()` in
`scripts/datasets/build_pomona_sensor_quality_dataset.py`). The deployed
parser (`parse_timestamp` in `services/model-router/app/sensor_quality.py`)
is more permissive -- it also accepts a `+00:00` offset in place of `Z` -- but
training and evaluation data should always use the canonical `Z` form so
staleness examples aren't confounded by timestamp-format variation.

`current_time` and `sensor.timestamp` must both use this exact format.
Never pass either field through `datasets`/pandas before rendering: loading
`.jsonl` through `datasets.load_dataset` reformats ISO timestamps to a
space-separated string with no explicit timezone, which is a different string
the model was never trained or evaluated on for that field.

## Missing values: omitted key vs. explicit null

**These two forms must be treated identically by any consumer, and training
data must demonstrate both.**

- *Explicit null*: `sensor["ph"] = None` -- the key is present with value `null`.
- *Truly omitted*: `"ph"` is absent from `sensor` entirely.

The system prompt already states this equivalence ("If required pH, EC, air
temperature, humidity, or moisture is null/**missing**, use the matching
missing label"), and the deployed rules fallback implements it that way
(`sensor.get(field) is None` returns `None` for both an absent key and an
explicit `null`). But `scripts/datasets/build_pomona_sensor_quality_dataset.py`'s
`generated_records()` only ever produces the null form (`sensor["ph"] = None`,
never `del sensor["ph"]`) -- confirmed by
`scripts/datasets/check_sensor_quality_omission_coverage.py`, which finds 704
null-form missing-field examples and 0 omitted-form examples in the current
processed dataset. The 2026-09-07 paired diagnostic found both v0.1.2 and
v0.1.3 pass 5/5 null-form cases but fail 0/5 omitted-form cases. A model never
shown the omitted form during training has no basis to generalize the
system prompt's stated equivalence to it; this is the most likely explanation
for that split and does not require assuming any deeper capability failure.

Any future training data revision for this reasoner should add omitted-key
variants alongside the existing null variants for every field in
`FIELD_LABELS` (`services/model-router/app/sensor_quality.py`), not replace
one form with the other -- production sensor feeds may legitimately produce
either form, and the deployed contract must keep treating them the same.

## Required fields and defaults

Same list the deployed fallback checks against `expected_fields`:
`air_temperature_c`, `humidity_pct`, `ph`, `ec_ms_cm`, and
`substrate_moisture_pct` when the system type is `greenhouse_substrate` or
`soil_field` (see `base_input()` in `build_pomona_sensor_quality_dataset.py`
and `FIELD_LABELS` in `sensor_quality.py`). `expected_fields` itself is part
of the input, not inferred from `system_type`, in both training data and the
deployed contract -- do not have one side infer it and the other read it
explicitly.

## What this contract does not resolve

- Whether raw-vs-`datasets`-normalized *training* prompts (as opposed to
  evaluation prompts, which this contract now pins) affected the adapters
  that were actually trained -- unresolved per
  `private/SENSOR_QUALITY_PAIRED_RESULTS_2026_09_07.md`.
- Any release or retraining decision. No dataset, adapter, or deployed
  behavior changes as a result of this document; see
  `private/AGENT_HANDOFF.md` for outstanding boundaries.
