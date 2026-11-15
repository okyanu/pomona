"""Multi-device zones, slice 2 (docs/design/multi-device-zones-slice2.md 2.3): the sensor-check results of a zone's
devices (`known_vetoed_fields`, `known_data_quality_labels`, `known_safe_next_checks`) are merged into the sensor quality
before the gate, in the guarded pipeline and in the shared chain, which also takes `device_fields`. Absent keys change
nothing."""

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app import pipeline
from app.main import PipelineEvaluateRequest, SharedReasonerChainRequest, app
from app.shared_chain import run_shared_reasoner_chain
from app.trust_gate import NEEDS_VERIFICATION, ROUTINE_CHECK, merge_known_checks

NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
FARM = {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"}
ZONE_FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"]
# What a zone snapshot looks like to the router: readings from two devices, no device_id.
SNAPSHOT = {"timestamp": "2026-10-06T08:58:00Z", "air_temperature_c": 24.0, "humidity_pct": 62.0, "ph": 6.0,
            "ec_ms_cm": 2.2, "substrate_moisture_pct": 45.0}
STUCK_CHECK = "inspect humidity_pct: near-zero variance may indicate a stuck or clipped probe"


@pytest.fixture(autouse=True)
def fixed_clock_without_audit(monkeypatch):
    monkeypatch.setattr(pipeline, "_now", lambda: NOW)
    monkeypatch.setattr(pipeline, "write_pipeline_audit", lambda record: None)


def evaluate(sensor=SNAPSHOT, **kwargs):
    return asyncio.run(pipeline.evaluate_pipeline(FARM, sensor, [], None, "test", "rules_only", **kwargs))


def chain(sensor=SNAPSHOT, expected=None, **kwargs):
    return run_shared_reasoner_chain(FARM, sensor, expected or [], None, "test", "rules_only", **kwargs)


def clean_quality(**overrides):
    return {"data_quality_labels": [], "missing_fields": [], "suspect_fields": [],
            "safe_next_checks": [ROUTINE_CHECK], "human_review_required": False,
            "rationale": "Critical sensor readings are present and inside plausible ranges."} | overrides


# --- trust_gate.merge_known_checks -----------------------------------------------------------------------

def test_nothing_known_changes_nothing_and_does_not_mutate():
    quality = clean_quality()
    snapshot = json.dumps(quality)
    for args in ((), ([], [], []), (None, None, None)):
        merged = merge_known_checks(quality, SNAPSHOT, *args)
        assert merged == quality and "from_device_checks" not in merged
    assert json.dumps(quality) == snapshot


def test_labels_are_added_except_global_and_missing_ones():
    merged = merge_known_checks(clean_quality(), SNAPSHOT, [], ["stuck_value", "stale_reading", "insufficient_context",
                                                                 "unit_mismatch", "missing_ph", "missing_critical_data", "noisy_signal_possible"], [])
    assert merged["data_quality_labels"] == ["stuck_value", "noisy_signal_possible"]
    assert merged["from_device_checks"] == {"data_quality_labels": ["stuck_value", "noisy_signal_possible"], "vetoed_fields": []}
    assert merged["human_review_required"] is True and merged["rationale"] == NEEDS_VERIFICATION
    assert merged["suspect_fields"] == [] and merged["safe_next_checks"] == [ROUTINE_CHECK]


def test_a_label_the_router_already_raised_is_not_added_twice_or_reported():
    local = clean_quality(data_quality_labels=["stuck_value"], suspect_fields=["humidity_pct"],
                          safe_next_checks=[STUCK_CHECK], human_review_required=True, rationale=NEEDS_VERIFICATION)
    merged = merge_known_checks(local, SNAPSHOT, ["humidity_pct"], ["stuck_value"], [STUCK_CHECK])
    assert merged == local and "from_device_checks" not in merged


def test_a_veto_is_added_only_for_a_field_the_snapshot_holds():
    sensor = {k: v for k, v in SNAPSHOT.items() if k != "ph"}
    merged = merge_known_checks(clean_quality(), sensor, ["humidity_pct", "ph", "nonsense_field"], [], [])
    assert merged["suspect_fields"] == ["humidity_pct"]  # ph is not held: that is the router's own missing-field call
    assert merged["from_device_checks"] == {"data_quality_labels": [], "vetoed_fields": ["humidity_pct"]}
    assert merged["human_review_required"] is True
    assert merged["data_quality_labels"] == [] and merged["rationale"] == clean_quality()["rationale"]  # no label added
    assert merge_known_checks(clean_quality(), {**SNAPSHOT, "ph": None}, ["ph"], [], [])["suspect_fields"] == []


def test_checks_are_appended_once_and_routine_monitoring_goes():
    merged = merge_known_checks(clean_quality(), SNAPSHOT, [], [], [STUCK_CHECK, STUCK_CHECK, "verify the probe"])
    assert merged["safe_next_checks"] == [STUCK_CHECK, "verify the probe"]
    assert merged["human_review_required"] is True and "from_device_checks" in merged
    local = clean_quality(data_quality_labels=["impossible_ph"], safe_next_checks=["inspect pH probe"])
    merged = merge_known_checks(local, SNAPSHOT, [], [], ["inspect pH probe", "verify the probe"])
    assert merged["safe_next_checks"] == ["inspect pH probe", "verify the probe"]
    assert merged["rationale"] == local["rationale"]  # labels were not added to a clean result


def test_provenance_lists_only_what_was_added():
    local = clean_quality(data_quality_labels=["impossible_ph"], suspect_fields=["ph"], human_review_required=True,
                          rationale=NEEDS_VERIFICATION, safe_next_checks=["inspect pH probe"])
    merged = merge_known_checks(local, SNAPSHOT, ["ph", "humidity_pct"], ["impossible_ph", "stuck_value"], [])
    assert merged["from_device_checks"] == {"data_quality_labels": ["stuck_value"], "vetoed_fields": ["humidity_pct"]}
    assert merged["suspect_fields"] == ["ph", "humidity_pct"] and merged["data_quality_labels"] == ["impossible_ph", "stuck_value"]


# --- the guarded pipeline -------------------------------------------------------------------------------------

def test_a_carried_stuck_humidity_probe_is_not_used_and_named_in_the_reason():
    result = evaluate(device_fields=ZONE_FIELDS, known_vetoed_fields=["humidity_pct"],
                      known_data_quality_labels=["stuck_value"], known_safe_next_checks=[STUCK_CHECK])
    assert "stuck_value" in result["sensor_quality"]["data_quality_labels"]
    assert result["sensor_quality"]["from_device_checks"] == {"data_quality_labels": ["stuck_value"], "vetoed_fields": ["humidity_pct"]}
    assert result["trust_gate"]["trust_verdict"] == "partial" and result["trust_gate"]["vetoed_fields"] == ["humidity_pct"]
    assert result["trust_gate"]["reason"] == "humidity_pct failed the sensor check and were not used"
    assert STUCK_CHECK in result["final_decision"]["safe_next_checks"] and ROUTINE_CHECK not in result["sensor_quality"]["safe_next_checks"]
    assert result["sensor_quality"]["human_review_required"] is True and result["final_decision"]["human_review_required"] is True


def test_companion_groups_follow_a_carried_veto():
    sensor = {**SNAPSHOT, "previous_ph": 5.9}
    result = evaluate(sensor, known_vetoed_fields=["ph"])
    assert result["trust_gate"]["vetoed_fields"] == ["ph", "previous_ph"]
    air = evaluate({**SNAPSHOT, "backup_air_temperature_c": 24.1}, known_vetoed_fields=["air_temperature_c"])
    assert air["trust_gate"]["vetoed_fields"] == ["air_temperature_c", "backup_air_temperature_c"]


def test_every_expected_field_vetoed_is_cannot_confirm():
    result = evaluate(known_vetoed_fields=ZONE_FIELDS, known_data_quality_labels=["stuck_value"])
    assert result["trust_gate"]["trust_verdict"] == "cannot_confirm" and result["trust_gate"]["global_veto"] is False
    assert result["water_irrigation"]["irrigation_risk_labels"] == []  # neutral specialists
    assert sorted(result["trust_gate"]["vetoed_fields"]) == sorted(ZONE_FIELDS)
    some = evaluate(known_vetoed_fields=ZONE_FIELDS[:3])
    assert some["trust_gate"]["trust_verdict"] == "partial"


def test_a_carried_global_label_or_missing_label_never_vetoes_the_zone():
    result = evaluate(device_fields=ZONE_FIELDS, known_data_quality_labels=["stale_reading", "missing_ph", "unit_mismatch"])
    assert result["trust_gate"]["trust_verdict"] == "trusted" and result["trust_gate"]["global_veto"] is False
    assert result["sensor_quality"]["data_quality_labels"] == [] and "from_device_checks" not in result["sensor_quality"]


def test_a_veto_for_a_field_the_snapshot_lacks_is_not_a_veto():
    sensor = {k: v for k, v in SNAPSHOT.items() if k != "ec_ms_cm"}
    plain = evaluate(sensor, device_fields=ZONE_FIELDS)
    carried = evaluate(sensor, device_fields=ZONE_FIELDS, known_vetoed_fields=["ec_ms_cm"])
    assert carried["sensor_quality"]["missing_fields"] == ["ec_ms_cm"]  # the router's own call, from the snapshot itself
    assert "from_device_checks" not in carried["sensor_quality"]
    assert carried["trust_gate"] == plain["trust_gate"]


def test_known_checks_reach_the_specialists_only_through_the_mask():
    result = evaluate(known_vetoed_fields=["ec_ms_cm"])
    assert result["trust_gate"]["vetoed_fields"] == ["ec_ms_cm"]
    assert "high_ec" not in result["nutrient_ph_ec"]["nutrient_risk_labels"]
    high = evaluate({**SNAPSHOT, "ec_ms_cm": 6.0})
    assert "high_ec" in high["nutrient_ph_ec"]["nutrient_risk_labels"]
    assert "high_ec" not in evaluate({**SNAPSHOT, "ec_ms_cm": 6.0}, known_vetoed_fields=["ec_ms_cm"])["nutrient_ph_ec"]["nutrient_risk_labels"]


def test_absent_keys_give_byte_identical_output():
    def dump(result):
        result = dict(result)
        result.pop("pipeline_id")
        return json.dumps(result, sort_keys=True)

    for sensor in (SNAPSHOT, {**SNAPSHOT, "humidity_pct": None}, {**SNAPSHOT, "ph": 13.0}):
        plain = dump(evaluate(sensor))
        assert dump(evaluate(sensor, known_vetoed_fields=None, known_data_quality_labels=None, known_safe_next_checks=None)) == plain
        assert dump(evaluate(sensor, known_vetoed_fields=[], known_data_quality_labels=[], known_safe_next_checks=[])) == plain
        assert "from_device_checks" not in plain
        assert dump(evaluate(sensor, device_fields=ZONE_FIELDS, known_vetoed_fields=[])) == dump(evaluate(sensor, device_fields=ZONE_FIELDS))


# --- the shared chain ---------------------------------------------------------------------------------------------

def test_the_shared_chain_merges_the_same_way_and_narrows_to_device_fields():
    result = chain(known_vetoed_fields=["humidity_pct"], known_data_quality_labels=["stuck_value", "stale_reading"],
                   known_safe_next_checks=[STUCK_CHECK])
    assert result["sensor_quality"]["data_quality_labels"] == ["stuck_value"]
    assert result["sensor_quality"]["from_device_checks"] == {"data_quality_labels": ["stuck_value"], "vetoed_fields": ["humidity_pct"]}
    assert result["trust_gate"]["vetoed_fields"] == ["humidity_pct"] and result["trust_gate"]["trust_verdict"] == "partial"
    assert result["human_review_required"] is True
    every = chain(known_vetoed_fields=ZONE_FIELDS)
    assert every["trust_gate"]["trust_verdict"] == "cannot_confirm" and every["water_irrigation"]["irrigation_risk_labels"] == []


def test_the_shared_chain_expects_only_what_the_zones_devices_carry():
    climate = {"timestamp": "2026-10-06T08:58:00Z", "air_temperature_c": 24.0, "humidity_pct": 62.0}
    plain = chain(climate)
    assert {"missing_ph", "missing_ec"} <= set(plain["sensor_quality"]["data_quality_labels"])
    narrowed = chain(climate, device_fields=["air_temperature_c", "humidity_pct"])
    assert narrowed["sensor_quality"]["data_quality_labels"] == [] and narrowed["trust_gate"]["trust_verdict"] == "trusted"
    assert narrowed["sensor_quality"]["missing_fields"] == []
    explicit = chain(climate, expected=ZONE_FIELDS, device_fields=["air_temperature_c", "humidity_pct"])  # explicit wins
    assert "missing_ph" in explicit["sensor_quality"]["data_quality_labels"]
    # a zone field no device ever carried is not missing: no moisture probe in the zone
    no_moisture = {k: v for k, v in SNAPSHOT.items() if k != "substrate_moisture_pct"}
    carried = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
    assert chain(no_moisture, device_fields=carried)["trust_gate"]["trust_verdict"] == "trusted"
    assert chain(no_moisture)["trust_gate"]["trust_verdict"] == "partial"  # without device_fields: moisture is missing


def test_the_shared_chain_is_byte_identical_without_the_keys():
    for sensor in (SNAPSHOT, {**SNAPSHOT, "ph": None}):
        plain = json.dumps(chain(sensor), sort_keys=True)
        assert json.dumps(chain(sensor, device_fields=None, known_vetoed_fields=None, known_data_quality_labels=None,
                                known_safe_next_checks=None), sort_keys=True) == plain
        assert json.dumps(chain(sensor, known_vetoed_fields=[], known_data_quality_labels=[], known_safe_next_checks=[]),
                          sort_keys=True) == plain


# --- the request validators ---------------------------------------------------------------------------------

@pytest.mark.parametrize("model", [PipelineEvaluateRequest, SharedReasonerChainRequest])
def test_validators_on_both_requests(model):
    request = model(farm_context={}, sensor={}, device_fields=["ph", "nonsense"],
                    known_vetoed_fields=["humidity_pct", "bogus", 3, None, "soil_moisture_pct"],
                    known_data_quality_labels=["stuck_value", "Bad Label", "with-dash", "", 7, "x" * 65, "y" * 64, None],
                    known_safe_next_checks=["ok", "c" * 300, "c" * 301, 5, None])
    assert request.device_fields == ["ph"] and request.known_vetoed_fields == ["humidity_pct", "soil_moisture_pct"]
    assert request.known_data_quality_labels == ["stuck_value", "y" * 64]
    assert request.known_safe_next_checks == ["ok", "c" * 300]
    absent = model(farm_context={}, sensor={})
    assert (absent.device_fields, absent.known_vetoed_fields, absent.known_data_quality_labels, absent.known_safe_next_checks) == (None,) * 4
    capped = model(farm_context={}, sensor={}, known_data_quality_labels=["a" * (i + 1) for i in range(60)],
                   known_safe_next_checks=[f"check {i}" for i in range(30)])
    assert len(capped.known_data_quality_labels) == 50 and len(capped.known_safe_next_checks) == 20
    assert capped.known_safe_next_checks == [f"check {i}" for i in range(20)]
    for name in ("known_vetoed_fields", "known_data_quality_labels", "known_safe_next_checks", "device_fields"):
        with pytest.raises(ValueError):
            model(farm_context={}, sensor={}, **{name: "not a list"})


# --- the endpoints ----------------------------------------------------------------------------------------------------

def test_the_pipeline_endpoint_takes_the_keys():
    client = TestClient(app)
    body = {"farm_context": FARM, "sensor": SNAPSHOT, "mode": "rules_only", "device_fields": ZONE_FIELDS,
            "known_vetoed_fields": ["humidity_pct"], "known_data_quality_labels": ["stuck_value"],
            "known_safe_next_checks": [STUCK_CHECK]}
    response = client.post("/v1/pipeline/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()
    assert data["trust_gate"]["vetoed_fields"] == ["humidity_pct"] and "stuck_value" in data["sensor_quality"]["data_quality_labels"]
    assert data["sensor_quality"]["from_device_checks"]["vetoed_fields"] == ["humidity_pct"]
    assert client.post("/v1/pipeline/evaluate", json={**body, "known_vetoed_fields": "humidity_pct"}).status_code == 422


def test_the_shared_chain_endpoint_takes_the_keys():
    client = TestClient(app)
    climate = {"timestamp": "2026-10-06T08:58:00Z", "air_temperature_c": 24.0, "humidity_pct": 62.0}
    body = {"farm_context": FARM, "sensor": climate, "mode": "rules_only"}
    plain = client.post("/v1/reasoners/shared-chain", json=body)
    assert plain.status_code == 200 and "missing_ph" in plain.json()["sensor_quality"]["data_quality_labels"]
    keyed = client.post("/v1/reasoners/shared-chain", json={**body, "device_fields": ["air_temperature_c", "humidity_pct"],
                                                            "known_vetoed_fields": ["humidity_pct"],
                                                            "known_data_quality_labels": ["stuck_value"]})
    assert keyed.status_code == 200
    data = keyed.json()
    assert data["trust_gate"]["vetoed_fields"] == ["humidity_pct"] and data["sensor_quality"]["data_quality_labels"] == ["stuck_value"]
    assert client.post("/v1/reasoners/shared-chain", json={**body, "known_safe_next_checks": {"a": 1}}).status_code == 422
