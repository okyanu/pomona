"""A numeric string ("9.9") is read as its number by every specialist; anything non-numeric counts as missing.

sensor_quality.numeric() accepts "9.9", so the sensor check lets it through. The tomato, nutrient and water rules used
to compare the raw string and crashed the pipeline with a 500. A non-object `actuator_states` counts as absent.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.main import app
from app.nutrient_ph_ec import derive_nutrient_ph_ec
from app.tomato_reasoner import derive_tomato_risk
from app.water_irrigation import derive_water_irrigation_risk

client = TestClient(app)
FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"]


@pytest.fixture(autouse=True)
def _audit_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr("app.audit.settings.audit_log_path", tmp_path / "audit.jsonl")


def evaluate(sensor, farm_context=None):
    body = {
        "farm_context": {"crop": "tomato", "system_type": "controlled_greenhouse", "zone_id": "a", **(farm_context or {})},
        "sensor": {"air_temperature_c": 24.0, "humidity_pct": 60.0, "ph": 6.2, "ec_ms_cm": 2.4,
                   "substrate_moisture_pct": 45.0, "timestamp": datetime.now(timezone.utc).isoformat(), **sensor},
        "expected_fields": FIELDS,
    }
    response = client.post("/v1/pipeline/evaluate", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def test_numeric_string_ph_is_read_as_its_number():
    body = evaluate({"ph": "9.9"})
    assert "sensor_anomaly" in body["crop_risk"]["risk_labels"]
    assert "sensor_anomaly" in body["nutrient_ph_ec"]["nutrient_risk_labels"]


def test_numeric_string_air_temperature_is_read_as_its_number():
    body = evaluate({"air_temperature_c": "35"})
    assert "heat_stress" in body["crop_risk"]["risk_labels"]


def test_actuator_states_that_is_not_an_object_counts_as_absent():
    body = evaluate({"humidity_pct": 92.0}, {"actuator_states": "on"})
    assert "actuator_conflict" not in body["crop_risk"]["risk_labels"]


def test_numeric_string_actuator_state_is_read_as_its_number():
    body = evaluate({"humidity_pct": 92.0}, {"actuator_states": {"screen_energy_pct": "90"}})
    assert "actuator_conflict" in body["crop_risk"]["risk_labels"]


def test_numeric_string_moisture_is_read_as_its_number():
    body = evaluate({"substrate_moisture_pct": "5"})
    assert "low_moisture" in body["water_irrigation"]["irrigation_risk_labels"]
    assert "water_level_risk" in body["crop_risk"]["risk_labels"]


def test_non_numeric_value_counts_as_missing_not_as_a_crash():
    tomato = derive_tomato_risk({"system_type": "controlled_greenhouse", "air_temperature_c": "warm",
                                 "humidity_pct": 60, "ph": [], "ec_ms_cm": 2.4})
    assert tomato["missing_data"] == ["air_temperature_c", "ph"]
    nutrient = derive_nutrient_ph_ec({"sensor": {"ph": "acid", "ec_ms_cm": 2.4}, "expected_fields": ["ph", "ec_ms_cm"],
                                      "system_type": "controlled_greenhouse"})
    assert nutrient["missing_fields"] == ["ph"]
    water = derive_water_irrigation_risk({"sensor": {"substrate_moisture_pct": "wet"}, "farm_context": {"system_type": "x"},
                                          "expected_fields": ["substrate_moisture_pct"]})
    assert water["missing_fields"] == ["substrate_moisture_pct"]


def test_advisor_stub_reads_numeric_strings_instead_of_crashing():
    response = client.post("/v1/advisor/explain", json={
        "instruction": "Explain risks for this reading.",
        "sensor": {"air_temperature_c": "35", "humidity_pct": "90", "ph": "abc"},
    })
    assert response.status_code == 200
    assert any("High air temperature" in risk for risk in response.json()["likely_risks"])
