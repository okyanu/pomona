# Dataset Card: Pomona Actuator Command Gate v0.1

## Summary

Pomona Actuator Command Gate v0.1 is a compact generated dataset for training a narrow farm safety reasoner.

Input records contain farm context, sensor readings, sensor-quality output, risk labels, actor identity, and a proposed command. Output records classify whether the command is allowed, blocked, or needs human approval.

## Intended Use

- Train and evaluate a small LoRA adapter for command-gate classification.
- Support Pomona's model-router and safety-checker workflow.
- Provide schema-stable examples for future actuator safety endpoint work.

## Out Of Scope

- Direct actuator control.
- Chemical dosage instructions.
- Definitive disease diagnosis.
- Replacement for deterministic safety logic.

## Generation

Rows are generated from Pomona rule templates and small hand-written seed/eval examples. There are no raw third-party files in this dataset scaffold.

## Safety

The trained model is advisory. Pomona's deterministic safety-checker must remain the final authority before any dashboard or automation flow.
