# Pomona Execution Plan

This is the practical timetable and AI-agent workflow for moving Pomona from the current checkpoint to a usable SaaS MVP with model routing, hybrid reasoners, and future small-model generation.

## Current Checkpoint

Completed or available now:

- Core Docker/MQTT/FastAPI skeleton.
- Sensor simulator.
- Model router stub/advisor path.
- Tomato risk dataset scaffold.
- Tomato risk LoRA on Hugging Face:
  - [Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- Water/irrigation LoRA release candidate:
  - [Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora](https://huggingface.co/Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora)
- Actuator-gate research preview:
  - [Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora](https://huggingface.co/Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora)
- Published greenhouse dataset on Hugging Face:
  - [Okyanus/greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)
- Hybrid local tomato reasoner:
  - small LoRA model output,
  - deterministic tomato rules,
  - guarded hybrid labels.
- Small-model factory documentation:
  - [SMALL_MODEL_FACTORY.md](./SMALL_MODEL_FACTORY.md)

Main product goal now:

```text
Turn the existing platform into a working SaaS-like local dashboard/API
that can ingest farm data, store it, route model/tool calls, apply safety,
and display guarded results.
```

## How To Use This File

This file is the active planning board for Codex, Cursor, and the human owner.

When the user asks "what next?", "continue", or "plan", assistants must read this file first and follow the highest-priority open item under [Active Task Board](#active-task-board).

Maintenance rules:

1. Keep active work in [Active Task Board](#active-task-board).
2. When an item is completed, remove it from the active board and add a dated entry to [Decision And Work Log](#decision-and-work-log).
3. When the user makes a product/architecture decision, add it to the log.
4. When the assistant makes a durable recommendation that the user accepts, add it to the log.
5. Do not use this file for private secrets, raw data paths outside approved local paths, tokens, or model weights.
6. Keep this file concise enough that future assistants can scan it quickly.

## Active Task Board

### Now

- [ ] Add `POST /v1/reasoners/safety-triage` in `services/model-router`.
- [ ] Keep `POST /v1/actuator-command-gate/check` in `services/safety-checker` as deterministic final authority.
- [ ] Start Phase 2 SQLite persistence in `services/core` after the first reasoner endpoint contract is stable.

### Next

- [ ] Build dashboard skeleton for latest farm/zone sensor readings.
- [ ] Add dashboard risk view for guarded labels, blocked actions, and safe checks.
- [ ] Add model-router endpoint contracts for the small-model chain:
  - safety triage,
  - actuator command gate advisory route if needed.

### Later

- [ ] Add big assistant explanation route using `ai-pomona-agronomist-gemma4`.
- [ ] Add digital twin v0 service/API contract.
- [ ] Apply the Pomona publishing schema to future Hugging Face model cards, dataset cards, and GitHub-facing docs when new artifacts are created.

### Current Model Checkpoint

Current active work is platform integration, not more training.

Use the current best local/published reasoners:

```text
tomato-risk: v0.1.7
water-irrigation-risk: v0.1.8 published release candidate
sensor-quality: v0.1.1-boundary
safety-triage: v0.1
actuator-command-gate: v0.1 published research preview + deterministic checker final authority
rejected: actuator-command-gate v0.1.1-hardcases and v0.1.2-correction
```

Do not start another nutrient or crop expansion model until the current chain is consumable through `model-router` and `safety-checker`. Water/irrigation v0.1.8 is now published; platform integration is the next step for that model family.

Reference task definitions:

```text
Pomona Sensor Quality Reasoner v0.1
input: farm context + sensor JSON + expected fields
output: data quality labels + missing fields + suspect fields + safe next checks + human_review_required + rationale
```

Reason:

```text
The next reusable model should check whether sensor data is complete, plausible,
stale, conflicting, or missing critical context before risk/safety models reason from it.
```

Scaffold:

```text
docs/SENSOR_QUALITY_REASONER.md
datasets/pomona-sensor-quality-v0.1/
models/registry/sensor-quality-reasoner-v0.1.yaml
scripts/datasets/build_pomona_sensor_quality_dataset.py
scripts/datasets/validate_pomona_sensor_quality_dataset.py
private/colab/pomona_sensor_quality_reasoner_v0_1_colab.ipynb
```

Current training target:

```text
Pomona Actuator Command Gate Reasoner v0.1
input: farm context + sensor quality + risk labels + actor + proposed command
output: decision + gate labels + blocked actions + safe alternatives + human_approval_required + rationale
```

Scaffold:

```text
docs/ACTUATOR_COMMAND_GATE_REASONER.md
datasets/pomona-actuator-command-gate-v0.1/
models/registry/actuator-command-gate-reasoner-v0.1.yaml
scripts/datasets/build_pomona_actuator_command_gate_dataset.py
scripts/datasets/validate_pomona_actuator_command_gate_dataset.py
private/colab/pomona_actuator_command_gate_reasoner_v0_1_colab.ipynb
```

### Planned Small-Model Sequence

Do not build these all at once. Build one model, connect it to an endpoint, test it, then continue.

#### 1. Sensor Quality Reasoner

Status: trained locally; current best candidate is `pomona-sensor-quality-reasoner-v0.1.1-boundary-lora.zip`.

Purpose:

```text
farm context + sensor JSON + expected fields
  -> missing fields, suspect fields, stale/conflicting/unit/drift labels
```

Endpoint target:

```text
POST /v1/reasoners/sensor-quality
```

#### 2. Actuator Command Gate

Purpose:

```text
proposed action + farm context + latest sensor/risk/safety state
  -> allowed | blocked | needs_human_approval
  -> blocked_actions + safe_alternatives + rationale
```

Why next:

```text
It protects the SaaS and automation path. Pomona models may advise, but this gate decides whether an action can even be suggested to a human.
```

Endpoint target:

```text
POST /v1/reasoners/actuator-command-gate
```

Hard rule:

```text
This model never directly controls actuators. Deterministic safety-checker logic must have final authority.
```

#### 3. Water / Irrigation Risk Reasoner

Purpose:

```text
sensor JSON + recent moisture/water/irrigation history
  -> dry risk, wet risk, irrigation anomaly, water-level risk, missing-data checks
```

Endpoint target:

```text
POST /v1/reasoners/water-irrigation-risk
```

#### 4. Nutrient / pH-EC Reasoner

Purpose:

```text
hydroponic or substrate sensor JSON + pH/EC history
  -> high/low pH, high/low EC, uptake issue, dilution/concentration checks
```

Endpoint target:

```text
POST /v1/reasoners/nutrient-ph-ec
```

#### 5. Crop-Specific Expansion

Build after the generic farm-system models above are usable through endpoints.

Planned order:

```text
strawberry risk reasoner
lettuce risk reasoner
aquaponic water chemistry reasoner
daily farm summary reasoner
digital twin scenario reasoner
```

Reason:

```text
Generic sensor, safety, actuator, water, and nutrient models become reusable building blocks. Crop models should come after those foundations so Pomona does not duplicate the same logic for every crop.
```

### Reusable Training Artifact Rule

For every new small model, create a modifiable local Colab notebook and versioned training zip:

```text
private/colab/pomona_<model_name>_v0_1_colab.ipynb
private/colab/pomona-<dataset-name>-v0.1-training-data.zip
```

The notebook must expose these editable values near the top:

```text
BASE_MODEL
OUTPUT_DIR
DATASET_ZIP_NAME
SYSTEM_PROMPT
ALLOWED_LABELS
MAX_LENGTH
training epochs / LoRA rank
```

The same notebook pattern should work when a new dataset zip is uploaded, as long as the schema and prompt are updated deliberately.

## Operating Principle

Pomona should not be one big model.

```text
Pomona platform
  -> sensor data and farm context
  -> model/router/tool selection
  -> small specialist models and/or big assistant
  -> deterministic rules and safety checker
  -> dashboard, chat, automation suggestions
```

All intelligence modules must be swappable:

- no LLM,
- small local LoRA,
- big assistant LLM,
- deterministic rule checker,
- digital twin simulator,
- future time-series model.

## 8-Week Timetable

### Week 1 — Publish-Safe Checkpoint And Cleanup

Goal: make the repo understandable and safe to push.

Tasks:

- Run publish checks.
- Confirm `.gitignore` excludes raw data, private files, HF repos, weights, checkpoints.
- Review new dataset/model docs.
- Keep `private/` local-only.
- Decide what public docs are ready for GitHub.
- Do not commit raw datasets or `.safetensors`.

Deliverable:

```text
GitHub-safe platform repo with docs, registry metadata, and no weights.
```

### Week 2 — SQLite Persistence In Core

Goal: sensor events survive restart.

Tasks:

- Add SQLite store to `services/core`.
- Keep existing in-memory behavior as simple fallback if useful.
- Add schema/migration-lite initialization.
- Add tests for event insert/list/latest.
- Expose recent sensor events through API.

Deliverable:

```text
pomona-core persists sensor events locally.
```

### Week 3 — Dashboard Skeleton

Goal: local SaaS UI starts to feel real.

Tasks:

- Build dashboard service screen for farm/zone latest readings.
- Add simple cards for temperature, humidity, pH, EC, moisture.
- Add recent event table.
- Add health/status panel for core/model-router/safety-checker.
- Keep UI practical, not marketing.

Deliverable:

```text
Dashboard shows live simulator data from core API.
```

### Week 4 — Safety Checker Integration

Goal: deterministic rule checker becomes an API service path.

Tasks:

- Expose tomato risk rules via `services/safety-checker`.
- Accept Pomona sensor JSON.
- Return guarded labels, missing data, blocked actions, and human review flag.
- Add tests for pesticide/action blocks, missing data, actuator conflict.
- Ensure no endpoint can request direct actuator control.

Deliverable:

```text
POST /v1/safety/check returns guarded tomato risk output.
```

### Week 5 — Model Router Hybrid Path

Goal: route between model-only, rules-only, and hybrid reasoner.

Tasks:

- Add tomato risk reasoner registry entry usage.
- Add a `hybrid_guarded` mode.
- Use rules-only fallback when model weights are unavailable.
- Keep Hugging Face/local model optional.
- Add API contract for model-router reasoner output.

Deliverable:

```text
model-router can return guarded tomato reasoner output.
```

### Week 6 — Dashboard Risk View

Goal: dashboard displays useful model/rule output.

Tasks:

- Add risk labels card.
- Add blocked actions card.
- Add safe next checks.
- Add clear model mode indicator:
  - stub,
  - rules-only,
  - hybrid,
  - assistant.
- Show why an action is blocked.

Deliverable:

```text
Dashboard shows sensor state + guarded risk reasoning.
```

### Week 7 — Big Assistant Integration

Goal: use the big assistant as an explanation layer, not as a controller.

Tasks:

- Route chat/explanation requests to `ai-pomona-agronomist-gemma4` when configured.
- Keep stub default.
- Provide context from sensor state and guarded labels.
- Safety-check assistant output before display.
- Add clear fallback if HF/API is unavailable.

Deliverable:

```text
User can ask for an explanation of guarded risk output.
```

### Week 8 — Digital Twin v0 Skeleton

Goal: create the first simulation/prediction service boundary.

Tasks:

- Add `services/digital-twin` or plan the service contract.
- Define input:
  - farm context,
  - latest sensor state,
  - historical window.
- Define output:
  - current state estimate,
  - simple forecast,
  - scenario notes.
- Start rules/simulation first; small models later.

Deliverable:

```text
Digital twin API contract and first simple simulator output.
```

## What To Do Right Now

Immediate order:

1. Finish GitHub-safe docs/metadata cleanup.
2. Commit/push platform checkpoint when ready.
3. Start Phase 2 SQLite persistence.
4. Build dashboard skeleton.
5. Add dashboard risk view.
6. Wire local LoRA inference into model-router when the platform path is ready.

Do not train another model until the platform can use the first one.

## Decision And Work Log

Add newest entries at the top.

### 2026-07-09

- Current model decision: stop training for now and move to platform integration. Use tomato-risk `v0.1.7`, sensor-quality `v0.1.1-boundary`, safety-triage `v0.1`, and actuator-command-gate `v0.1` with deterministic checker final authority.
- Do not use or publish actuator-command-gate `v0.1.1-hardcases`; local evaluation showed it regressed versus v0.1.
- Next GitHub repo work: update docs/metadata, then add `POST /v1/reasoners/sensor-quality` in `services/model-router`.
- Future models remain planned only: water/irrigation risk, nutrient/pH-EC, crop-specific risk, daily summary, and digital twin scenario reasoners.

### 2026-07-07

- Started **Pomona Sensor Quality Reasoner v0.1** as the next reusable small model after tomato risk and safety triage. Added docs, dataset scaffold, schemas, seed/eval JSONL, validator, generated local dataset builder, model registry metadata, and a local Colab notebook/zip under `private/colab/`.

### 2026-07-06

- Added **Pomona Safety Triage Reasoner v0.1.1 hardcases** dataset build: 2,371 total records with 360 hardcases for paraphrases, safe mentions of blocked concepts, soft/indirect unsafe requests, missing-data handling, and compound blocked actions. Created local Colab notebook and zip under `private/colab/`.
- Built the first local generated dataset for **Pomona Safety Triage Reasoner v0.1**: 2,011 records split into 1,609 train, 201 validation, and 201 test records under `datasets/processed/pomona-safety-triage-v0.1/`. Generated splits are ignored by Git and validated with the safety-triage validator.
- Added `POST /v1/reasoners/tomato-risk` to `services/model-router` with `rules_only`, `hybrid_guarded`, and explicit `model_only` not-implemented behavior. The route uses deterministic rules fallback now and gives the dashboard/API a stable contract before local LoRA inference is wired.
- Human owner decided not to update current Hugging Face pages immediately. Future models, datasets, and GitHub-facing pages should follow the Pomona publishing schema in this execution plan: cross-link platform code, related models, related datasets, metadata, usage, limitations, and safety notes.
- Verified `services/safety-checker` exposes deterministic tomato rules through `POST /v1/tomato-risk/check`; added API tests and updated the service README. This completes the platform slice for exposing the tomato rule checker API.
- Human owner accepted a safety-focused small-model direction. Added scaffold for **Pomona Safety Triage Reasoner v0.1** with schema, seed JSONL, eval JSONL, validator, docs, and model registry metadata. Training is deferred until tomato reasoner integration exists in the platform.
- Cleaned up Git index issue where agent/planning files were staged as deleted while still present on disk; updated `.gitignore` so execution-plan, agent rules, and public model docs can be tracked.
- Human owner asked for the next model direction. Initial idea was a safe action explainer; refined decision is **Pomona Safety Triage Reasoner v0.1**, with safe explanation as a later companion capability.
- Assistant recommendation accepted: do not train another model immediately; first wire the existing tomato risk reasoner into the SaaS path through safety/model-router/dashboard.
- Human owner asked that this file be the active future planner for Codex and Cursor. Rule added: read this file first for "what next" work, remove completed active items, and log user/assistant decisions.

### 2026-07-04

- Published `Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora` to Hugging Face as the current best tomato risk LoRA adapter.
- Added GitHub-facing docs and model registry metadata for the tomato risk reasoner.
- Expanded the Hugging Face model card with VibeThinker-style small verifiable reasoner motivation, while clearly stating Pomona does not use VibeThinker code, weights, or data.

### 2026-07-03

- Chose `v0.1.7-risk-label-list-normalfix` as the best standalone tomato risk adapter.
- Built local hybrid reasoner scripts that compare model-only, rules-only, and hybrid-guarded outputs.
- Hybrid guarded evaluation corrected model misses on rule-derived eval sets.

### 2026-07-02

- Built multiple tomato risk LoRA iterations from v0.1.5 through v0.2.
- Learned that repeated fine-tuning did not reliably beat the v0.1.7 adapter on general staged evaluation.
- Decision: use deterministic rule guardrails rather than chasing more tiny threshold-reasoning fine-tunes.

## Codex Vs Cursor Workflow

### Codex

Use Codex for:

- repo-wide edits,
- scripts,
- tests,
- backend services,
- publishing scripts,
- refactors,
- multi-file changes,
- debugging terminal/test failures,
- writing/maintaining docs.

Codex should usually work in complete vertical slices:

```text
inspect -> edit -> test -> summarize
```

### Cursor

Use Cursor for:

- focused file editing,
- UI polish,
- quick navigation,
- manual review,
- small fixes inside a file,
- reading code interactively,
- checking generated docs.

Cursor should follow the same rules as Codex and read:

```text
AGENTS.md
docs/PROJECT_STATUS.md
docs/PHASES.md
docs/EXECUTION_PLAN.md
```

### Human Owner

The human owner decides:

- when to publish GitHub,
- when to publish Hugging Face,
- whether to create new repos,
- whether a phase is complete,
- which model direction is next.

## Agent Rules

All AI agents must follow these rules.

### Repository Boundaries

```text
pomona/
  platform code, Docker, docs, services, model registry, dataset pipeline scaffold

~/Desktop/hf-repos/
  Hugging Face dataset/model checkouts

private/
  local experiments, adapters, notebooks, generated outputs
```

Never:

- put HF git repos inside `pomona`,
- commit model weights,
- commit raw third-party datasets,
- commit `.env` or tokens,
- modify `.git` manually.

### Architecture Rules

```text
Sensor/Simulator
  -> MQTT
  -> pomona-core
  -> DB
  -> model-router / digital-twin / safety-checker
  -> dashboard / chat / automation proposals
```

LLMs and small models are advisory. They do not directly control actuators.

Automation must be:

```text
rules first -> safety checked -> human approved
```

### Model Rules

Big model:

```text
ai-pomona-agronomist-gemma4
role: assistant/explanation/chat
```

Small models:

```text
role: narrow specialist tasks
examples: risk labels, anomaly labels, missing-data questions, safe explanation
```

Digital twin:

```text
role: simulate, forecast, compare scenarios, estimate state
```

Model weights live on Hugging Face only.

### Pomona Publishing Schema

Use this schema for any future public model, dataset, Space, demo, or GitHub-facing page. Do not rewrite existing pages only for this schema unless the human owner asks.

Every Hugging Face model card should include:

- YAML metadata at the top:
  - `license: apache-2.0` when compatible with the artifact,
  - `pipeline_tag` for the task,
  - `library_name` when relevant, such as `peft` for LoRA adapters,
  - `base_model` and `base_model_relation: adapter` for LoRA/adapters,
  - `datasets` for training/evaluation datasets,
  - focused tags such as `pomona`, `agriculture`, `greenhouse`, `tomato`, `risk-reasoning`, `safety`, `lora`, or `peft`.
- A short **Pomona Ecosystem** section near the beginning:
  - platform code on GitHub,
  - related base model,
  - related adapter/specialist model,
  - related dataset,
  - related docs or demo when available.
- A copy-paste **Usage** section that works for the artifact type.
- A **Task And Limits** section stating what the artifact does and does not do.
- A **Safety** section stating that Pomona models are advisory and never directly control actuators.
- A **Data** section linking any public dataset and describing private/local-only data if applicable without exposing secrets or raw private paths.

Every Hugging Face dataset card should include:

- YAML metadata with `license`, `task_categories` or `task_ids` when applicable, and focused Pomona tags.
- A **Pomona Ecosystem** section linking the platform repo and related models.
- Schema/example rows.
- Split, source, and generation notes.
- Safety/privacy notes.

Every GitHub README or public docs page that mentions models or datasets should include:

- A **Hugging Face Assets** section linking public models and datasets.
- A clear boundary statement:

```text
GitHub contains Pomona platform code and metadata only.
Model weights and public datasets live on Hugging Face.
Private notes, raw local data, tokens, and checkpoints stay out of GitHub.
```

Versioning rule:

- When publishing a replacement model, link older cards to the newer repo with `new_version` metadata when appropriate.
- Keep old model cards honest about limitations instead of deleting history.

### Small-Model Factory Rules

Before training a new small model:

1. Define task.
2. Define schema.
3. Define eval.
4. Define rule checker or teacher.
5. Build dataset.
6. Train.
7. Evaluate model-only.
8. Evaluate rules-only.
9. Evaluate hybrid.
10. Publish only if the model card can state limitations honestly.

Do not chase training loops before the platform can consume the model.

## Future Model Families

Use this routing idea:

```text
generic_sensor models
  sensor anomaly, missing data, data quality

farm_system models
  hydroponic pH/EC, aquaponic water chemistry, soil irrigation

crop_specific models
  tomato fungal risk, strawberry humidity risk, lettuce tipburn risk

explanation models
  safe next checks, dashboard summary, daily briefing

safety models/rules
  blocked actions, toxic/chemical warnings, automation gates
```

Do not build all at once. Build only what the platform can use next.

## Definition Of Done For Any Slice

A task is done when:

- code is implemented,
- tests or validation run,
- docs updated if behavior changed,
- no raw data/weights/secrets added,
- user can run one command to verify,
- final summary explains what changed and what remains.

## Work Log

### 2026-07-11

- Published Water/Irrigation Risk Reasoner v0.1.8 to `Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-lora` as a release candidate. Its model card discloses synthetic/rule-derived evaluation, advisory-only use, deterministic validation, local threshold calibration, and human-review requirements.
- Published Actuator Command Gate v0.1 to `Okyanus/pomona-actuator-command-gate-reasoner-v0.1-lora` as a research preview below the standalone release gate. The card exposes the independent scores and explicitly prohibits direct actuator use; Pomona's deterministic checker remains final authority.
- Added reciprocal ecosystem links to the existing tomato and agronomist Hugging Face model cards. Added the previously missing `Okyanus/greenhouse-sensor-data` dataset card with 4TU CC BY 4.0 attribution, mixed source/derived-data disclosure, limitations, and links to all public Pomona assets.
- Published the GitHub platform checkpoint to `okyanu/pomona` main at commit `91da20b`, including dataset scaffolds, model registry metadata, reasoner routes, deterministic safety services, model-factory documentation, and Hugging Face release scripts. Publish preflight, 25 service tests, four dataset validators, shell syntax, Python compilation, YAML parsing, and public-link verification passed.
- Imported `pomona-actuator-command-gate-reasoner-v0.1.2-correction-lora.zip` into the gitignored private adapter store after archive and SHA-256 verification. The 50-case generated Colab smoke test scored 1.0 on valid JSON, schema, allowed values, exact match, decision, labels, blocked actions, and human approval.
- Ran v0.1 and v0.1.2 on the unchanged 126-case independent clean holdout. v0.1 reproduced gate-label F1 0.8127, blocked-action F1 0.8333, and decision/review match 0.8571. v0.1.2 improved label F1 to 0.8537 and blocked F1 to 0.8889, but regressed decision match to 0.6667, review match to 0.7778, exact match to 0.2937, and allowed-label rate to 0.9841.
- Detailed v0.1.2 diagnosis: actuator-conflict, climate, fertigation, and schema behavior were strong; every clean observation and manual-check case was incorrectly routed to human approval; chemical blocked-action F1 was 0.5; irrigation decision/blocked F1 were 0.5; and two irrigation cases invented `safe_irrigation_control_request`. Decision: reject v0.1.2 as a standalone release, retain v0.1 for development comparison, and keep the deterministic gate as final authority.
- Enhanced the unified local evaluator with per-bucket decision/review/blocked metrics and separate invalid-output diagnostics. Reports remain private under `private/colab/outputs/`. Nothing was committed, pushed, or published.

### 2026-07-10

- Added `scripts/models/evaluate_unpublished_candidates.py`, a unified local evaluator for Safety Triage v0.1/v0.1.1, Sensor Quality v0.1.1, and Actuator Command Gate v0.1. It loads `Qwen/Qwen2.5-0.5B-Instruct` once, swaps local LoRA adapters, uses each training prompt contract, supports balanced smoke tests, and writes one private JSON report.
- Ran the full zero-overlap clean holdouts locally on CPU: 562 generations total. Safety v0.1 scored valid/required/allowed 1.0, safety-label F1 0.7753, blocked-action F1 0.7148, and review match 0.9609. Safety v0.1.1 regressed to label F1 0.6897, blocked F1 0.6745, and review match 0.8984; retain v0.1 and reject v0.1.1.
- Sensor Quality v0.1.1 scored valid JSON/allowed labels 1.0, required fields 0.9667, label F1 0.5389, missing-field F1 0.8333, suspect-field F1 0.5889, and review match 0.9333. It is not publishable; target normal/unit-mismatch separation, impossible pH, and generalized missing-field cases.
- Actuator Command Gate v0.1 scored valid/required/allowed outputs 1.0, gate-label F1 0.8127, blocked-action F1 0.8333, decision/review match 0.8571, and exact match 0.4365. It is the closest remaining candidate but not publishable; target chemical, manual-check, irrigation-control, and actuator-conflict behavior.
- Full private report: `private/colab/outputs/unpublished_model_full_clean_eval.json`. No model, dataset, commit, push, or Hugging Face publication was performed.
- Prepared Actuator Command Gate v0.1.2 targeted correction after the clean evaluation. The curriculum combines the v0.1 base with 2,880 focused examples across chemical, irrigation-control, actuator-conflict, clean/bad-sensor manual checks, climate, fertigation, and observation controls. Final split: 4,237 train, 528 validation, 529 generated test; zero exact overlap across splits and zero overlap with the independent 126-case clean holdout.
- Added `private/colab/pomona_actuator_command_gate_reasoner_v0_1_2_correction_colab.ipynb` and its training-data zip. The first run uses one epoch at `1.5e-4`, requires a GPU runtime, and includes a corrected gate-specific evaluator. Added `actuator-v0.1.2` support to the unified local evaluator for the post-training v0.1 versus v0.1.2 clean-holdout comparison. Nothing was trained, committed, pushed, or published in this preparation step.

### 2026-07-09

- Corrected public asset docs and model registry metadata: published HF assets are `Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora`, `Okyanus/ai-pomona-agronomist-gemma4`, and `Okyanus/greenhouse-sensor-data`. Sensor-quality, safety-triage, and actuator-command-gate remain local/unpublished candidates.
- Added `POST /v1/reasoners/sensor-quality` to `services/model-router` with deterministic rules fallback for missing, impossible, stale, unit-mismatch, drift, and conflicting sensor packets.
- Added model-router API tests for the sensor-quality endpoint. Verification: `services/model-router/.venv/bin/pytest services/model-router/tests/test_model_router_api.py` passed with 9 tests.
- Built water-irrigation-risk v0.1 as a local experiment and rejected it for public/model use. It produced valid JSON but failed label reasoning: 50-case label F1 0.0667, exact match 0.0.
- Added Purdue WHIN soil/weather as a candidate source with `license_needs_manual_verification`; no raw data downloaded or committed.
- Built water-irrigation-risk v0.1.1 simplified/realderived scaffold. Scope is moisture risk only; pump/valve conflicts remain deterministic. Generated local split: 1,800 records, 1,440 train, 180 validation, 180 test.
- Trained/evaluated `pomona-water-irrigation-risk-reasoner-v0.1.1-realderived-lora.zip`. It improved over v0.1 but remains not publishable: local 50-case eval valid JSON 1.0, label F1 0.6, exact match 0.16, human-review match 0.6. Next dataset fix should add focused stale/anomaly/boundary hardcases and likely train a v0.1.2 adapter.
- Built water-irrigation-risk v0.1.2 hardcase dataset: 3,000 records with focused stale, anomaly, low/high moisture boundary, and normal near-miss examples. Local Colab zip: `private/colab/pomona-water-irrigation-risk-v0.1.2-hardcases-training-data.zip`.
- Trained/evaluated `pomona-water-irrigation-risk-reasoner-v0.1.2-hardcases-lora.zip`; rejected as a regression. Local 50-case eval: valid JSON 1.0, label F1 0.44, exact match 0.02, human-review match 0.44. Cause appears to be normal-collapse from too many normal/near-miss examples plus only 1 epoch.
- Built water-irrigation-risk v0.1.3 balancedfix dataset: 2,520 records with seven balanced buckets (`normal`, `low_moisture`, `high_moisture`, `missing_moisture`, `stale_irrigation_data`, `sensor_anomaly`, `insufficient_context`). Local Colab zip: `private/colab/pomona-water-irrigation-risk-v0.1.3-balancedfix-training-data.zip`.
- Trained/evaluated `pomona-water-irrigation-risk-reasoner-v0.1.3-balancedfix-lora.zip`. This is the best water-irrigation candidate so far, but still not publish-ready. User Colab 50-case eval: valid JSON 1.0, exact match 0.66, label F1 0.82, blocked F1 0.82, human-review match 0.82. Local 50-case eval: valid JSON 1.0, allowed labels/actions 1.0, exact match 0.02, label F1 0.64, blocked F1 0.90, human-review match 0.90. Keep as local candidate; next improvement should focus on moisture-edge labels and output exactness.
- Built water-irrigation-risk v0.1.4 edgefix dataset: 2,940 records with balanced buckets for `normal`, `low_moisture`, `high_moisture`, `missing_moisture`, `stale_irrigation_data`, `sensor_anomaly`, and `insufficient_context`. This version focuses on exact threshold pairs such as 28.0 vs 28.1 and 77.9 vs 78.0, plus stale/missing/anomaly cases with stable expected wording.
- Updated the water-irrigation Colab notebook to train v0.1.4 using `private/colab/pomona-water-irrigation-risk-v0.1.4-edgefix-training-data.zip` and output `pomona-water-irrigation-risk-reasoner-v0.1.4-edgefix-lora.zip`. Keep the first run at 2 epochs, then compare against v0.1.3 before publishing anything.
- Trained/evaluated `pomona-water-irrigation-risk-reasoner-v0.1.4-edgefix-lora.zip`. This is the strongest water-irrigation candidate so far. User Colab 50-case eval: valid JSON 1.0, exact match 0.66, label F1 0.96, blocked F1 0.96, human-review match 0.96. Local CPU 50-case eval was less stable: valid JSON 1.0, allowed labels/actions 1.0, exact match 0.0, label F1 0.52, blocked F1 0.8533, human-review match 0.88. Full local CPU 294-case eval: valid JSON 1.0, allowed labels/actions 1.0, exact match 0.0, label F1 0.4354, blocked F1 0.8061, human-review match 0.8333. Decision: do not publish yet; use full 294-case Colab eval as the publish decision because local CPU generation is materially less stable.
- Full Colab 294-case eval for `pomona-water-irrigation-risk-reasoner-v0.1.4-edgefix-lora-2.zip`: valid JSON 1.0, exact match 0.8571, label F1 0.9116, blocked F1 0.9615, human-review match 0.9728. This is the first water-irrigation run above the target label/review range. However, pasted examples include invented risk labels on some `sensor_anomaly` cases, so the notebook evaluator was updated to report `allowed_labels_rate`, `allowed_blocked_actions_rate`, and invalid output examples. Decision: rerun Colab eval with the new allowed-label checks before Hugging Face upload.
- Built water-irrigation-risk v0.1.5 label-lock dataset after v0.1.4 invented invalid labels on impossible moisture cases. New split: 3,640 records, 2,912 train, 364 validation, 364 test, with 520 examples in each bucket. The only intended change is to lock moisture values below 0 or above 100 to `sensor_anomaly` with stable schema wording. Colab zip: `private/colab/pomona-water-irrigation-risk-v0.1.5-label-lock-training-data.zip`. Updated the water-irrigation Colab notebook to train/output `pomona-water-irrigation-risk-reasoner-v0.1.5-label-lock-lora.zip`.
- Trained/evaluated `pomona-water-irrigation-risk-reasoner-v0.1.5-label-lock-lora.zip` locally as a 50-case smoke test. Local CPU result: valid JSON 1.0, allowed labels 1.0, allowed blocked actions 1.0, label F1 0.728, blocked F1 0.9867, human-review match 1.0. This confirms the v0.1.4 invented-label blocker is fixed in the smoke test. Next decision must come from full Colab test split because local CPU remains conservative for label F1.
- Full local CPU 364-case eval for `pomona-water-irrigation-risk-reasoner-v0.1.5-label-lock-lora.zip`: valid JSON 1.0, allowed labels 1.0, allowed blocked actions 1.0, exact match 0.0055, label F1 0.672, blocked F1 0.9771, human-review match 1.0. This confirms schema obedience across the full local split. Next action: run full Colab eval; if label F1 stays >= 0.90 and invalid output count is 0, prepare Hugging Face model card/upload.
- Added eval-only Colab notebook for water-irrigation v0.1.5: `private/colab/pomona_water_irrigation_risk_reasoner_v0_1_5_eval_only_colab.ipynb`. Use this notebook for publish-gate evaluation only: upload the v0.1.5 training-data zip and trained adapter zip, then run the full test split and check `allowed_labels_rate`, `allowed_blocked_actions_rate`, `invalid_output_count`, `label_f1_avg`, and `human_review_match_rate`.
- Full Colab 364-case evaluation for `pomona-water-irrigation-risk-reasoner-v0.1.5-label-lock-lora.zip`: valid JSON 1.0, allowed labels 1.0, allowed blocked actions 1.0, invalid output count 0, blocked-action F1 1.0, human-review match 1.0, and label F1 0.7753. Decision: keep as a safe local prototype only; do not publish because diagnostic label accuracy misses the 0.90 gate. Next action: run a short per-label and required-field diagnostic before building a v0.1.6 classification-focused dataset.
- Added `private/colab/pomona_water_irrigation_risk_reasoner_v0_1_5_diagnostic_colab.ipynb`: a 56-case balanced diagnostic (8 rows per primary label bucket) with visible progress, per-bucket label F1, required-output-field presence, and missing-key counts. Use it with the same v0.1.5 dataset zip and adapter zip before changing the training data.
- v0.1.5 diagnostic result: valid JSON/actions/review were all 1.0, but required fields were present in 0.8571 and label F1 was 0.8536. `sensor_anomaly` label F1 was 0.375 and `stale_irrigation_data` was 0.625; both failures omitted `irrigation_risk_labels` and `missing_fields` rather than emitting an invalid label. Built v0.1.6 schema-order training data and notebooks to address this: output keys train in schema order with labels first, plus 960 train-only stale/anomaly schema-completion examples. The 364-case validation/test splits remain balanced with 52 cases in every primary-label bucket. Do not publish until the v0.1.6 full evaluation passes the updated gate.
- v0.1.6 run order: train with `pomona_water_irrigation_risk_reasoner_v0_1_6_schema_order_colab.ipynb`, run the 56-case diagnostic notebook first, then run `pomona_water_irrigation_risk_reasoner_v0_1_6_schema_order_full_eval_colab.ipynb` only if the diagnostic does not reveal a regression.
- Important evaluation correction: v0.1.6's initial 364-case score (label F1 0.9951) is **not publish-valid**. The generated split has 141 exact train/test input overlaps, 150 train/validation overlaps, and 32 validation/test overlaps. Added `validate_pomona_water_irrigation_splits.py`, which correctly fails this split. Built a 168-case clean holdout with zero exact overlap against v0.1.6 train data plus 56-case diagnostic and full clean-holdout Colab evaluators. Next decision: evaluate the already-trained v0.1.6 adapter on that clean holdout; do not publish based on the leaked split.
- Added controlled release evaluation packs for all other unpublished specialist adapters. Sensor quality now has a 180-case/15-category clean holdout; safety triage has a 128-case adversarial holdout for comparing v0.1 and v0.1.1; actuator gate has a 126-case/9-category boundary holdout. Every clean set validates and has zero exact overlap with its candidate training data. Added `docs/UNPUBLISHED_MODEL_RELEASES.md` with model-specific gates. Next action is evaluation, not additional training.
- Water v0.1.6 failed its independent 168-case holdout despite perfect schema compliance: label F1 0.4782, blocked-action F1 0.6726, and human-review match 0.75. Missing-moisture and sensor-anomaly classes scored 1.0, but stale and insufficient-context scored 0.0 and low/high/normal generalization was weak. Decision: reject v0.1.6 for publication.
- Built water v0.1.7 generalized as the targeted correction: 3,360 train, 392 validation, and 392 test records, balanced across seven primary categories with zero exact overlap across splits. Training uses continuous threshold values, explicit telemetry age, both stale representations, combined conditions, and exact threshold rules in the prompt. Colab artifacts: `pomona-water-irrigation-risk-v0.1.7-generalized-training-data.zip`, `pomona_water_irrigation_risk_reasoner_v0_1_7_generalized_colab.ipynb`, and the matching full-eval notebook.
- Trained water v0.1.7 generalized and evaluated all 392 leakage-free test cases: valid JSON/allowed labels/allowed actions 1.0, exact match 0.9184, label F1 0.9480, blocked-action F1 0.9456, human-review match 1.0, and zero invalid outputs. This is the strongest trustworthy water adapter so far. It passes label and review gates but misses the blocked-action gate by 0.0044. Added a v0.1.7-prompt evaluator for the independent 168-case external clean holdout; use that result for the final release or focused-correction decision.
- Water v0.1.7 external 168-case holdout: valid JSON/required fields/allowed actions/review all 1.0, but allowed-label rate 0.9405, label F1 0.8988, and blocked-action F1 0.9087. High, missing, normal, anomaly, and stale categories scored 1.0; weaknesses were system-type-only insufficient context (0.5) and low moisture (0.7917), plus ten invalid-label outputs. Decision: keep v0.1.7 as a strong internal/hybrid candidate but do not publish standalone.
- Built water v0.1.8 context-low-lock as a narrow correction: leakage-free v0.1.7 base plus 480 empty-system-type examples, 480 low-moisture examples, and 240 normal near-low-boundary controls. Total split: 4,560 train, 392 validation, 392 test, with zero exact overlap. Prompt now locks missing system type, low-moisture label/action pairing, and allowed-label-only output. Training, diagnostic, full-eval, and external-holdout notebooks are ready under `private/colab/`.
- Trained water v0.1.8 context-low-lock and evaluated all 392 leakage-free internal test cases: valid JSON, allowed labels/actions, label F1, blocked-action F1, and human-review match are all 1.0; invalid output count is zero. Exact match is 0.8444 due to harmless safe-check wording variation. This is a strong release candidate pending the independent 168-case external holdout.
- Water v0.1.8 passed the independent 168-case external holdout with valid JSON, required fields, allowed labels/actions, label F1, blocked-action F1, and human-review match all at 1.0; every category scored label F1 1.0 and there were no diagnostic failures. Promoted locally to `release_candidate_not_published`.
- Prepared the local Hugging Face release package at `private/colab/hf-publish/pomona-water-irrigation-risk-reasoner-v0.1.8-lora` with adapter files, Apache-2.0 license, model card, labels, samples, evaluation summary, and citation. Added `scripts/huggingface/publish_water_irrigation_reasoner_to_hf.sh`; it targets `~/Desktop/hf-repos/`, rejects paths inside the GitHub repo, and does not upload unless `PUSH_TO_HF=1`.

### 2026-07-07

- Built `pomona-sensor-quality-v0.1.1-boundary` to improve the first sensor-quality adapter's weak label separation.
- Added boundary cases for `unit_mismatch` vs `conflicting_readings`, `impossible_*` vs `sensor_drift_possible`, `missing_*` vs `insufficient_context`, and normal vs `stale_reading`.
- Prepared local Colab artifacts in `private/colab/`; these remain unpublished and outside GitHub release flow.
- Trained and evaluated `pomona-sensor-quality-reasoner-v0.1.1-boundary-lora.zip` locally. On 50 boundary test cases with the matched v0.1.1 prompt: valid JSON 1.00, allowed labels 1.00, exact match 0.34, label F1 0.78, missing-field F1 1.00, suspect-field F1 0.796, human-review match 0.92.
- Previous sensor-quality v0.1 on the same 50 boundary cases: exact match 0.08, label F1 0.42, missing-field F1 0.92, suspect-field F1 0.357.
- Full 270-case sensor-quality test for v0.1.1 boundary: valid JSON 1.00, allowed labels 1.00, exact match 0.319, label F1 0.793, missing-field F1 1.00, suspect-field F1 0.788, human-review match 0.933.
- Current sensor-quality candidate: v0.1.1 boundary is good enough to park as an upload-ready local candidate. Next model direction: Actuator Command Gate, but only after defining its endpoint contract, schema, deterministic blocked-action rules, and golden eval cases.
- Started **Pomona Actuator Command Gate Reasoner v0.1**. Added deterministic safety-checker rules and endpoint, dataset scaffold, schemas, hand-written seed/eval JSONL, generated local split, validator, model registry metadata, docs, and local Colab training notebook/zip.
- Actuator gate generated split: 2,414 records, train 1,932, validation 241, test 241.
- Trained and evaluated `pomona-actuator-command-gate-reasoner-v0.1-lora.zip` locally. Full 241-case test: valid JSON 1.00, allowed decision 1.00, allowed labels 1.00, allowed blocked actions 1.00, exact match 0.556, decision match 0.772, gate-label F1 0.873, blocked-action F1 0.959, human-approval match 0.772.
- Current actuator-gate status: useful schema-following v0.1, but not publish-ready as a standalone model. Weak spots are allowed/manual-check vs human-approval boundary cases and chemical request vs fertigation request confusion. Next action: build v0.1.1 hardcases before upload.
- Built **Pomona Actuator Command Gate Reasoner v0.1.1 hardcases**: 3,214 total records with 800 focused hardcases. Split: train 2,572, validation 321, test 321.
- Prepared local Colab artifacts: `private/colab/pomona_actuator_command_gate_reasoner_v0_1_1_hardcases_colab.ipynb` and `private/colab/pomona-actuator-command-gate-v0.1.1-hardcases-training-data.zip`. Next action: train this notebook and evaluate the downloaded adapter.
- Trained and evaluated `pomona-actuator-command-gate-reasoner-v0.1.1-hardcases-lora.zip`. Rejected as a regression: on 50 v0.1.1 hardcase test rows it scored exact match 0.12, decision match 0.62, gate-label F1 0.599, blocked-action F1 0.48, human-approval match 0.80.
- Previous actuator-gate v0.1 adapter on the same 50 hardcase rows scored exact match 0.56, decision match 1.00, gate-label F1 0.891, blocked-action F1 0.90, human-approval match 1.00.
- Current actuator-gate candidate remains v0.1. Do not publish v0.1.1 hardcases. Next improvement should use a cleaner curriculum or deterministic hybrid correction, not this hardcase LoRA.

## Suggested Commit Messages

Use concise commits:

```text
docs: add Pomona execution plan
feat(core): persist sensor events in SQLite
feat(safety): expose tomato risk guardrail endpoint
feat(model-router): add hybrid tomato reasoner route
feat(dashboard): show latest greenhouse readings
docs(models): document tomato risk reasoner
```
