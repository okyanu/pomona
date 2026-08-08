# Pomona Execution Plan

This is the practical timetable and AI-agent workflow for moving Pomona from the current checkpoint to a usable SaaS MVP with model routing, hybrid reasoners, and future small-model generation.

Product direction and long-range architecture: [POMONA_MASTER_ROADMAP.md](./POMONA_MASTER_ROADMAP.md).

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

- [x] Add one shared reasoner-chain contract in `services/model-router`: sensor quality first, water/irrigation risk second, deterministic actuator safety last.
- [x] Add integration tests for normal, missing-data, moisture-risk, and actuator-blocked packets across the shared chain.
- [x] Keep `POST /v1/actuator-command-gate/check` in `services/safety-checker` as deterministic final authority.
- [x] Start Phase 2 SQLite persistence in `services/core` after the first reasoner endpoint contract is stable.
- [x] Add the first read-only dashboard skeleton at `http://localhost:3000` for persisted sensor readings.
- [x] Add the dashboard guarded risk view sourced from the shared reasoner chain.
- [x] Add the first integrated software-validation pipeline endpoint with deterministic specialist orchestration and local audit output.
- [x] Add a reproducible local software-validation benchmark with latency, schema, safety, and machine metadata.
- [x] Add a safety-failure matrix covering missing, stale, impossible, conflicting, malformed, and unsafe-action inputs.
- [x] Connect the unified guarded pipeline to the read-only dashboard through `GET /api/pipeline`.
- [x] Expose bounded read-only pipeline audit summaries through model-router and dashboard APIs.
- [x] Add a repeatable no-Docker local validation runner with temporary state and assertions.
- [x] Include the dedicated Safety Checker service in the no-Docker runner and assert direct actuator rejection.
- [x] Assert dashboard service-status and deterministic-runtime visibility in the no-Docker runner.
- [x] Cover both high-risk blocking and routine observation paths in the no-Docker runner.
- [x] Verify the rendered dashboard HTML contains the integrated pipeline, audit, and read-only safety view.
- [x] Verify SQLite event recovery after restarting Core in the local runner.
- [x] Add local SQLite backup and restore commands independent of Docker.
- [x] Connect the unified pipeline's water/irrigation specialist to the configured local backend with deterministic guarded authority.
- [x] Route Nutrient/pH-EC through its explicit hybrid/rules contract inside the unified pipeline.
- [x] Show individual guarded specialist outputs and runtime sources in the read-only dashboard.
- [x] Expose a dashboard Digital Twin forecast-only preview from the latest persisted event.
- [x] Route Sensor Quality and Safety Triage through explicit guarded contracts inside the unified pipeline.
- [x] Add bounded Digital Twin scenario controls and validate forecast states through the guarded pipeline.
- [x] Add a repeatable pre-hardware validation suite for missing, stale, impossible, nutrient-risk, and unsafe-command scenarios.
- [x] Define and enforce the ESP32/MQTT sensor-event contract with units, transport bounds, JSON Schema, and Core API rejection tests.
- [x] Add a dry-run actuator command endpoint that audits safety decisions and guarantees no execution.
- [x] Add a one-shot ESP32/MQTT simulation validation that checks ingest, persistence, dashboard guarding, and dry-run actuator safety.
- [x] Add a non-destructive Docker SQLite backup, restart, and restore validation.
- [x] Carry an explicit `system_type` through the sensor contract and dashboard so hardware profiles can be selected without changing the transport layer.

### Next

- [x] Build dashboard skeleton for latest farm/zone sensor readings.
- [x] Add dashboard risk view for guarded labels, blocked actions, and safe checks.
- [x] Add dashboard service-status panel for core, model-router, and safety-checker.
- [x] Add dashboard advisory Agronomist note sourced from the guarded context.
- [x] Add Digital Twin v0 forecast-only scenario API.
- [x] Add model-router endpoint contracts for the small-model chain:
  - actuator command gate advisory route.
- [x] Add model-router safety triage advisory route using the deterministic safety policy.
- [x] Add deterministic Nutrient/pH-EC reasoner endpoint scaffold and registry metadata.
- [x] Add the local Nutrient/pH-EC dataset scaffold, balanced generated builder, and JSONL validator.

### Later

- [x] Review Nutrient/pH-EC thresholds and independent cases, then prepare a local-only Colab training/evaluation notebook.
- [x] Finish the guarded runtime quality gate for Nutrient/pH-EC GGUF/Ollama and MLX conversions; both guarded paths pass the full 140-case holdout, while model-only conversion scores remain disclosed and below the standalone gate.
- [x] Add guarded big assistant explanation route using `ai-pomona-agronomist-gemma4` or configured fallback.
- [x] Add digital twin v0 service/API contract.
- [x] Define the Pomona publishing schema with separate lifecycle and publication states; keep local artifacts `local_only` or `prepared_not_uploaded` until owner approval.

### Current Model Checkpoint

