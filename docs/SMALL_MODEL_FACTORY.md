# Pomona Small Model Factory

This document captures the first Pomona small-purpose model checkpoint and the repeatable pipeline for future compact reasoners.

The goal is not one huge agriculture LLM. Pomona should be able to create many small task-specific models, each wrapped by deterministic agronomy and safety rules.

## Core Pattern

```text
define narrow task
  -> build normalized JSONL dataset
  -> define strict input/output schema
  -> train small adapter
  -> evaluate model-only
  -> add deterministic rule checker
  -> evaluate hybrid system
  -> publish dataset/model only when useful
```

For the first checkpoint:

```text
Task: tomato greenhouse sensor JSON -> risk label JSON list
Base model: Qwen/Qwen2.5-0.5B-Instruct
Best adapter: v0.1.7-risk-label-list-normalfix
Best practical system: v0.1.7 adapter + deterministic tomato rules
```

## Why This Matters

The small model learned useful task behavior, but strict threshold reasoning was imperfect. The deterministic rule checker corrected missing data, impossible sensor readings, water risk, fungal pressure, and actuator conflicts.

This is the Pomona thesis pattern:

```text
small local model = flexible task reasoner
deterministic rules = safety and agronomy guardrails
hybrid output = usable system behavior
```

Do not let any model directly control actuators. The model advises or classifies; hard safety logic gates downstream action.

## Reusable Repo Structure

Use the same shape for future small models:

```text
datasets/
  sources/*.yaml              source/license registry
  raw/                        local raw files only, gitignored
  interim/                    normalized local files, gitignored
  processed/                  generated train/validation/test, gitignored
  <dataset-name>/
    README.md
    DATASET_CARD.md
    LICENSES.md
    CITATION.cff
    schema/
    data/
    docs/

scripts/datasets/
  normalize_<source>.py
  build_<dataset>.py
  validate_<dataset>.py
  split_dataset.py

private/colab/                local training notebooks, adapters, test zips
services/safety-checker/      deterministic rule guardrails
services/model-router/        future model routing/inference API path
```

## First Model Checkpoint

Current best standalone adapter:

```text
private/colab/adapters/v0.1.7-risk-label-list-normalfix.zip
```

Do not treat it as production-safe by itself. It is the best experimental adapter from this run.

Observed model-only scores:

```text
v0.1.7 staged risk F1: 0.924 on its original staged test
v0.1.7 golden risk F1: 0.667
```

Hybrid guarded scores from `evaluate_hybrid_tomato_reasoner.py`:

```text
golden eval:
  model-only risk F1: 0.667
  hybrid risk F1:     1.000
  corrections:        5 / 15

v0.1.7 staged test:
  model-only risk F1: 0.902
  hybrid risk F1:     1.000
  corrections:        59 / 473
```

The perfect hybrid score is expected because this eval set is rule-derived. For future real-world validation, keep a separate human-reviewed eval set.

## Training Iteration Lessons

What worked:

- Narrow output format: bare JSON list of risk labels.
- Small, explicit label vocabulary.
- Hand-written golden eval cases.
- Boundary examples around pH, EC, temperature, humidity, moisture, and actuator states.
- Deterministic rule checker for safety-critical labels.

What did not work well:

- Asking the 0.5B model to reliably learn every hard threshold.
- Repeatedly patching the dataset after each failure without adding a guardrail layer.
- Treating model-only score as the final product score.

Recommendation:

```text
Train small adapters for flexible task behavior.
Use deterministic code for exact thresholds and safety boundaries.
Evaluate both model-only and hybrid outputs.
```

## Future Model Workflow

For each new small Pomona model:

1. Pick one narrow task.

Examples:

```text
sensor JSON -> climate anomaly labels
sensor JSON -> irrigation risk labels
sensor JSON -> safe next-check suggestions
sensor JSON -> disease observation triage
sensor JSON -> dashboard explanation text
```

2. Define the schema.

Keep input and output strict. Prefer JSON objects or JSON lists. Avoid open-ended prose unless the task is explanation generation.

3. Register sources and licenses.

Add one YAML per source under `datasets/sources/`:

```yaml
id:
name:
url:
doi:
license:
allowed_use:
redistribution_notes:
attribution_required:
status:
```

Do not download or commit raw data until the license is clear.

4. Normalize data.

Raw files stay local:

```text
datasets/raw/
datasets/interim/
datasets/processed/
```

These must stay gitignored unless a file is intentionally tiny and publishable.

5. Build teacher labels.

For safety-critical labels, implement deterministic teacher rules first. Then generate JSONL.

6. Create golden eval.

Golden eval must include:

