import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_pomona_sensor_quality_v0_1_5_dataset as builder  # noqa: E402
from prepare_sensor_quality_review_bundle import expanded_cases  # noqa: E402

RECORDS = builder.generate(seed=7, count=600)


def test_every_target_matches_the_deterministic_contract():
    rules = builder.load_rules()
    for record in RECORDS:
        assert builder.label(rules, record["input"]) == record["expected_output"], record["id"]


def test_v014_shortcuts_and_gaps_are_covered():
    coverage = builder.coverage(RECORDS)
    assert all(count > 0 for count in coverage.values()), coverage
    # A missing moisture key alone must never imply missing_moisture.
    for record in RECORDS:
        if "missing_moisture" in record["expected_output"]["data_quality_labels"]:
            assert any(f in record["input"]["expected_fields"] for f in builder.MOISTURE_FIELDS)


def test_no_holdout_inputs_or_invalid_tokens_leak_into_training_data():
    holdout = {json.dumps(r["input"], sort_keys=True) for r in expanded_cases()}
    holdout_tokens = [True, "broken", "NaN", "Infinity", {}]
    for record in RECORDS:
        assert json.dumps(record["input"], sort_keys=True) not in holdout
        for value in record["input"]["sensor"].values():
            assert not any(value == token and type(value) is type(token) for token in holdout_tokens), record["id"]