The current product direction is shared-model platform integration. Tomato v0.2.1 through v0.2.4 standalone correction adapters are rejected; Tomato remains deterministic rules plus guarded hybrid output until a larger-base experiment is justified.

Use the current best local/published reasoners:

```text
tomato-risk: v0.1.7 published baseline; v0.2.1 through v0.2.4 standalone correction adapters rejected; use deterministic rules plus guarded hybrid path
water-irrigation-risk: v0.1.8 published release candidate
sensor-quality: v0.1.1-boundary
safety-triage: v0.1
actuator-command-gate: v0.1 published research preview + deterministic checker final authority
rejected: actuator-command-gate v0.1.1-hardcases and v0.1.2-correction
```

Tomato standalone model gate, for any future larger-base experiment:

```text
1. Dataset validator passes with zero train/validation/test/release overlap.
2. Model-only output is valid JSON and uses only the declared risk labels.
3. Independent golden and release evaluation reach at least 0.90 label F1.
4. Deterministic rules-only and hybrid evaluation remain 1.00 on the safety holdout.
5. The model card states that labels are rule-derived/synthetic and are not field-ground-truth accuracy.
6. Only after these checks, ask the owner before any Hugging Face upload.
```

The v0.2.1 adapter failed this gate: it produced `fungal_pressure` for unrelated cases after deduplication removed most rare-label training examples. The v0.2.2 balanced-clean adapter also failed the golden gate with model-only label F1 0.6333 and exact match 0.60; it confused normal, high-EC, temperature, and missing-data cases. Both remain local-only for diagnosis. The deterministic rules-only and hybrid paths stayed at 1.00 on the golden holdout.

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

### 2026-07-26

- Added the local `make article-demo` evidence gate for the InfoQ technical article. It runs 65 service tests, the integrated local stack, and the seven-case pre-hardware benchmark, then writes ignored machine-readable evidence under `private/colab/outputs/`.
- Added the safety-constrained architecture diagram and two canonical annotated scenarios: simulated Arizona tomato risk and routine hydroponic lettuce. The scenario capture stores complete inputs and outputs locally and explicitly excludes field, hardware, adoption, and autonomous-safety claims.
- Replaced the Arizona scenario's fixed timestamp with `__CURRENT_TIMESTAMP__` so the article case isolates heat, moisture, pH, and nutrient behavior; the dedicated stale-telemetry fixture remains unchanged. The regenerated seven-case benchmark passed all schema, blocking, and human-review assertions at 1.0. No commit, push, hardware command, or Hugging Face upload was performed.
- Added a repeatable InfoQ runtime benchmark for cold startup, first request, 70 warm guarded-pipeline requests, 30 blocked dry-run gate requests, sampled Model Router RSS, and process CPU time. The full article gate passed with 259.061 ms cold startup, 0.552 ms average warm pipeline latency, 0.684 ms average dry-run gate latency, and 49.594 MB sampled peak RSS on the local Apple Silicon development machine. These measurements use the deterministic/stub runtime and are explicitly not edge-device or local-model results.
- Added the first complete InfoQ article draft, `docs/INFOQ_ARTICLE_DRAFT.md`, centered on separating probabilistic recommendations from deterministic control authority. The 2,547-word draft includes the architecture, two captured scenarios, local benchmark, model/dataset failures, reproducibility command, general lessons, and explicit unsupported claims. Target hardware measurements and independent reproduction remain pending; nothing was submitted, committed, pushed, or uploaded.

### 2026-07-21

