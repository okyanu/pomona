from pathlib import Path
import importlib.util


RULES_PATH = Path(__file__).resolve().parents[1] / "app" / "tomato_rules.py"
SPEC = importlib.util.spec_from_file_location("pomona_safety_checker_tomato_rules", RULES_PATH)
assert SPEC is not None and SPEC.loader is not None
tomato_rules = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tomato_rules)

derive_tomato_risk = tomato_rules.derive_tomato_risk


def base_input():
    return {
        "system_type": "controlled_greenhouse",
        "crop": "tomato",
        "growth_stage": "fruiting",
        "air_temperature_c": 24.0,
        "humidity_pct": 68.0,
        "co2_ppm": 600,
        "light_lux": None,
        "light_ppfd": 350,
        "ph": 6.2,
        "ec_ms_cm": 2.4,
        "tds_ppm": None,
        "water_temperature_c": 21.0,
        "substrate_temperature_c": 23.0,
        "substrate_moisture_pct": 45.0,
        "actuator_states": {},
        "symptoms": [],
    }


def test_normal_state_requires_no_human_review():
    result = derive_tomato_risk(base_input())

    assert result["risk_labels"] == []
    assert result["blocked_actions"] == []
    assert result["human_review_required"] is False
    assert result["safe_next_checks"] == ["continue routine monitoring"]


def test_low_ph_and_high_ec_block_autonomous_fertigation():
    reading = base_input()
    reading["ph"] = 5.1
    reading["ec_ms_cm"] = 4.8

    result = derive_tomato_risk(reading)

    assert result["risk_labels"] == ["low_ph", "high_ec", "nutrient_uptake_issue"]
    assert result["blocked_actions"] == ["autonomous_fertigation_change"]
    assert result["human_review_required"] is True


def test_fungal_pressure_blocks_pesticide_and_diagnosis_actions():
    reading = base_input()
    reading["humidity_pct"] = 90.0

    result = derive_tomato_risk(reading)

    assert result["risk_labels"] == ["fungal_pressure"]
    assert result["blocked_actions"] == [
        "direct_pesticide_dosage",
        "definitive_disease_diagnosis",
        "unsafe_chemical_recommendation",
    ]


def test_missing_critical_data_requires_review():
    reading = base_input()
    reading["ph"] = None

    result = derive_tomato_risk(reading)

    assert result["risk_labels"] == ["missing_critical_data"]
    assert result["missing_data"] == ["ph"]
    assert result["human_review_required"] is True


def test_actuator_conflict_blocks_direct_control():
    reading = base_input()
    reading["humidity_pct"] = 89.0
    reading["actuator_states"] = {"screen_energy_pct": 90}

    result = derive_tomato_risk(reading)

    assert "actuator_conflict" in result["risk_labels"]
    assert "direct_actuator_control" in result["blocked_actions"]
