"""VPD in the tomato rules, and parity between the two copies of those rules.

The model-router (app/tomato_reasoner.py) and the safety-checker (app/tomato_rules.py) each
carry derive_tomato_risk; they must give identical results.
"""

import importlib.util
import random
from pathlib import Path

from app import reasoner_thresholds as thresholds
from app.nutrient_ph_ec import derive_nutrient_ph_ec
from app.tomato_reasoner import derive_tomato_risk, vapour_pressure_deficit_kpa

_RULES = Path(__file__).resolve().parents[2] / "safety-checker" / "app" / "tomato_rules.py"
_SPEC = importlib.util.spec_from_file_location("safety_checker_tomato_rules", _RULES)
safety_rules = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(safety_rules)


def _input(**updates):
    base = {"system_type": "controlled_greenhouse", "crop": "tomato", "growth_stage": "fruiting",
            "air_temperature_c": 24.0, "humidity_pct": 68.0, "ph": 6.2, "ec_ms_cm": 2.4,
            "substrate_temperature_c": 23.0, "substrate_moisture_pct": 45.0, "actuator_states": {}}
    base.update(updates)
    return base


def test_vpd_values_match_fao56():
    # FAO-56 Table 2.3: saturation vapour pressure 2.985 kPa at 24 C (table rounding differs by 0.001).
    assert abs(vapour_pressure_deficit_kpa(24.0, 0.0) - 2.985) <= 0.002
    assert vapour_pressure_deficit_kpa(24.0, 68.0) == 0.955
    assert vapour_pressure_deficit_kpa(20.0, 100.0) == 0.0


def test_vpd_is_none_for_missing_or_implausible_readings():
    for temp, rh in ((None, 60.0), (24.0, None), (True, 60.0), (24.0, "60"), (24.0, 120.0),
                     (24.0, -1.0), (80.0, 60.0), (float("nan"), 60.0)):
        assert vapour_pressure_deficit_kpa(temp, rh) is None


def test_cool_humid_night_flags_fungal_pressure_below_85_percent():
    result = derive_tomato_risk(_input(air_temperature_c=17.0, humidity_pct=80.0))
    assert result["vpd_kpa"] < 0.4
    assert "fungal_pressure" in result["risk_labels"]
    assert any("low VPD" in check for check in result["safe_next_checks"])


def test_normal_day_has_no_vpd_label_or_check():
    result = derive_tomato_risk(_input())
    assert result["vpd_kpa"] == 0.955
    assert result["risk_labels"] == []
    assert not any("VPD" in check for check in result["safe_next_checks"])


def test_high_vpd_adds_a_check_but_no_label():
    result = derive_tomato_risk(_input(air_temperature_c=28.0, humidity_pct=35.0))
    assert result["vpd_kpa"] >= 1.6
    assert result["risk_labels"] == []
    assert any("high VPD" in check for check in result["safe_next_checks"])


def test_humidity_rule_still_applies_without_double_checks():
    result = derive_tomato_risk(_input(air_temperature_c=24.0, humidity_pct=90.0))
    assert result["risk_labels"] == ["fungal_pressure"]
    assert not any("low VPD" in check for check in result["safe_next_checks"])


def test_model_router_and_safety_checker_rules_agree():
    rng = random.Random(1004)
    systems = ["controlled_greenhouse", "hydroponic", "greenhouse_substrate", "hydroponic_greenhouse"]
    for _ in range(3000):
        record = _input(
            system_type=rng.choice(systems),
            air_temperature_c=rng.choice([None, round(rng.uniform(-10, 65), 1)]),
            humidity_pct=rng.choice([None, round(rng.uniform(-5, 105), 1)]),
            ph=rng.choice([None, round(rng.uniform(3, 10), 2)]),
            ec_ms_cm=rng.choice([None, round(rng.uniform(0, 11), 2)]),
            substrate_temperature_c=rng.choice([None, round(rng.uniform(5, 40), 1)]),
            substrate_moisture_pct=rng.choice([None, round(rng.uniform(0, 100), 1)]),
            actuator_states=rng.choice([{}, {"fan": False}, {"heater": True}]),
        )
        assert derive_tomato_risk(record) == safety_rules.derive_tomato_risk(record), record


def test_safety_checker_copy_agrees_on_vetoed_fields_not_expected_fields_and_odd_values():
    rng = random.Random(77)
    fields = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_temperature_c", "substrate_moisture_pct"]
    odd = [None, "9.9", "35", " 6.5 ", "abc", "", "nan", True, False, [], {}, float("nan"), float("inf")]
    states = ["on", 5, [], {}, {"fan": False}, {"screen_energy_pct": "90"}, {"screen_energy_pct": 90},
              {"screen_blackout_pct": "85", "water_flow_duration_min": "0"}, {"water_flow_duration_min": 0}]
    for _ in range(3000):
        record = _input(
            system_type=rng.choice(["controlled_greenhouse", "hydroponic", "greenhouse_substrate", "hydroponic_greenhouse", None, "x", ["y"]]),
            actuator_states=rng.choice(states),
            vetoed_fields=rng.sample(fields, rng.randint(0, 3)),
            not_expected_fields=rng.sample(fields, rng.randint(0, 3)),
            humidity_pct=rng.choice([90.0, "90", 60.0, 20.0]),
            substrate_moisture_pct=rng.choice([20.0, "20", 45.0, 5.0]),
        )
        for field in rng.sample(fields, rng.randint(0, 3)):
            record[field] = rng.choice(odd)
        assert derive_tomato_risk(record) == safety_rules.derive_tomato_risk(record), record


def test_safety_checker_copy_agrees_at_every_threshold():
    boundaries = {
        "ph": [thresholds.PH_ANOMALY_LOW, thresholds.PH_ANOMALY_HIGH, thresholds.PH_HIGH, thresholds.PH_LOW],
        "ec_ms_cm": [thresholds.EC_ANOMALY_LOW, thresholds.EC_ANOMALY_HIGH, thresholds.EC_HIGH,
                     thresholds.EC_LOW_HYDROPONIC, thresholds.EC_LOW_SUBSTRATE],
    }
    for system_type in ("controlled_greenhouse", "hydroponic_greenhouse", "hydroponic", "greenhouse_substrate", "soil_field"):
        for field, limits in boundaries.items():
            for limit in limits:
                for value in (limit - 0.001, limit, limit + 0.001):
                    record = _input(system_type=system_type, **{field: value})
                    assert derive_tomato_risk(record) == safety_rules.derive_tomato_risk(record), (field, value)


def test_system_types_are_the_same_in_every_copy_and_in_both_reasoners():
    assert safety_rules.HYDROPONIC_SYSTEM_TYPES == thresholds.HYDROPONIC_SYSTEM_TYPES
    for system_type in sorted(thresholds.HYDROPONIC_SYSTEM_TYPES):
        tomato = derive_tomato_risk(_input(system_type=system_type, ec_ms_cm=0.3))
        nutrient = derive_nutrient_ph_ec({"sensor": {"ph": 6.2, "ec_ms_cm": 0.3}, "system_type": system_type,
                                          "expected_fields": ["ph", "ec_ms_cm"]})
        assert "low_ec" in tomato["risk_labels"], system_type
        assert "low_ec" in nutrient["nutrient_risk_labels"], system_type
    soil = derive_nutrient_ph_ec({"sensor": {"ph": 6.2, "ec_ms_cm": 0.3}, "system_type": "soil_field",
                                  "expected_fields": ["ph", "ec_ms_cm"]})
    assert "low_ec" not in soil["nutrient_risk_labels"]