- Rechecked Docker Desktop: the initial CLI context could not reach the engine even though the app was open; `docker compose config` still parsed successfully. Later direct socket verification confirmed the Docker API was healthy.
- Re-ran `make local-check` with the no-Docker runner: Core, Dashboard, Safety Checker, Digital Twin, and Model Router passed 53 tests; high-risk blocking, routine hydroponic flow, dashboard HTML, audit summaries, and SQLite restart recovery all passed.
- Confirmed Docker Desktop's API socket is healthy through the explicit `desktop-linux` socket endpoint, then built and started all six Compose services. Core, model-router, safety-checker, digital-twin, dashboard, and MQTT health checks passed; the Docker benchmark passed 4/4 cases with valid JSON, required fields, blocking assertions, and human-review assertions all at 1.0.
- Ingested a fresh simulated sensor event through the Docker Core API. SQLite-backed latest-event recovery, dashboard overview, guarded high-risk pipeline output, and summary-only audit redaction all passed.
- The first live Docker Ollama Water/Irrigation check exposed a false-positive normal classification: the model labeled 50% moisture as low moisture. Tightened guarded mode so deterministic rules own all structured decision fields and added a regression test; model-only mode remains explicitly unsafe for production use.
- Rebuilt the Docker model-router with the guard fix. Live Ollama checks now pass for normal 50% moisture and low 20% moisture, and the two-scenario Docker benchmark passes 4/4 cases with valid JSON, required fields, blocking assertions, and human-review assertions all at 1.0.
- Connected the unified pipeline to the configured Water/Irrigation backend. Local unit tests pass 35/35; Docker Ollama pipeline checks returned `ollama_guarded` for normal and low-moisture packets with deterministic labels, blocking, and review decisions; restored the default `REASONER_BACKEND=rules` afterward. No commit, push, or Hugging Face upload was performed.
- Routed Nutrient/pH-EC through its explicit `hybrid_guarded` contract inside the unified pipeline. The current implementation remains deterministic because model inference is not wired; the response now exposes the specialist mode/source consistently for future runtime integration. No commit, push, or Hugging Face upload was performed.
- Added a read-only dashboard specialist table for Sensor Quality, Water/Irrigation, Nutrient/pH-EC, Crop Risk, and Actuator Safety. It exposes labels, runtime source, and review state without adding any action controls. No commit, push, or Hugging Face upload was performed.
- Added `GET /api/digital-twin` and a dashboard forecast preview backed by the Digital Twin service. The preview is bounded, uses the latest persisted event, strips source metadata, and explicitly cannot execute or authorize actions. No commit, push, or Hugging Face upload was performed.
- Routed Sensor Quality and Safety Triage through explicit guarded contracts inside the unified pipeline. The response now exposes their mode/source metadata while deterministic rules remain authoritative; the final actuator safety gate is unchanged. No commit, push, or Hugging Face upload was performed.
- Added bounded dashboard Digital Twin controls for temperature, humidity, irrigation duration, ventilation, and horizon. `POST /api/digital-twin` validates scenario limits, runs the forecast, and evaluates the final forecast state through the guarded pipeline; it never creates or executes an actuator command. No commit, push, or Hugging Face upload was performed.
- Added `scripts/run_pre_hardware_validation.sh` and five additional simulated scenarios for missing data, stale telemetry, impossible sensor values, nutrient risk, and unsafe chemical commands. The seven-case suite passed with valid JSON, required fields, blocked-action assertions, and human-review assertions all at 1.0. It is dry-run software validation only; no hardware command was executed. No commit, push, or Hugging Face upload was performed.
- Added `schemas/sensor-event.schema.json` and `docs/HARDWARE_EVENT_CONTRACT.md` for the ESP32/MQTT payload contract. Core now rejects transport-level values outside physical ranges, with five boundary rejection tests. No device connection, actuator execution, commit, push, or Hugging Face upload was performed.
- Added `POST /v1/actuator-commands/dry-run` to model-router. It returns deterministic `allowed`/`blocked` decisions, writes redacted audit summaries, and always reports `execution_performed: false`; two API tests cover blocked and observation-only paths. No hardware command, commit, push, or Hugging Face upload was performed.
- Added `scripts/run_hardware_simulation_validation.sh` and `make hardware-simulation-validation`. With Docker running, it publishes two observation-only ESP32-shaped MQTT packets, verifies Core and Dashboard behavior, and checks the dry-run gate. No actuator command, commit, push, or Hugging Face upload was performed.
- Added `scripts/run_backup_recovery_validation.sh` and `make backup-recovery-validation`. It backs up the live Core database, restarts Core, verifies event recovery, and restores into a temporary database. Updated local phase/status/roadmap wording; Phase 2 remains partial because production hardening and real hardware validation are not complete. No commit, push, or Hugging Face upload was performed.
- Added `system_type` to the shared sensor event and dashboard context. Soil, greenhouse substrate/soilless, hydroponic, and aquaponic profiles can share transport, while their reasoner rules remain profile-specific. No commit, push, or Hugging Face upload was performed.

### 2026-07-20

