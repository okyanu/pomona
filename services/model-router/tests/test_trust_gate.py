"""Sensor-quality veto: field masking, verdicts and the guarded pipeline."""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.nutrient_ph_ec import derive_nutrient_ph_ec
from app.pipeline import evaluate_pipeline
from app.sensor_quality import derive_sensor_quality
from app.shared_chain import run_shared_reasoner_chain
from app.tomato_reasoner import derive_tomato_risk
from app.trust_gate import apply_sensor_veto
from app.water_irrigation import derive_water_irrigation_risk

FARM = {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"}
EXPECTED = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"]
NOW = datetime(2026, 10, 24, 12, tzinfo=timezone.utc)


def quality(**overrides):
    base = {"data_quality_labels": [], "missing_fields": [], "suspect_fields": []}
    return {**base, **overrides}


def packet(**overrides):
    base = {"air_temperature_c": 24.0, "humidity_pct": 60.0, "ph": 6.0, "ec_ms_cm": 2.0,
            "substrate_moisture_pct": 50.0, "substrate_temperature_c": 23.0, "timestamp": datetime.now(timezone.utc).isoformat()}
    return {**base, **overrides}


def run(sensor, history=None, expected=EXPECTED):
    return asyncio.run(evaluate_pipeline(FARM, sensor, expected, {"action_type": "continue_monitoring"},
                                         "test", "rules_only", history=history))


def domain_labels(result):
    return (result["water_irrigation"]["irrigation_risk_labels"], result["nutrient_ph_ec"]["nutrient_risk_labels"],
            result["crop_risk"]["risk_labels"])


def test_trusted_when_sensor_check_found_nothing():
    sensor = packet()
    masked, history, gate = apply_sensor_veto(sensor, [packet()], quality(), EXPECTED)
    assert masked == sensor and history[0]["ph"] == 6.0
    assert gate["trust_verdict"] == "trusted" and gate["vetoed_fields"] == [] and gate["global_veto"] is False


def test_suspect_field_is_removed_from_sensor_and_every_history_frame():
    frames = [packet(ph=6.0), packet(ph=6.1), None]
    masked, history, gate = apply_sensor_veto(
        packet(ph=13.0), frames, quality(data_quality_labels=["impossible_ph"], suspect_fields=["ph"]), EXPECTED)
    assert "ph" not in masked and masked["ec_ms_cm"] == 2.0
    assert all("ph" not in frame for frame in history if frame) and history[2] is None
    assert gate["trust_verdict"] == "partial" and gate["vetoed_fields"] == ["ph"]


def test_missing_field_is_vetoed_and_companions_follow_when_present():
    sensor = packet(ph=7.9, previous_ph=6.8, backup_air_temperature_c=36.0)
    masked, _, gate = apply_sensor_veto(
        sensor, [], quality(data_quality_labels=["sensor_drift_possible", "conflicting_readings"],
                            suspect_fields=["ph", "air_temperature_c"]), EXPECTED)
    assert {"ph", "previous_ph", "air_temperature_c", "backup_air_temperature_c"} == set(gate["vetoed_fields"])
    assert not {"ph", "previous_ph", "air_temperature_c", "backup_air_temperature_c"} & set(masked)
    _, _, gate = apply_sensor_veto(packet(), [], quality(data_quality_labels=["missing_ph"], missing_fields=["ph"]), EXPECTED)
    assert gate["vetoed_fields"] == ["ph"]  # absent companions are not invented


def test_global_veto_labels_and_timestamp_make_cannot_confirm():
    for labels, suspect in ((["stale_reading"], ["timestamp"]), (["insufficient_context"], []),
                            (["unit_mismatch"], ["air_temperature_c", "temperature_f"]), ([], ["timestamp"])):
        masked, _, gate = apply_sensor_veto(packet(), [], quality(data_quality_labels=labels, suspect_fields=suspect), EXPECTED)
        assert gate["trust_verdict"] == "cannot_confirm" and gate["global_veto"] is True
        assert set(EXPECTED) <= set(gate["vetoed_fields"]) and not set(EXPECTED) & set(masked)


def test_every_expected_field_vetoed_is_cannot_confirm_but_one_left_is_partial():
    all_bad = quality(data_quality_labels=["missing_ph"], missing_fields=["ph", "ec_ms_cm"])
    assert apply_sensor_veto(packet(), [], all_bad, ["ph", "ec_ms_cm"])[2]["trust_verdict"] == "cannot_confirm"
    assert apply_sensor_veto(packet(), [], all_bad, ["ph", "ec_ms_cm", "humidity_pct"])[2]["trust_verdict"] == "partial"


def test_real_quality_output_drives_the_gate():
    sensor = packet(ph=13.0)
    result = derive_sensor_quality(FARM, sensor, EXPECTED, now=datetime.now(timezone.utc))
    _, _, gate = apply_sensor_veto(sensor, [], result, EXPECTED)
    assert gate["trust_verdict"] == "partial" and "ph" in gate["vetoed_fields"]


def test_impossible_ph_yields_no_ph_label_but_other_fields_are_still_reasoned():
    result = run(packet(ph=13.0, humidity_pct=92.0))
    water, nutrient, crop = domain_labels(result)
    assert not {"high_ph", "low_ph", "sensor_anomaly", "nutrient_uptake_issue"} & set(nutrient)
    assert not {"high_ph", "low_ph", "sensor_anomaly", "missing_critical_data"} & set(crop)
    assert "fungal_pressure" in crop  # humidity was not vetoed
    assert result["trust_gate"]["trust_verdict"] == "partial"
    assert "ph" in result["trust_gate"]["vetoed_fields"]
    decision = result["final_decision"]
    assert decision["trust_verdict"] == "partial" and "ph" in decision["vetoed_fields"]
    assert decision["human_review_required"] is True and decision["risk_level"] == "high"
    assert "impossible_ph" in result["sensor_quality"]["data_quality_labels"]
    assert "13.0" not in result["agronomist"]["explanation"]
    assert result["input"]["sensor"]["ph"] == 13.0  # the original packet is still reported


def test_drifted_ec_is_not_reasoned_on_even_through_history():
    start = NOW - timedelta(hours=3)
    history = [packet(ec_ms_cm=ec, timestamp=(start + timedelta(minutes=20 * i)).isoformat())
               for i, ec in enumerate([2.0, 2.0, 2.0, 4.6, 4.7])]
    sensor = packet(ec_ms_cm=4.8)
    result = run(sensor, history)
    assert "baseline_drift_possible" in result["sensor_quality"]["data_quality_labels"]
    assert derive_nutrient_ph_ec({"sensor": sensor, "farm_context": FARM, "expected_fields": EXPECTED})[
        "nutrient_risk_labels"] == ["high_ec", "nutrient_uptake_issue"]  # what it used to say
    _, nutrient, crop = domain_labels(result)
    assert not {"high_ec", "low_ec", "nutrient_uptake_issue"} & set(nutrient + crop)
    assert result["final_decision"]["vetoed_fields"] == ["ec_ms_cm"]


def test_stale_timestamp_cannot_confirm_and_has_no_domain_labels():
    result = run(packet(ph=8.0, ec_ms_cm=5.0, humidity_pct=95.0, substrate_moisture_pct=10.0,
                        timestamp=(datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()))
    assert "stale_reading" in result["sensor_quality"]["data_quality_labels"]
    assert domain_labels(result) == ([], [], [])
    assert result["trust_gate"]["trust_verdict"] == "cannot_confirm" and result["trust_gate"]["global_veto"] is True
    assert result["final_decision"]["trust_verdict"] == "cannot_confirm"
    assert result["final_decision"]["human_review_required"] is True and result["final_decision"]["risk_level"] == "high"
    for key in ("water_irrigation", "nutrient_ph_ec"):  # result shapes the dashboard reads are kept
        assert result[key]["source"] == "sensor_veto" and result[key]["model_id"]
    assert result["crop_risk"]["risk_labels"] == [] and "vpd_kpa" in result["crop_risk"]


def test_clean_packet_is_trusted_and_matches_ungated_specialists():
    sensor = packet(ph=7.5, ec_ms_cm=4.6, humidity_pct=90.0, substrate_moisture_pct=20.0, air_temperature_c=31.0)
    result = run(sensor)
    assert result["sensor_quality"]["data_quality_labels"] == []
    assert result["trust_gate"] == {**result["trust_gate"], "trust_verdict": "trusted", "vetoed_fields": [], "global_veto": False}
    context = {"farm_context": FARM, "sensor": sensor, "expected_fields": EXPECTED}
    assert result["water_irrigation"]["irrigation_risk_labels"] == derive_water_irrigation_risk(context)["irrigation_risk_labels"]
    assert result["nutrient_ph_ec"]["nutrient_risk_labels"] == derive_nutrient_ph_ec(context)["nutrient_risk_labels"]
    assert result["crop_risk"]["risk_labels"] == derive_tomato_risk({**FARM, **sensor})["risk_labels"]
    assert {"high_ph", "high_ec", "fungal_pressure", "heat_stress", "low_moisture"} <= set(sum(domain_labels(result), []))


def test_actuator_gate_still_sees_the_original_sensor_and_quality(monkeypatch):
    from app import pipeline

    seen = {}
    real = pipeline.derive_actuator_gate
    monkeypatch.setattr(pipeline, "derive_actuator_gate", lambda data: seen.update(data) or real(data))
    run(packet(ph=13.0))
    assert seen["sensor"]["ph"] == 13.0 and "impossible_ph" in seen["sensor_quality"]["data_quality_labels"]


def test_shared_chain_applies_the_same_veto():
    sensor = packet(ph=None, substrate_moisture_pct=24.0)
    result = run_shared_reasoner_chain(FARM, sensor, EXPECTED, {"action_type": "continue_monitoring"}, "test", "rules_only")
    assert result["trust_gate"]["trust_verdict"] == "partial"
    assert "low_moisture" in result["water_irrigation"]["irrigation_risk_labels"]
    bad = run_shared_reasoner_chain({"crop": "tomato"}, sensor, EXPECTED, None, "test", "rules_only")
    assert bad["trust_gate"]["trust_verdict"] == "cannot_confirm"
    assert bad["water_irrigation"]["irrigation_risk_labels"] == []
