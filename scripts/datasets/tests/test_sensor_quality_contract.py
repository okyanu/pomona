"""Regression tests for the canonical sensor-quality input contract.

These guard the specific failure modes found by the 2026-09-07 paired
diagnostic (see `private/SENSOR_QUALITY_PAIRED_RESULTS_2026_09_07.md`):
omitted-vs-null prompts silently colliding, and HF `datasets` loading
reformatting timestamps / null-filling omitted keys before a prompt is built.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from sensor_quality_contract import (  # noqa: E402
    SYSTEM_PROMPT,
    render_prompt,
    verify_system_prompt,
)


BASE_INPUT = {
    "farm_context": {"crop": "tomato", "system_type": "hydroponic", "zone_id": "zone-a"},
    "sensor": {
        "air_temperature_c": 24.0,
        "humidity_pct": 68.0,
        "ph": 6.2,
        "ec_ms_cm": 2.4,
        "timestamp": "2026-07-07T10:00:00Z",
    },
    "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"],
    "current_time": "2026-07-07T10:03:00Z",
}


def test_system_prompt_matches_verified_notebook_copy():
    assert verify_system_prompt(SYSTEM_PROMPT)


def test_omitted_key_and_explicit_null_render_differently():
    null_variant = copy.deepcopy(BASE_INPUT)
    null_variant["sensor"]["ph"] = None

    omitted_variant = copy.deepcopy(BASE_INPUT)
    del omitted_variant["sensor"]["ph"]

    assert render_prompt(null_variant) != render_prompt(omitted_variant)


def test_render_is_stable_regardless_of_input_dict_key_order():
    reordered = json.loads(json.dumps(BASE_INPUT))
    shuffled = {k: reordered[k] for k in reversed(list(reordered))}
    shuffled["sensor"] = {k: shuffled["sensor"][k] for k in reversed(list(shuffled["sensor"]))}

    assert render_prompt(BASE_INPUT) == render_prompt(shuffled)


def test_render_is_deterministic():
    assert render_prompt(BASE_INPUT) == render_prompt(copy.deepcopy(BASE_INPUT))


def test_missing_top_level_keys_use_documented_defaults():
    minimal = {"sensor": BASE_INPUT["sensor"]}
    rendered = render_prompt(minimal)
    assert '"farm_context":{}' in rendered
    assert '"expected_fields":[]' in rendered
    assert '"current_time":null' in rendered


def test_timestamp_passes_through_unmodified():
    rendered = render_prompt(BASE_INPUT)
    assert "2026-07-07T10:00:00Z" in rendered
    assert "2026-07-07T10:03:00Z" in rendered


def test_hf_datasets_loader_reformats_records_do_not_use_it_for_prompts():
    """Documents the loader hazard so it cannot be silently reintroduced.

    Skips if the real `datasets` package is not importable locally -- this
    repo has its own top-level `datasets/` directory, which shadows the pip
    package of the same name on `sys.path` and has no `load_dataset` --
    rather than the pip package. The hazard is exercised for real in the GPU
    diagnostic runner (`private/colab/sensor_quality_paired_diagnostic.py`).
    """
    datasets = pytest.importorskip("datasets")
    if not hasattr(datasets, "load_dataset"):
        pytest.skip("`datasets` on sys.path is this repo's own datasets/ directory, not the HF package")
    import tempfile

    record = {"id": "contract-test-0001", "input": copy.deepcopy(BASE_INPUT)}
    del record["input"]["sensor"]["ph"]  # a truly-omitted field, like the training gap case

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "one.jsonl"
        path.write_text(json.dumps(record) + "\n", encoding="utf-8")
        loaded = list(datasets.load_dataset("json", data_files=str(path), split="train"))

    raw_prompt = render_prompt(record["input"])
    loaded_prompt = render_prompt(loaded[0]["input"])
    assert raw_prompt != loaded_prompt, (
        "datasets.load_dataset stopped reformatting omitted/null fields; "
        "if this now fails, the loader hazard documented in "
        "docs/SENSOR_QUALITY_INPUT_CONTRACT.md may be resolved upstream -- "
        "re-verify before relying on it for prompt building."
    )
