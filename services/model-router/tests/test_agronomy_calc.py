import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

import pytest

from app.agronomy_calc import (
    NpkTarget,
    WeatherInputs,
    crop_evapotranspiration,
    fertilizer_grams_for_target,
    irrigation_volume_liters,
    psychrometric_constant,
    reference_et_penman_monteith,
    saturation_vapor_pressure_kpa,
)


def test_saturation_vapor_pressure_matches_known_value():
    # FAO-56 documents es(20C) = 2.338 kPa (Annex 1, worked constants).
    assert saturation_vapor_pressure_kpa(20.0) == pytest.approx(2.338, abs=0.001)


def test_psychrometric_constant_at_sea_level():
    # Standard tabulated value: ~0.0674 kPa/C at sea level, 20C.
    assert psychrometric_constant(0.0) == pytest.approx(0.0674, abs=0.001)


def test_reference_et_is_reasonable_and_monotonic_in_radiation():
    base = WeatherInputs(
        t_mean_c=29.2,
        t_min_c=25.6,
        t_max_c=34.8,
        rh_mean_pct=66,
        wind_speed_2m_ms=2.0,
        solar_radiation_mj_m2_day=14.0,
        elevation_m=2,
    )
    eto = reference_et_penman_monteith(base)
    # Hot, humid tropical day: a plausible ETo range, not an exact textbook match.
    assert 3.0 < eto < 9.0

    brighter = WeatherInputs(**{**base.__dict__, "solar_radiation_mj_m2_day": 20.0})
    assert reference_et_penman_monteith(brighter) > eto


def test_crop_et_scales_by_kc():
    assert crop_evapotranspiration(5.0, kc=1.15) == pytest.approx(5.75)
    with pytest.raises(ValueError):
        crop_evapotranspiration(5.0, kc=-1)


def test_irrigation_volume_accounts_for_efficiency():
    # 5 mm over 10 m^2 = 50 L at field, /0.9 efficiency.
    volume = irrigation_volume_liters(etc_mm_day=5.0, area_m2=10.0, irrigation_efficiency=0.9)
    assert volume == pytest.approx(55.56, abs=0.01)
    with pytest.raises(ValueError):
        irrigation_volume_liters(5.0, 10.0, irrigation_efficiency=0)


def test_fertilizer_grams_for_target_covers_npk():
    target = NpkTarget(n_ppm=150, p_ppm=50, k_ppm=200, volume_liters=100)
    grams = fertilizer_grams_for_target(target)
    assert grams["dap_g"] > 0
    assert grams["sop_g"] > 0
    assert grams["urea_g"] >= 0
    # DAP alone supplies P; check the P delivered matches the target.
    dap_p_mg = grams["dap_g"] * 1000 * 0.46 * 0.4364
    assert dap_p_mg == pytest.approx(target.p_ppm * target.volume_liters, rel=0.01)


def test_fertilizer_grams_rejects_negative_or_zero_volume():
    with pytest.raises(ValueError):
        fertilizer_grams_for_target(NpkTarget(n_ppm=10, p_ppm=0, k_ppm=0, volume_liters=0))
    with pytest.raises(ValueError):
        fertilizer_grams_for_target(NpkTarget(n_ppm=-1, p_ppm=0, k_ppm=0, volume_liters=10))
