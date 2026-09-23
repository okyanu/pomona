import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from eval_identity import neutral_zone
from prepare_sensor_quality_training import prepare
from sensor_quality_contract import render_prompt
from build_sensor_quality_release_candidate import build, cases


def test_ids_do_not_depend_on_bucket():
    import build_pomona_sensor_quality_clean_eval_dataset as sq
    import random
    assert sq.make_input("normal", 0, random.Random(1))[0]["farm_context"]["zone_id"] == sq.make_input("impossible_ph", 0, random.Random(1))[0]["farm_context"]["zone_id"] == neutral_zone(0)
    for name in ("sensor_quality", "safety_triage", "actuator_command_gate", "water_irrigation_v0_1_6"):
        code = (Path(__file__).resolve().parents[1] / f"build_pomona_{name}_clean_eval_dataset.py").read_text()
        assert '"zone_id": neutral_zone(index)' in code


def test_prepared_prompts_preserve_raw_input(tmp_path):
    records = cases()[:2]
    records[0]["input"]["sensor"].pop("ph", None)
    records[1]["input"]["sensor"]["ph"] = None
    source, dest = tmp_path / "source.jsonl", tmp_path / "prepared.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in records))
    assert prepare(source, dest)["rows"] == 2
    outputs = [json.loads(line) for line in dest.read_text().splitlines()]
    for record, output in zip(records, outputs):
        assert output["prompt"] == render_prompt(record["input"])
        assert '"review_status"' not in output["prompt"] and '"bucket"' not in output["prompt"]
    with pytest.raises(FileExistsError): prepare(source, dest)


def test_new_candidate_is_not_release_approved(tmp_path):
    manifest = build(tmp_path / "holdout")
    assert manifest["cases"] == 56 and not manifest["release_approved"]
    with pytest.raises(FileExistsError): build(tmp_path / "holdout")