- Reviewed `POMONA_PRE_HARDWARE_VALIDATION_PLAN.md` feedback. Decision: pause new model releases and complete the integrated software-simulation release first. Added `POST /v1/pipeline/evaluate`, combining sensor quality, water/irrigation, nutrient/pH-EC, tomato/crop rules, agronomist explanation, deterministic actuator safety, and a local append-only audit record.
- Added simulated scenarios `examples/scenarios/arizona_tomato.json` and `examples/scenarios/hydroponic_leafy_greens.json`, plus `scripts/run_software_validation.sh`. The tomato scenario demonstrates blocked irrigation/fertigation/actuator actions; the lettuce scenario demonstrates a routine observation path. Both are explicitly simulated and not field results.
- Added a local benchmark report at `private/colab/outputs/software_validation_benchmark.json` and a safety-failure matrix for missing, stale, impossible, conflicting, malformed, and unsafe-action inputs. Connected the same unified pipeline to the read-only dashboard at `GET /api/pipeline`, then added bounded summary-only audit views at `/v1/pipeline/audit` and `/api/audit`; the combined dashboard/model-router validation passes with 35 tests. No GitHub commit, push, Hugging Face upload, or public release was performed.
- Verified the local process path with temporary Core, Model Router, and Dashboard ports plus a temporary SQLite file. HTTP sensor ingest, dashboard pipeline output, dashboard audit summaries, and health endpoints passed end to end. Docker Compose could not start because Docker Desktop was not running; no repository or remote state was changed.
- Added `scripts/run_local_validation.sh` so the same no-Docker smoke test is repeatable with temporary SQLite/log state and automatic cleanup.
- Ran the broader local service suite: Core, Dashboard, Safety Checker, and Digital Twin pass 20 tests together; Model Router passes 33 tests separately. Added service-test import isolation for the shared `app` package name. No GitHub commit, push, or Hugging Face upload was performed.
- Extended `scripts/run_local_validation.sh` to start Safety Checker locally and verify `/v1/actuator-command-gate/check` independently blocks an unsafe irrigation command. The four-service local runner passes with high-risk pipeline output, one isolated audit summary, and a blocked safety-gate decision.
- Added dashboard `/api/services` and `/api/runtimes` assertions to the local runner; the smoke test now verifies all four services and the deterministic rules runtime are visible to the dashboard.
- Added a normal hydroponic lettuce case to the local runner; it must remain routine with no blocked actions or human review while the tomato case remains blocked.
- Added a dashboard HTML assertion to the local runner so the local checkpoint verifies the visible page labels as well as service APIs.
- Added Core restart recovery to the local runner; the ingested event must remain available from temporary SQLite after Core restarts.
- Added `scripts/backup_sqlite.sh` and `scripts/restore_sqlite.sh` for local SQLite recovery when Docker is unavailable.
- Documented the no-Docker local validation command in the root README for repeatable contributor verification.
- Added `make local-validation` as the short local entry point for the same isolated runner.
- Added `make test-local` for the full local service contract suite: Core, Dashboard, Safety Checker, Digital Twin, and Model Router.
- Added `make local-check` to run the full service tests and isolated four-service smoke test together before a human-reviewed commit.
- Added `docs/LOCAL_VALIDATION.md` documenting local commands, coverage, and non-production limitations.
- Added `docs/PUBLISHING_SCHEMA.md` with separate lifecycle/publication states for models, datasets, LoRA adapters, GGUF/Ollama, and MLX variants. Local preparation never changes an artifact to `published`; owner approval is required before any Hugging Face upload, and GitHub commit/push remains a separate approval.
- Added `make docker-config` to validate Docker Compose syntax without requiring the Docker daemon. The compose file parses locally; full container smoke testing remains blocked until Docker Desktop is running.
- Fixed `make test` to use the service virtual environments, matching the already-passing local test suite instead of failing when system Python lacks pytest.
- Synchronized README, PHASES, ROADMAP, and PROJECT_STATUS with the actual Phase 2 local checkpoint: SQLite persistence, dashboard, guarded pipeline, audit summaries, and no-Docker validation are complete locally; Docker smoke testing remains pending.
- Fixed the Docker benchmark's routine hydroponic fixture to resolve `__CURRENT_TIMESTAMP__` at validation time. The previous fixed-date fixture became stale and incorrectly failed the routine human-review assertion; explicit stale-data cases remain unchanged.

### 2026-07-17

- With explicit user approval, uploaded the Nutrient/pH-EC v0.1.1 F16 GGUF and MLX 8-bit guarded runtime packages to `Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-GGUF` and `Okyanus/pomona-nutrient-ph-ec-reasoner-v0.1.1-MLX`. Both cards disclose the lower model-only conversion scores, the 1.0000 guarded-hybrid holdout results, deterministic safety authority, and advisory-only scope. No GitHub commit or push was performed.
- Added `scripts/models/guard_nutrient_ph_ec_output.py` and guarded runtime evaluation. The deterministic Pomona rules now authoritatively enforce labels, missing fields, blocked actions, and human review after GGUF/MLX generation. Full 140-case guarded evaluations passed 1.0000 on every gate for both Ollama F16 GGUF and MLX 8-bit. This qualifies the guarded hybrid packages for owner review, not the bare converted models.

- Prepared structurally uploadable local packages for Nutrient/pH-EC v0.1.1 F16 GGUF/Ollama and MLX 8-bit under ignored `private/colab/hf-publish/`. Added complete model cards, Apache-2.0 licenses, citations, runtime configuration, and evaluation metadata. No Hugging Face upload, GitHub commit, or push was performed. The latest full raw Ollama evaluation remains below the runtime gate (allowed-label rate 0.8571, label F1 0.6690, blocked-action F1 0.8571, human-review match 0.8571); MLX has only an 0.8667-label-F1 smoke result. Both are experimental/not release-ready.