- normal cases,
- each single label,
- important combined labels,
- missing-data cases,
- sensor-anomaly cases,
- boundary near-misses,
- unsafe action cases if applicable.

7. Train adapter.

Use the Colab notebook pattern in `private/colab/`. Update:

```text
dataset zip
task prompt
output adapter name
base model if needed
```

Every new training notebook should be modifiable without rewriting the whole notebook. Put these values near the top:

```text
BASE_MODEL
OUTPUT_DIR
DATASET_ZIP_NAME
SYSTEM_PROMPT
ALLOWED_LABELS
MAX_LENGTH
NUM_TRAIN_EPOCHS
LORA_R
LORA_ALPHA
```

Recommended local naming:

```text
private/colab/pomona_<model_name>_v0_1_colab.ipynb
private/colab/pomona-<dataset-name>-v0.1-training-data.zip
private/colab/adapters/<model-name>-v0.1-local.zip
```

8. Evaluate.

Always compare:

```text
model-only
rules-only
hybrid-guarded
```

For the tomato-risk checkpoint:

```bash
cd ~/Desktop/pomona

./private/colab/test_hybrid_v0_1_7_reasoner.sh

SPLIT=test LIMIT=473 SUMMARY_ONLY=1 ./private/colab/test_hybrid_v0_1_7_reasoner.sh
```

9. Decide publishability.

Publish only when the model card can honestly say:

- what the model does,
- what it does not do,
- what base model it uses,
- what dataset it was trained on,
- model-only eval score,
- hybrid eval score,
- required safety guardrails,
- no autonomous actuator or chemical decisions.

## Hugging Face Guidance

Weights/adapters belong on Hugging Face, not GitHub.

Recommended model repo for the current best adapter:

```text
Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora
```

Recommended dataset repo for the clean dataset artifact:

```text
Okyanus/greenhouse-sensor-data
```

Model card must say this is experimental and should be used with Pomona deterministic safety rules.

## Checklist For The Next Small Model

- [ ] Task is narrow and useful.
- [ ] Inputs and outputs are strict JSON.
- [ ] Endpoint contract exists before training starts.
- [ ] Sources have license metadata.
- [ ] Raw data is local only and gitignored.
- [ ] Dataset has train/validation/test/golden eval.
- [ ] Validation script exists.
- [ ] Modifiable Colab training notebook output name is versioned.
- [ ] Local adapter test exists.
- [ ] Deterministic safety/rule checker exists.
- [ ] Hybrid evaluator compares model-only, rules-only, and hybrid.
- [ ] Model card documents limitations and safety boundaries.
- [ ] No weights, raw datasets, or Hugging Face repos are committed to GitHub.

## Endpoint Contract Pattern

Each small model should have a clear service contract before it becomes product work.

Recommended request shape:

```json
{
  "farm_id": "demo-farm",
  "zone_id": "greenhouse-a",
  "mode": "hybrid_guarded",
  "input": {},
  "context": {}
}
```

Recommended response shape:

```json
{
  "model_id": "pomona-example-reasoner-v0.1",
  "mode": "hybrid_guarded",
  "labels": [],
  "missing_data": [],
  "safe_next_checks": [],
  "blocked_actions": [],
  "human_review_required": false,
  "model_output": {},
  "rule_output": {},
  "final_output": {}
}
```

Service routing target:

```text
services/model-router/
  POST /v1/reasoners/<reasoner-name>

services/safety-checker/
  deterministic final authority for blocked actions and actuator gates
```

Never route small-model output directly to actuators. The API may return recommendations, classifications, and blocked/approval states only.

## Planned Model Roadmap

Near-term chain:

```text
sensor-quality reasoner
  -> tomato/crop risk reasoner
  -> safety-triage reasoner
  -> actuator-command gate
```

Next reusable specialist models:

```text
actuator command gate
  Checks whether a proposed action is safe, blocked, or needs human approval.

water / irrigation risk reasoner
  Checks water level, moisture, irrigation anomaly, dry/wet risk.

nutrient / pH-EC reasoner
  Checks hydroponic nutrient balance, pH/EC interpretation, and uptake issue.
```

Later expansion:

```text
strawberry risk reasoner
lettuce risk reasoner
aquaponic water chemistry reasoner
daily farm summary reasoner
digital twin scenario reasoner
```

Build order rule:

```text
Finish endpoint + evaluation + docs for the current model before starting the next model.
```

## Current Next Engineering Step

Move the hybrid tomato-risk reasoner from `private/colab/` into a service path:

```text
services/safety-checker/  for deterministic guardrail output
services/model-router/    for model inference and routing
```

The public API should expose guarded outputs. The model-only output can be kept for debugging/evaluation, but not used for direct decisions.
