"""Canonical input contract for the Pomona Sensor Quality Reasoner.

This is the single source of truth for how a sensor-quality `input` record
becomes a model prompt. It mirrors the verified `render()` implementation in
`private/colab/sensor_quality_paired_diagnostic.py` (offline-audited against
`private/colab/pomona_sensor_quality_verified_baseline_eval.ipynb`) and exists
so training-data prep, evaluation, and any future deployment code build
prompts identically instead of re-implementing this logic per notebook.

Do not build prompts by loading records through `datasets.load_dataset` or
pandas: both infer a columnar schema across the whole file, which silently
can reformat timestamps depending on version and row order. Omitted-key
normalization was not reproduced in the September 8 local recheck; do not
assume it happens in every version. See `docs/SENSOR_QUALITY_INPUT_CONTRACT.md` for the
loader-audit evidence. Always render each record's raw JSON dict directly, as
`render_prompt` does below.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict

SYSTEM_PROMPT = (
    "You are Pomona Sensor Quality Reasoner, a narrow farm telemetry quality classifier.\n"
    "Return only one valid JSON object with exactly these keys:\n"
    "- data_quality_labels: list of allowed labels\n"
    "- missing_fields: list of missing required sensor field names\n"
    "- suspect_fields: list of suspect sensor field names\n"
    "- safe_next_checks: list of safe manual checks\n"
    "- human_review_required: boolean\n"
    "- rationale: short reason string\n"
    "\n"
    "Allowed data_quality_labels:\n"
    "missing_ph, missing_ec, missing_temperature, missing_humidity, missing_moisture,\n"
    "impossible_ph, impossible_ec, impossible_temperature, impossible_humidity,\n"
    "stale_reading, unit_mismatch, sensor_drift_possible, conflicting_readings, insufficient_context.\n"
    "\n"
    "Rules:\n"
    "- If required pH, EC, air temperature, humidity, or moisture is null/missing, use the matching missing label.\n"
    "- Use impossible_ph for pH outside plausible agricultural range.\n"
    "- Use impossible_ec for negative or extreme EC.\n"
    "- Use impossible_humidity for humidity below 0 or above 100 percent.\n"
    "- Use impossible_temperature for extreme greenhouse/farm temperature.\n"
    "- Use stale_reading when current_time minus sensor.timestamp is more than 1 hour. Compute the gap; do not judge staleness from the calendar date alone.\n"
    "- Use unit_mismatch when Celsius/Fahrenheit or unit naming is ambiguous.\n"
    "- Use conflicting_readings when primary and backup readings strongly disagree.\n"
    "- Use sensor_drift_possible for abrupt jumps from previous readings.\n"
    "- Use insufficient_context when expected fields or farm context are not defined.\n"
    '- If data is complete and plausible, output empty labels, empty missing/suspect fields, safe_next_checks ["continue routine monitoring"], and human_review_required false.\n'
    "- Never output extra text outside the JSON object.\n"
)

# Regression guard: if this stops matching, SYSTEM_PROMPT has drifted from the
# verified notebook copy it was extracted from -- update both together.
SYSTEM_PROMPT_SHA256 = "74dab26cca7e43b87a1a5d3d82f814d2d87c5ab6fc2e102523a2b0c964f9ace4"

USER_INSTRUCTION = "Classify this farm sensor packet for data quality."

# Top-level keys a rendered prompt must carry, and the default used only when
# a key is absent from the whole `input` object (not from `sensor`/`farm_context`
# sub-fields -- those pass through unmodified, omitted or not).
TOP_LEVEL_DEFAULTS: Dict[str, Any] = {
    "farm_context": {},
    "sensor": {},
    "expected_fields": [],
    "current_time": None,
}


def render_prompt(input_data: Dict[str, Any], system_prompt: str = SYSTEM_PROMPT) -> str:
    """Render one sensor-quality `input` record into the exact training/eval prompt string.

    `input_data` must be a plain dict decoded straight from JSON (e.g. via
    `json.loads` on one JSONL line) -- not a row produced by `datasets` or
    pandas, which normalize missing keys across the file.
    """
    user = {key: input_data.get(key, default) for key, default in TOP_LEVEL_DEFAULTS.items()}
    body = json.dumps(user, separators=(",", ":"), sort_keys=True, default=str)
    return (
        "<|im_start|>system\n"
        + system_prompt
        + "\n<|im_end|>\n<|im_start|>user\n"
        + USER_INSTRUCTION
        + "\n"
        + body
        + "\n<|im_end|>\n<|im_start|>assistant\n"
    )


def verify_system_prompt(system_prompt: str = SYSTEM_PROMPT) -> bool:
    return hashlib.sha256(system_prompt.encode()).hexdigest() == SYSTEM_PROMPT_SHA256