- Added the local model catalog, reciprocal local-card links, Nutrient/pH-EC v0.1.1 release-candidate card, and runtime conversion instructions. The catalog records 4 published model families and 3 active unpublished families: Sensor Quality, Safety Triage, and Nutrient/pH-EC. Nutrient GGUF/Ollama and MLX scripts are executable and write only under ignored `private/models/`; no conversion, upload, commit, or push was performed.
- Built the Nutrient/pH-EC v0.1.1 merged local checkpoint and F16 GGUF at `private/models/gguf/pomona-nutrient-ph-ec-v0.1.1-f16.gguf`, then registered it locally as `pomona-nutrient-ph-ec:v0.1.1` in Ollama. The exact-prompt runtime evaluator passed the five-case smoke but failed the full 140-case holdout: label F1 0.7857, blocked-action F1 0.9071, human-review match 0.8643, and allowed-label rate 0.8571. Built the 8-bit MLX conversion locally after installing `mlx-lm` in an ignored environment; its five-case smoke scored label F1 0.8667. Both converted formats are rejected pending runtime correction; no upload or repository publication was performed.
- Reviewed the existing independent clean evaluations for the remaining unpublished families. Sensor Quality v0.1.1 boundary remains blocked by label F1 0.5389, especially normal, unit-mismatch, impossible-pH, and missing-field buckets. Safety Triage v0.1 remains the retained candidate but is blocked by safety-label F1 0.7753 and blocked-action F1 0.7148, with chemical, diagnosis, multiple-blocked, and autonomous-fertigation weaknesses; v0.1.1 hardcases is rejected as a regression. Neither family is publishable.
- Prepared local Hugging Face staging packages for Sensor Quality v0.1.1 boundary, Safety Triage v0.1, and Nutrient/pH-EC v0.1.1 correction. Cards and evaluation JSON explicitly mark the first two as `not_publishable`; all packages remain under ignored `private/colab/hf-publish/`. No upload, commit, or push was performed.
- Completed and integrity-checked the local Nutrient/pH-EC v0.1.1 LoRA release package with adapter weights, tokenizer, chat template, labels, sample input/output, license, citation, and independent evaluation metadata. The LoRA itself is ready for owner review and possible upload; no upload was performed. GGUF/MLX remain separate runtime-format candidates and require their own evaluation.
- Received and verified `pomona-nutrient-ph-ec-reasoner-v0.1.1-correction-lora.zip`. Prepared the independent evaluation package `private/colab/pomona-nutrient-ph-ec-v0.1.1-correction-eval-data.zip` and matching notebook `private/colab/pomona_nutrient_ph_ec_reasoner_v0_1_1_correction_eval_colab.ipynb`; no publication was performed.
- Evaluated Nutrient/pH-EC v0.1.1 correction on the independent 140-case release holdout: valid JSON, allowed labels/actions, label F1, blocked-action F1, and human-review match were all 1.0. Exact match was 0.0 only because the adapter varied rationale wording while preserving the correct labels, checks, blocked action, and review decision. Promoted locally to `release_candidate_not_published`; no Hugging Face upload was performed.
- Rejected Nutrient/pH-EC v0.1-lora-2 as a standalone adapter after the 70-case evaluation: valid JSON 0.9857, allowed values 1.0, label F1 0.4143, blocked-action F1 0.8429, and human-review match 0.8429. Kept deterministic rules as authority.
- Built Nutrient/pH-EC v0.1.1 correction data with explicit derived pH/EC states, balanced hard cases, 1,412 training-contract records, and a separate 140-case release holdout. Validation passed; generated files remain ignored under `datasets/processed/`.
- Prepared local-only `private/colab/pomona_nutrient_ph_ec_reasoner_v0_1_1_correction_colab.ipynb` and `private/colab/pomona-nutrient-ph-ec-v0.1.1-correction-training-data.zip`. No training, commit, push, or Hugging Face upload was performed.

### 2026-07-16

