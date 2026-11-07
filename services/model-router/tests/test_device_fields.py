"""Multi-device zones, slice 1: `device_fields` narrows the expected fields to what one device carries.

docs/design/multi-device-zones.md 1.3. Without `device_fields` (or with an explicit `expected_fields`) nothing changes.
"""

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
from app.expected_fields import MOISTURE_FIELDS, expected_fields_for, narrow_to_device
from app.main import PipelineEvaluateRequest, app
from app.tomato_reasoner import derive_tomato_risk, missing_input_fields

CORE = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
FULL = [*CORE, "substrate_moisture_pct"]
NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
FARM = {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"}
CLIMATE_SENSOR = {"timestamp": "2026-10-06T08:58:00Z", "air_temperature_c": 24.0, "humidity_pct": 62.0}
SUBSTRATE_SENSOR = {"timestamp": "2026-10-06T08:58:00Z", "ph": 6.0, "ec_ms_cm": 2.2, "substrate_moisture_pct": 45.0}


@pytest.fixture(autouse=True)
def fixed_clock_without_audit(monkeypatch):
    monkeypatch.setattr(pipeline, "_now", lambda: NOW)
    monkeypatch.setattr(pipeline, "write_pipeline_audit", lambda record: None)


def evaluate(sensor, expected=None, device_fields=None, farm=FARM):
    kwargs = {} if device_fields is None else {"device_fields": device_fields}
    return asyncio.run(pipeline.evaluate_pipeline(farm, sensor, expected or [], None, "test", "rules_only", **kwargs))


def test_narrow_keeps_only_the_fields_the_device_carries():
    assert narrow_to_device(FULL, ["air_temperature_c", "humidity_pct"]) == ["air_temperature_c", "humidity_pct"]
    assert narrow_to_device(FULL, ["ph", "ec_ms_cm", "substrate_moisture_pct"]) == ["ph", "ec_ms_cm", "substrate_moisture_pct"]
    assert narrow_to_device(FULL, [*CORE, "substrate_moisture_pct", "substrate_temperature_c"]) == FULL


@pytest.mark.parametrize("carried", MOISTURE_FIELDS)
def test_any_moisture_name_keeps_the_moisture_field(carried):
    for expected_name in MOISTURE_FIELDS:
        assert narrow_to_device([*CORE, expected_name], ["ph", carried]) == ["ph", expected_name]


def test_empty_result_falls_back_to_the_full_list():
    assert narrow_to_device(FULL, ["substrate_temperature_c"]) == FULL
    assert narrow_to_device(FULL, []) == FULL
    assert narrow_to_device(CORE, ["substrate_moisture_pct"]) == CORE  # a hydroponic zone has no moisture field


def test_request_keeps_only_known_field_names():
    request = PipelineEvaluateRequest(farm_context={}, sensor={}, device_fields=["ph", "nonsense", 3, "soil_moisture_pct", None])
    assert request.device_fields == ["ph", "soil_moisture_pct"]
    assert PipelineEvaluateRequest(farm_context={}, sensor={}).device_fields is None


def test_climate_only_and_substrate_only_devices_get_no_missing_data_labels():
    climate = evaluate(CLIMATE_SENSOR, device_fields=["air_temperature_c", "humidity_pct"])
    substrate = evaluate(SUBSTRATE_SENSOR, device_fields=["ph", "ec_ms_cm", "substrate_moisture_pct"])
    for result in (climate, substrate):
        labels = [*result["sensor_quality"]["data_quality_labels"], *result["crop_risk"]["risk_labels"]]
        assert not [label for label in labels if label.startswith("missing_")], labels
        assert result["sensor_quality"]["missing_fields"] == []
        assert result["trust_gate"]["trust_verdict"] == "trusted"
    assert climate["input"]["expected_fields"] == ["air_temperature_c", "humidity_pct"]
    assert substrate["input"]["expected_fields"] == ["ph", "ec_ms_cm", "substrate_moisture_pct"]


def test_without_narrowing_the_same_packets_report_missing_data():
    labels = evaluate(CLIMATE_SENSOR)["sensor_quality"]["data_quality_labels"]
    assert {"missing_ph", "missing_ec"} <= set(labels)
    assert "missing_critical_data" in evaluate(CLIMATE_SENSOR)["crop_risk"]["risk_labels"]


def test_a_probe_the_device_reported_before_is_still_expected():
    result = evaluate({k: v for k, v in SUBSTRATE_SENSOR.items() if k != "ec_ms_cm"},
                      device_fields=["ph", "ec_ms_cm", "substrate_moisture_pct"])
    assert "missing_ec" in result["sensor_quality"]["data_quality_labels"]
    assert result["trust_gate"]["vetoed_fields"] == ["ec_ms_cm"]
    # the tomato reasoner skips a vetoed field, so no second report of it
    assert "missing_critical_data" not in result["crop_risk"]["risk_labels"]


def test_a_missing_substrate_temperature_is_critical_only_when_the_device_reported_one():
    sensor = {**SUBSTRATE_SENSOR, "substrate_temperature_c": None}
    carried = ["ph", "ec_ms_cm", "substrate_moisture_pct", "substrate_temperature_c"]
    assert "missing_critical_data" in evaluate(sensor, device_fields=carried)["crop_risk"]["risk_labels"]
    assert "missing_critical_data" not in evaluate(sensor, device_fields=carried[:3])["crop_risk"]["risk_labels"]


def test_explicit_expected_fields_win():
    result = evaluate(CLIMATE_SENSOR, expected=FULL, device_fields=["air_temperature_c", "humidity_pct"])
    assert result["input"]["expected_fields"] == FULL
    assert "missing_ph" in result["sensor_quality"]["data_quality_labels"]
    assert "missing_critical_data" in result["crop_risk"]["risk_labels"]


def test_absent_device_fields_gives_byte_identical_output():
    for sensor in (CLIMATE_SENSOR, SUBSTRATE_SENSOR):
        plain = evaluate(sensor)
        for name in ("pipeline_id",):
            plain.pop(name)
        again = evaluate(sensor, device_fields=None)
        again.pop("pipeline_id")
        assert json.dumps(plain, sort_keys=True) == json.dumps(again, sort_keys=True)
    assert "not_expected_fields" not in json.dumps(evaluate(SUBSTRATE_SENSOR)["input"])


def test_a_device_that_carries_everything_keeps_todays_behaviour():
    full_packet = {**SUBSTRATE_SENSOR, "air_temperature_c": 24.0, "humidity_pct": 62.0}
    carried = [*CORE, "substrate_moisture_pct"]
    plain, narrowed = evaluate(full_packet), evaluate(full_packet, device_fields=carried)
    assert "missing_critical_data" in plain["crop_risk"]["risk_labels"]  # no substrate temperature: today's rule
    assert "missing_critical_data" in narrowed["crop_risk"]["risk_labels"]
    assert narrowed["input"]["expected_fields"] == FULL


def test_a_device_that_carries_none_of_the_expected_fields_keeps_todays_behaviour():
    sensor = {"timestamp": "2026-10-06T08:58:00Z", "substrate_temperature_c": 20.0}
    plain, narrowed = evaluate(sensor), evaluate(sensor, device_fields=["substrate_temperature_c"])
    assert narrowed["input"]["expected_fields"] == FULL
    assert narrowed["crop_risk"]["risk_labels"] == plain["crop_risk"]["risk_labels"]
    assert narrowed["sensor_quality"]["data_quality_labels"] == plain["sensor_quality"]["data_quality_labels"]
    assert narrowed["trust_gate"] == plain["trust_gate"] and narrowed["final_decision"] == plain["final_decision"]


def test_water_and_nutrient_specialists_use_the_narrowed_list(monkeypatch):
    seen = {}
    for name in ("route_water_irrigation_reasoner", "route_nutrient_ph_ec_reasoner"):
        real = getattr(pipeline, name)

        async def spy(input_data, *args, _real=real, _name=name, **kwargs):
            seen[_name] = input_data["expected_fields"]
            return await _real(input_data, *args, **kwargs)

        monkeypatch.setattr(pipeline, name, spy)
    evaluate(SUBSTRATE_SENSOR, device_fields=["ph", "ec_ms_cm", "substrate_moisture_pct"])
    assert seen == {"route_water_irrigation_reasoner": ["ph", "ec_ms_cm", "substrate_moisture_pct"],
                    "route_nutrient_ph_ec_reasoner": ["ph", "ec_ms_cm", "substrate_moisture_pct"]}
    result = evaluate(CLIMATE_SENSOR, device_fields=["air_temperature_c", "humidity_pct"])
    assert seen["route_nutrient_ph_ec_reasoner"] == ["air_temperature_c", "humidity_pct"]
    assert "missing_critical_data" not in result["nutrient_ph_ec"]["nutrient_risk_labels"]
    assert "missing_moisture" not in result["water_irrigation"]["irrigation_risk_labels"]


def test_tomato_missing_input_fields_skips_not_expected_fields():
    base = {"system_type": "greenhouse_substrate", "air_temperature_c": 24.0}
    assert missing_input_fields(base) == ["humidity_pct", "ph", "ec_ms_cm", "substrate_temperature_c", "substrate_moisture_pct"]
    assert missing_input_fields({**base, "not_expected_fields": ["ph", "ec_ms_cm", "substrate_moisture_pct"]}) == [
        "humidity_pct", "substrate_temperature_c"]
    assert "missing_critical_data" not in derive_tomato_risk(
        {**base, "not_expected_fields": ["humidity_pct", "ph", "ec_ms_cm", "substrate_temperature_c",
                                          "substrate_moisture_pct"]})["risk_labels"]


def test_endpoint_accepts_device_fields():
    client = TestClient(app)
    body = {"farm_context": FARM, "sensor": CLIMATE_SENSOR, "mode": "rules_only",
            "device_fields": ["air_temperature_c", "humidity_pct"]}
    response = client.post("/v1/pipeline/evaluate", json=body)
    assert response.status_code == 200
    assert response.json()["input"]["expected_fields"] == ["air_temperature_c", "humidity_pct"]
    plain = client.post("/v1/pipeline/evaluate", json={k: v for k, v in body.items() if k != "device_fields"}).json()
    assert "missing_ph" in plain["sensor_quality"]["data_quality_labels"]
