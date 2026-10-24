import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app import pipeline
from app.expected_fields import expected_fields_for
from app.shared_chain import run_shared_reasoner_chain

CORE = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
NOW = datetime(2026, 10, 6, 9, 0, 0, tzinfo=timezone.utc)
# Non-moisture readings only: what a recirculating system reports.
HYDROPONIC_SENSOR = {"timestamp": "2026-10-06T08:58:00Z", "air_temperature_c": 22.0, "humidity_pct": 62.0,
                     "ph": 5.9, "ec_ms_cm": 1.8}


@pytest.fixture(autouse=True)
def fixed_clock_without_audit(monkeypatch):
    monkeypatch.setattr(pipeline, "_now", lambda: NOW)
    monkeypatch.setattr(pipeline, "write_pipeline_audit", lambda record: None)


def evaluate(system_type, sensor):
    farm = {"crop": "tomato", "system_type": system_type, "growth_stage": "vegetative"}
    return asyncio.run(pipeline.evaluate_pipeline(farm, sensor, [], None, "test", "rules_only"))


@pytest.mark.parametrize("system_type", [
    "hydroponic", "hydroponic_greenhouse", "hydroponic_dwc", "hydroponic_passive", "nft_aquaponic",
    "controlled_greenhouse", " Hydroponic ",
])
def test_recirculating_systems_expect_no_moisture(system_type):
    assert expected_fields_for({"system_type": system_type}, {}) == CORE


@pytest.mark.parametrize("system_type", ["greenhouse_substrate", "soil_field", "soil_pot", "something_new", "", None, 7])
def test_substrate_soil_and_unknown_systems_expect_moisture(system_type):
    assert expected_fields_for({"system_type": system_type}, {}) == [*CORE, "substrate_moisture_pct"]
    assert expected_fields_for({}, {}) == [*CORE, "substrate_moisture_pct"]


def test_moisture_field_is_the_one_the_packet_carries():
    farm = {"system_type": "greenhouse_substrate"}
    assert expected_fields_for(farm, {"soil_moisture_pct": 40}) == [*CORE, "soil_moisture_pct"]
    assert expected_fields_for(farm, {"root_zone_moisture_pct": 40}) == [*CORE, "root_zone_moisture_pct"]
    assert expected_fields_for(farm, {"soil_moisture_pct": 40, "substrate_moisture_pct": 41}) == [*CORE, "substrate_moisture_pct"]
    assert expected_fields_for(farm, {"soil_moisture_pct": None}) == [*CORE, "substrate_moisture_pct"]
    assert expected_fields_for(farm, {"soil_moisture_pct": 45, "substrate_moisture_pct": None}) == [*CORE, "soil_moisture_pct"]
    assert expected_fields_for(farm, {"ph": 6.0}) == [*CORE, "substrate_moisture_pct"]


def test_default_expected_fields_stays_importable():
    assert pipeline.DEFAULT_EXPECTED_FIELDS == [*CORE, "substrate_moisture_pct"]


def test_hydroponic_packet_without_moisture_is_trusted():
    result = evaluate("hydroponic", HYDROPONIC_SENSOR)
    assert result["input"]["expected_fields"] == CORE
    assert result["trust_gate"]["trust_verdict"] == "trusted"
    assert result["final_decision"]["vetoed_fields"] == []
    assert result["sensor_quality"]["data_quality_labels"] == []
    assert "missing_moisture" not in result["sensor_quality"]["data_quality_labels"]
    # No moisture expected and none sent means no moisture reasoning, not "missing moisture".
    assert result["water_irrigation"]["irrigation_risk_labels"] == []
    assert result["water_irrigation"]["missing_fields"] == []
    assert result["crop_risk"]["missing_data"] == []


def test_substrate_packet_without_moisture_still_reports_it_missing():
    result = evaluate("greenhouse_substrate", HYDROPONIC_SENSOR)
    assert "missing_moisture" in result["sensor_quality"]["data_quality_labels"]
    assert result["sensor_quality"]["missing_fields"] == ["substrate_moisture_pct"]
    assert result["trust_gate"]["trust_verdict"] == "partial"


def test_substrate_packet_with_only_soil_moisture_is_not_missing_moisture():
    sensor = {**HYDROPONIC_SENSOR, "soil_moisture_pct": 45.0}
    result = evaluate("greenhouse_substrate", sensor)
    assert result["input"]["expected_fields"] == [*CORE, "soil_moisture_pct"]
    assert "missing_moisture" not in result["sensor_quality"]["data_quality_labels"]
    assert result["trust_gate"]["trust_verdict"] == "trusted"


def test_core_shaped_packet_with_null_substrate_moisture_is_trusted():
    # Core's SensorEvent dumps substrate_moisture_pct as null next to the required soil_moisture_pct.
    sensor = {**HYDROPONIC_SENSOR, "soil_moisture_pct": 45.0, "substrate_moisture_pct": None}
    result = evaluate("greenhouse_substrate", sensor)
    assert result["input"]["expected_fields"] == [*CORE, "soil_moisture_pct"]
    assert result["sensor_quality"]["data_quality_labels"] == []
    assert result["trust_gate"]["trust_verdict"] == "trusted"


def test_explicit_expected_fields_are_still_respected():
    farm = {"crop": "tomato", "system_type": "hydroponic", "growth_stage": "vegetative"}
    result = asyncio.run(pipeline.evaluate_pipeline(
        farm, HYDROPONIC_SENSOR, ["substrate_moisture_pct"], None, "test", "rules_only"))
    assert result["input"]["expected_fields"] == ["substrate_moisture_pct"]
    assert "missing_moisture" in result["sensor_quality"]["data_quality_labels"]


def test_shared_chain_picks_expected_fields_the_same_way():
    farm = {"crop": "tomato", "system_type": "hydroponic"}
    sensor = {**HYDROPONIC_SENSOR, "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    result = run_shared_reasoner_chain(farm, sensor, [], None, "test", "rules_only")
    assert result["sensor_quality"]["data_quality_labels"] == []
    assert result["trust_gate"]["trust_verdict"] == "trusted"
    assert result["water_irrigation"]["irrigation_risk_labels"] == []