- Evaluated `pomona-nutrient-ph-ec-reasoner-v0.1-lora-2.zip` on the 70-case generated test split. It achieved valid JSON 0.9857, allowed labels/actions 1.0, exact match 0.0, label F1 0.4143, blocked-action F1 0.8429, and human-review match 0.8429. It frequently collapsed pH/EC cases into `low_ph`, missed `sensor_anomaly` and `high_ec`, and varied rationale wording. Decision: reject as a standalone model; keep deterministic rules or guarded hybrid mode as authority. Next correction should add explicit derived pH/EC state features, balanced hard negatives, and a clean independent holdout.
- Received the first and second Nutrient/pH-EC adapter archives locally and verified they contain different LoRA weights. Added the evaluation-only notebook `private/colab/pomona_nutrient_ph_ec_reasoner_v0_1_lora_2_eval_colab.ipynb`, locked to the `-2` filename; no model evaluation result or publication decision has been made yet.
- Prepared local-only Nutrient/pH-EC training artifacts: `private/colab/pomona_nutrient_ph_ec_reasoner_v0_1_colab.ipynb` and `private/colab/pomona-nutrient-ph-ec-v0.1-training-data.zip`. The notebook trains `Qwen/Qwen2.5-0.5B-Instruct` with LoRA and downloads only the adapter archive. It must not be treated as a release until independent evaluation and domain review pass.
- Added the local Nutrient/pH-EC dataset scaffold with 12 committed hand-written sample/evaluation records, schemas, dataset card, and release-scope documentation. Added a balanced generated builder with 712 total records across normal, pH, EC, anomaly, and missing-data buckets; generated train/validation/test files remain under ignored `datasets/processed/`.
- Validated the Nutrient/pH-EC committed data and generated splits: 724 records checked, JSONL/schema/type/allowed-label/action validation passed, and all 712 generated expected outputs match the deterministic router implementation. No raw data, model weights, commit, push, or Hugging Face upload was performed.
- Verified Nutrient/pH-EC endpoint behavior live with a high-pH/high-EC packet. It returned `high_ph`, `high_ec`, `nutrient_uptake_issue`, blocked `autonomous_fertigation_change`, and required human review. Full model-router suite now passes 25 tests.
- Added the deterministic-first Nutrient/pH-EC Reasoner scaffold at `POST /v1/reasoners/nutrient-ph-ec`, with pH/EC thresholds, missing-data handling, fertigation blocking, registry metadata, documentation, and API tests. No training data or model weights were created.
- Verified `GET /v1/runtimes` and dashboard `GET /api/runtimes` live. Rules are available, Ollama is reachable with both local Pomona models visible, and MLX is accurately reported offline because no MLX server is running. Router tests remain at 22 passed.
- Added `GET /v1/runtimes` to model-router and `GET /api/runtimes` to the dashboard. They report deterministic rules availability plus Ollama/MLX reachability and configured models without loading weights or changing runtime state.
- Rebuilt the dashboard and verified `GET /api/safety` against the persisted Docker event. It returned the Safety Triage result with `safe_observation_only`, no blocked actions, and no operational execution path. Digital Twin tests passed 2 tests.
- Added dashboard `GET /api/safety` and a read-only Safety Triage panel. It displays the current advisory decision, labels, blocked actions, safe alternative, and review status using a non-operational `continue_monitoring` action. No command execution path was added.
- Verified the installed local Ollama runtime through `POST /v1/reasoners/water-irrigation-risk` using `pomona-water-irrigation:v0.1.8`. The direct router case and a 10-case frozen smoke evaluation both returned valid, allowed outputs with label F1 1.0, blocked-action F1 1.0, and human-review match 1.0. The report is local-only at `private/colab/outputs/water-v0.1.8-ollama-smoke.json`; no model download, rebuild, commit, or upload was performed.
- Verified `scripts/backup_core_db.sh` against the running Docker SQLite volume using a temporary `/tmp` destination. The backup opened successfully and preserved the persisted sensor event (`esp32-greenhouse-01`); no restore or active database modification was performed.
- Built and verified the complete local Docker stack: MQTT, Core, Model Router, Safety Checker, Dashboard, and Digital Twin. Fixed model-router path resolution for `/app` containers and added a read-only safety-rule mount so the shared chain starts correctly in Docker. Verified SQLite event persistence, health endpoints, shared-chain blocking, dashboard overview/risk/explanation, service status, and forecast-only Digital Twin output. No commit or push was performed.
- Added guarded Agronomist context to `POST /v1/advisor/explain` and the dashboard explanation path. The advisor now receives validated reasoner output as a safety boundary, while stub/Ollama/Hugging Face backends remain advisory and cannot issue operational actions. Added a router test for guarded context propagation; no commit, push, model upload, or dataset upload was performed.
- Added `POST /v1/reasoners/safety-triage` to `services/model-router`. It maps the deterministic actuator gate into the safety-triage schema, supports advisory `rules_only` and `hybrid_guarded` modes, rejects model-only mode until independent evaluation passes, and keeps the safety-checker as final authority. Added safe, blocked, and model-only contract tests; no commit, push, model upload, or dataset upload was performed.
- Added `POST /v1/reasoners/actuator-command-gate` to `services/model-router`. It exposes the existing deterministic actuator gate as an advisory `rules_only` or `hybrid_guarded` route, rejects model-only mode until a candidate passes independent evaluation, and keeps `services/safety-checker` as final authority. Added API contract tests; no commit, push, model upload, or dataset upload was performed.

