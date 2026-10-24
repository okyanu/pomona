import json
import subprocess
import sys
from pathlib import Path


def test_replay_passes_with_temporal_history():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/benchmark_sensor_fault_replay.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    report = json.loads(result.stdout)
    rows = {row["scenario"]: row for row in report["scenarios"]}
    assert len(rows) == 12
    assert report["model_quality_evaluation"] is False
    assert rows["normal"]["false_positive"] == 0
    assert rows["spike"]["true_positive"] == 1
    assert rows["missing_ph"]["true_positive"] == 6
    assert rows["conflicting_probes"]["true_positive"] == 6
    assert rows["sustained_impossible_ph"]["true_positive"] == 6
    assert rows["dropout"]["false_negative"] == 0
    assert rows["dropout"]["true_positive"] == 3
    assert rows["slow_drift"]["false_negative"] == 0
    assert rows["stuck_value"]["false_negative"] == 0
    assert rows["stuck_value"]["true_positive"] >= 4
    assert report["passed"] is True
    assert result.returncode == 0


def test_replay_reports_trusted_wrong_metric_and_the_undetectable_offset():
    root = Path(__file__).resolve().parents[3]
    report = json.loads(subprocess.run([sys.executable, str(root / "scripts/benchmark_sensor_fault_replay.py")], cwd=root,
                                       capture_output=True, text=True, timeout=20).stdout)
    rows = {row["scenario"]: row for row in report["scenarios"]}
    assert {"faulty_frames", "trusted_wrong_ungated", "trusted_wrong_gated", "trusted_wrong_rate_gated",
            "trusted_wrong_rate_ungated"} <= set(report["totals"]) and "trusted_wrong_gated" in report["metric_definitions"]
    offset = rows["plausible_offset"]
    assert offset["detectable"] is False and offset["false_negative"] == offset["faulty_frames"] == 12
    assert offset["trusted_wrong_ungated"] == offset["trusted_wrong_gated"] > 0  # the veto cannot see it
    assert offset["trusted_wrong_cards_ungated"] == offset["trusted_wrong_cards_gated"] == 12
    assert all(rows[name]["detectable"] for name in rows if name != "plausible_offset")
    original = ("spike", "missing_ph", "conflicting_probes", "dropout", "slow_drift", "stuck_value", "sustained_impossible_ph")
    for name in original:  # the specialists' own impossible-value guards already kept these from making a card
        assert rows[name]["wrong_cards_ungated"] == rows[name]["wrong_cards_gated"] == 0
        assert rows[name]["trusted_wrong_gated"] == rows[name]["trusted_wrong_ungated"] == rows[name]["wrong_gated"] == 0
    assert rows["spike"]["wrong_ungated"] == 1 and rows["missing_ph"]["wrong_ungated"] == 6
    assert rows["sustained_impossible_ph"]["partial_frames"] == 6 and rows["dropout"]["cannot_confirm_frames"] == 3
    # Plausible but faulty readings: the old pipeline made a wrong card on every injected frame that crossed a
    # threshold; the veto removes them once the sensor check fires. Frames before it fires stay wrong and trusted.
    assert (rows["ph_jump"]["wrong_cards_ungated"], rows["ph_jump"]["wrong_cards_gated"]) == (6, 1)
    assert (rows["ec_drift_high"]["wrong_cards_ungated"], rows["ec_drift_high"]["wrong_cards_gated"]) == (5, 0)
    assert (rows["stuck_humidity_high"]["wrong_cards_ungated"], rows["stuck_humidity_high"]["wrong_cards_gated"]) == (6, 2)
    for name in ("ph_jump", "ec_drift_high", "stuck_humidity_high"):
        assert rows[name]["detectable"] and rows[name]["false_positive"] == rows[name]["false_negative"] == 0
        assert rows[name]["trusted_wrong_cards_gated"] <= rows[name]["wrong_cards_gated"] < rows[name]["wrong_cards_ungated"]
    totals = report["totals_detectable"]
    assert (totals["wrong_cards_ungated"], totals["wrong_cards_gated"], totals["trusted_wrong_cards_gated"]) == (17, 3, 3)
    assert (report["totals"]["trusted_wrong_cards_gated"], report["totals"]["faulty_frames"]) == (15, 70)
    assert report["totals"]["trusted_wrong_rate_gated"] == round(15 / 70, 4)


def test_replay_gate_matches_the_guarded_pipeline(monkeypatch):
    import asyncio
    import importlib.util
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app import pipeline

    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("fault_replay", root / "scripts/benchmark_sensor_fault_replay.py")
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    monkeypatch.setattr(pipeline, "write_pipeline_audit", lambda record: None)
    checked = 0
    for name, frames in replay.scenarios():
        history = []
        for now, sensor, faulty, injected, clean in frames:
            monkeypatch.setattr(pipeline, "_now", lambda now=now: now)
            result = asyncio.run(pipeline.evaluate_pipeline(
                replay.FARM, sensor, replay.FIELDS, None, "test", "rules_only", history=history))
            quality = replay.derive_sensor_quality(replay.FARM, sensor, replay.FIELDS, now=now, history=history)
            labels, gate = replay.gated_labels(sensor, history, quality)
            assert gate == result["trust_gate"], (name, now)
            assert labels == sorted({*result["water_irrigation"]["irrigation_risk_labels"],
                                     *result["nutrient_ph_ec"]["nutrient_risk_labels"],
                                     *result["crop_risk"]["risk_labels"]}), (name, now)
            history.append(dict(sensor))
            checked += 1
    assert checked == 144
