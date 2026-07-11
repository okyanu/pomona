# Dataset Card: Pomona Tomato Risk v0.1

## Dataset Summary

Pomona Tomato Risk v0.1 is a compact JSONL dataset for tomato greenhouse risk reasoning. It is designed to train and evaluate small agriculture reasoners that identify risk, request missing measurements, and block unsafe recommendations.

## Intended Use

- Prototype greenhouse tomato risk classifiers.
- Evaluate safe next-check behavior under missing or conflicting sensor data.
- Support future compact VibeThinker-style Pomona reasoners.

## Not Intended For

- Direct pesticide dosage.
- Autonomous fertigation changes.
- Direct actuator control.
- Definitive disease diagnosis.
- Production agronomy decisions without human review.

## Data Fields

Each record contains:

- `id`
- `source_id`
- `input`
- `expected_output`
- `notes`

## Safety

Unsafe operational recommendations are represented as `blocked_actions`. Examples requiring expert review set `human_review_required` to `true`.

## Sources

Active v0.1 source registry entries:

- `udea_greenhouse_tomato` — CC BY 4.0; greenhouse tomato environmental and crop measurements
- `4tu_autonomous_greenhouse_challenge` — CC BY 4.0; dwarf tomato greenhouse climate/control timeseries
- `pomona_handwritten_eval_cases` — Apache-2.0; Pomona-authored seed and eval records
- `pomona_generated_normal_calibration` — Apache-2.0; generated no-risk calibration rows derived from safe-range variations of clean normalized records

Raw third-party files are not included in this release. Published train/validation/test files contain normalized inputs and rule-derived Pomona labels.

The generated train/validation/test files are normal-first for local v0.1.2 training, with roughly 60% routine no-risk greenhouse states and 40% risk states. Risk labels and blocked actions are derived from Pomona's deterministic tomato safety-rule baseline so small models learn the same safety boundary enforced in code.

## Splits

- `data/train.jsonl`
- `data/validation.jsonl`
- `data/test.jsonl`
- `data/samples.jsonl`
- `data/eval_cases.jsonl`
- `data/golden_eval.jsonl`

The train/validation/test split files are generated from local processed artifacts and published only to the Hugging Face dataset repo, not committed to the Pomona GitHub repo.

`golden_eval.jsonl` is a small hand-curated safety regression suite intended for rules and model adapters. It focuses on normal/no-risk states, pH/EC risks, temperature risks, fungal pressure, missing data, sensor anomalies, water risk, and actuator conflicts.

## Licensing

Pomona-generated schema, examples, and documentation are Apache-2.0. Third-party derived labels follow CC BY 4.0 with required attribution. See `LICENSES.md` for source-specific notes.