- Imported the maintainer's full product roadmap as `docs/POMONA_MASTER_ROADMAP.md` and linked it from this execution plan. The roadmap keeps the product sequence centered on a real edge data loop, deterministic safety, hybrid reasoners, Digital Twin, Agronomist, and Model Studio rather than isolated model uploads.
- Rejected Tomato v0.2.1 correction as a model-only release after the unchanged golden holdout regressed to label F1 0.1778. The failure was traced to unsafe deduplication and severe rare-label imbalance, not to the deterministic Tomato rules.
- Started Tomato v0.2.2 balanced-clean locally. The new builder preserves rare-label coverage, jitters sensor values, excludes golden-equivalent inputs, and creates an independent release evaluation split. No adapter training, Hugging Face upload, GitHub commit, or push was performed.
- Tomato v0.2.2 is complete only after dataset validation, model-only golden/release evaluation, rules-only/hybrid comparison, and an honest synthetic-data limitation statement all pass the gates recorded above. After that checkpoint, return to the platform chain and ask the owner before publication.
- Evaluated `pomona-tomato-risk-reasoner-v0.2.2-balanced-lora.zip` locally with the v0.2.2 prompt on the 15-case golden holdout. Model-only output was valid JSON/list syntax with allowed labels, but label F1 was 0.6333 and exact match was 0.60. It misclassified normal controlled/substrate cases, high EC, heat, cold, and missing pH. Rules-only and hybrid guarded outputs were both 1.00. Decision: reject v0.2.2 as a standalone model and do not run a full release evaluation or publish it.
- Prepared Tomato v0.2.3 golden-correction data with 2,340 training-contract records: 1,872 train, 234 validation, 234 test, 780 independent release cases, and 15 golden cases. It focuses on the v0.2.2 confusions, preserves every allowed label combination, uses value-jittered inputs to avoid exact golden leakage, and changes training to three epochs at `7e-5`. Colab artifacts remain local-only under `private/colab/`; no training, commit, push, or publication was performed.
- Evaluated `pomona-tomato-risk-reasoner-v0.2.3-golden-correction-lora.zip` locally on the 15-case golden holdout. Model-only output was valid JSON/list syntax with allowed labels, but label F1 fell to 0.3778 and exact match to 0.3333. It confused normal data with pH/EC labels and missed cold, fungal, missing-data, anomaly, and water cases. Rules-only and hybrid guarded outputs were both 1.00. Decision: reject v0.2.3 and do not run release evaluation or publish it.
- Prepared the final structured-input Tomato v0.2.4 attempt. Every record now contains the raw sensor packet plus deterministic `derived_signals` (`ph_state`, `ec_state`, temperature/humidity/moisture states, missing-data state, fungal signal, nutrient signal, and actuator conflict). The Qwen 0.5B adapter is trained as a constrained label formatter, with two epochs at `5e-5`. Dataset validation passes with 1,872 train, 234 validation, 234 test, 780 release, and 15 golden records with zero overlap. Colab artifacts remain local-only; no training, commit, push, or publication was performed.
- Evaluated `pomona-tomato-risk-reasoner-v0.2.4-structured-lora.zip` with the matching structured evaluator on the 15-case golden holdout. Model-only output was valid JSON/list syntax, but label F1 was 0.4000 and exact match was 0.2667; hybrid guarded output remained 1.00. The adapter still confused normal, nutrient, temperature, and risk states. Decision: reject v0.2.4 as a standalone/public model. The Tomato model work is complete for this Qwen 0.5B line; keep deterministic rules as authority and use the small adapter only as an optional non-authoritative experiment.
- Product decision: stop iterating the Tomato Qwen2.5-0.5B standalone adapter and focus on the shared model chain. The next implementation task is one router-level integration contract: Sensor Quality -> Water/Irrigation Risk -> deterministic Actuator Safety. This makes the successful shared models useful across Tomato, strawberry, lettuce, and future crop profiles before adding more crop-specific training.
- Implemented `POST /v1/reasoners/shared-chain` with deterministic dependency order: Sensor Quality -> Water/Irrigation Risk -> Actuator Safety. It returns nested specialist results, combined blocked actions, review status, and explicit hybrid fallback metadata. Added normal, missing-data/moisture-risk, and actuator-blocked integration tests; `services/model-router/.venv/bin/python -m pytest services/model-router/tests/test_model_router_api.py -q` passes 15 tests. No commit or push was performed.
- Replaced the in-memory core event deque with SQLite persistence at configurable `DB_PATH` (default `data/pomona.db`), added Docker `core_data` volume wiring, and retained the existing sensor event API. Core verification passes 2 tests. Next platform task is the dashboard/read-model slice.
- Added local-only `scripts/backup_core_db.sh` and `scripts/restore_core_db.sh` for exporting/restoring the Docker SQLite database. Backup files under `backups/` are gitignored; no database contents are committed.
- Added the first dashboard service under `services/dashboard`: read-only live sensor overview, core availability status, recent event table, Docker wiring on port 3000, and smoke verification. It does not execute model output or control actuators. No commit or push was performed.
- Added dashboard `/api/risk` and a guarded risk status view showing sensor-quality labels, water/irrigation labels, safety decision, blocked actions, and human-review status. The dashboard remains read-only; Compose now waits for model-router as well as core. Dashboard smoke tests and Compose validation pass.
- Added dashboard `/api/services` and a service-status panel for core, model-router, and safety-checker health. The dashboard now exposes the local chain's operational availability without executing commands. Dashboard service-status smoke test, Python compilation, Compose validation, and diff checks pass. No commit or push was performed.
- Added dashboard `/api/explanation`, which sends the latest sensor packet to the existing Agronomist advisor with guarded-context instructions and renders the result as advisory-only text. It never executes model output or exposes actuator control. No commit or push was performed.
- Added `services/digital-twin` with `POST /v1/digital-twin/scenarios/simulate`, bounded temperature/humidity/moisture trajectories, safety disclaimers, Docker Compose wiring on port 8084, and API tests. It is forecast-only and never controls actuators.

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

### 2026-07-26

- Added a local-only commit-control workflow for the large dirty worktree. `make commit-plan` classifies changed paths into platform candidates, ML-repo holds, local-sensitive files, tracked redaction reviews, manual review, and never-commit groups, then writes ignored Markdown and JSON reports under `private/`. It never stages, deletes, commits, pushes, or uploads files. InfoQ drafts/evidence and the owner master roadmap are now explicitly ignored; already tracked operational logs remain blocked for redaction review rather than being treated as automatically public.

