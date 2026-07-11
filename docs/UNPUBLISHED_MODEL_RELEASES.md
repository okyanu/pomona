# Unpublished Model Release Control

This file controls promotion of Pomona's local specialist adapters. A model is
not publishable merely because it trains successfully or performs well on its
training dataset's generated test split.

## Common Release Requirements

Every candidate must have:

- zero exact input overlap between training and clean holdout data,
- valid JSON rate of `1.0`,
- required output fields rate of `1.0`,
- allowed labels/actions rate of `1.0`,
- no direct actuator authority,
- a documented base model, dataset version, prompt contract, and limitation,
- deterministic safety rules after model inference.

## Current Candidates

| Model | Candidate | Clean holdout | Publish gate | Current decision |
|---|---|---|---|---|
| Sensor quality | v0.1.1 boundary | 180 cases, 15 categories | label/missing/suspect F1 >= 0.90; review >= 0.95 | Needs targeted improvement; clean label F1 0.539 |
| Safety triage | v0.1 retained; v0.1.1 rejected | 128 adversarial cases, 8 categories | safety F1 >= 0.95; blocked/review = 1.0 | Needs targeted improvement; v0.1 clean safety F1 0.775 |
| Actuator command gate | v0.1 published research preview; v0.1.2 rejected | 126 cases, 9 categories | decision >= 0.95; gate F1 >= 0.90; blocked F1 = 1.0 | Public for transparent research only; deterministic gate final |
| Water/irrigation risk | v0.1.8 context/low lock | 392 leakage-free test cases plus 168-case external holdout | label F1 >= 0.90; blocked/review >= 0.95 | Published release candidate |

## Evaluation Artifacts

Local Colab artifacts are under `private/colab/` and are ignored by Git.

```text
pomona_sensor_quality_v0_1_1_clean_eval_colab.ipynb
pomona_safety_triage_v0_1_clean_eval_colab.ipynb
pomona_actuator_command_gate_v0_1_clean_eval_colab.ipynb
pomona_water_irrigation_risk_reasoner_v0_1_6_clean_holdout_full_eval_colab.ipynb
```

Each notebook is evaluation-only. It uploads one clean-holdout zip and one
adapter zip, runs the complete holdout, and reports per-category failures.

All three unpublished families can also be evaluated locally with one command.
The evaluator loads the Qwen base model once and swaps the selected LoRA
adapters:

```bash
private/venvs/pomona-model-test/bin/python \
  scripts/models/evaluate_unpublished_candidates.py \
  --per-bucket 0 \
  --device cpu \
  --output private/colab/outputs/unpublished_model_full_clean_eval.json
```

Use `--per-bucket 1` or `--per-bucket 3` for a faster balanced smoke test.
The full local report is private and ignored by Git.

## Promotion Decisions

Use one of these statuses:

- `clean_eval_pending`: trained adapter exists but independent evaluation is missing.
- `needs_targeted_improvement`: clean evaluation found specific weak categories.
- `release_candidate`: all numeric and schema gates pass; model card review remains.
- `rejected_regression`: a newer version is worse than the retained candidate.
- `published`: model card and adapter are on Hugging Face.

Do not average away a safety failure. A model with strong overall F1 but weak
blocked-action, human-review, or required-field behavior does not pass.