### 2026-07-14

- Prepared local-only Tomato v0.1.7 deployment candidates for Ollama/GGUF F16 and MLX 8-bit. Both formats returned valid JSON and allowed labels on the 15-case golden smoke suite, but each reached only label F1 0.600 and exact-label match 0.600. The original LoRA reached model-only F1 0.6667 on the same suite; deterministic tomato rules and guarded hybrid logic reached 1.0. Decision: keep both runtime formats private integration candidates only, not release candidates. Their staging notes, artifacts, and reports are under gitignored `private/`; no Hugging Face, GitHub, commit, push, or public update was made.
- Prepared Tomato v0.2.1 local quality-correction training data from the later v0.2 boundary curriculum. v0.2 improved the unchanged 15-case golden model-only label F1 from 0.6667 to 0.7778, but still missed safe substrate normals, missing pH, impossible EC, and humidity-plus-screen conflict behavior. The v0.2.1 builder adds targeted contrasts, globally deduplicates source inputs, excludes all golden-equivalent rows from train/validation/test, and produces 3,326 train, 412 validation, 412 test, 15 golden, and 420 zero-overlap release-evaluation records. The release holdout is rule-derived synthetic data, not independent field ground truth. Local Colab ZIP and notebook are under gitignored `private/colab/`; no training, commit, push, or publication was performed.
- Evaluated locally trained Tomato v0.2.1 correction adapter (`SHA-256 0818a1d4ff5dc4c81d990ecf6ba028ce7d0616530aa76a3577f5be2d3a681bd5`). It is rejected: the unchanged 15-case golden model-only F1 regressed to 0.1778 and exact match to 0.1333, while JSON validity remained 1.0. Diagnosis: global exact-input deduplication collapsed the training distribution to 2,723 normal rows but only 1-26 examples for several risk labels; the adapter consequently over-predicted `fungal_pressure`. Do not run release evaluation, upload, or use this adapter beyond guarded-rule experiments. Next data version must use balanced, value-jittered examples and preserve label coverage without split leakage.

### 2026-07-12

- With explicit user approval, published the accepted Water/Irrigation v0.1.8 deployment formats to Hugging Face: `Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-GGUF` (F16 GGUF/Ollama) and `Okyanus/pomona-water-irrigation-risk-reasoner-v0.1.8-MLX` (8-bit MLX). Both cards identify the canonical LoRA lineage, frozen 168-case results, synthetic/rule-derived evaluation limits, advisory-only scope, and deterministic-safety requirements. The rejected 4-bit MLX artifact was not uploaded. No GitHub commit or push was performed.
- Built and evaluated local deployment formats for Water/Irrigation v0.1.8. Ollama F16 GGUF passed all 168 frozen holdout cases with valid/required/allowed outputs, label F1, blocked-action F1, and human-review match all at 1.0 in 97.14 seconds. MLX 8-bit also scored 1.0 on every gate in 80.47 seconds and is the preferred Apple Silicon candidate. MLX 4-bit regressed to label F1 0.7262 and review match 0.5536 and is rejected.
- Added a reusable Ollama/MLX frozen-holdout evaluator. Private reports are under `private/colab/outputs/`; merged, GGUF, Ollama, and MLX artifacts remain under gitignored `private/models/`. No runtime artifact was published.
- Added `POST /v1/reasoners/water-irrigation-risk` with one stable API contract across deterministic rules, Ollama/GGUF, and an OpenAI-compatible MLX server. `hybrid_guarded` validates model JSON and merges deterministic risk/action guards; unavailable or invalid local runtimes fall back to rules. `model_only` rejects invalid outputs and is intended for evaluation.
- Added local-only packaging tools to merge the v0.1.8 Qwen LoRA, build an Ollama-compatible GGUF model, and build a 4-bit MLX model. Generated artifacts stay under gitignored `private/models/`; no weights were committed or uploaded.
- Added runtime configuration, Docker environment wiring, registry metadata, and `docs/LOCAL_MODEL_RUNTIMES.md`. Full verification passed: 2 core tests and 12 model-router tests, plus Python compilation, shell syntax, YAML parsing, and `git diff --check`.
- No commit, push, tag, GitHub update, or Hugging Face update was performed. Next local action is installing/locating Ollama and `llama.cpp`, building the GGUF candidate, then rerunning the frozen v0.1.8 evaluation against the quantized runtime before considering any publication.

### 2026-07-11

- Established independent platform/model/dataset versioning. The current GitHub platform checkpoint is `v0.1.0-alpha.1`; model checkpoints retain their own versions and lifecycle labels, and phases remain product milestones rather than release numbers. Added `VERSION` and `docs/VERSIONING.md`, synchronized the public phase tables, and documented experimental, research-preview, release-candidate, stable, deprecated, and rejected-regression states.
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
