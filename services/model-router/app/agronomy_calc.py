"""Deterministic agronomic calculators: FAO-56 crop water demand and NPK
fertilizer stoichiometry.

These are pure calculation utilities (no LLM, no risk labels) meant to feed
numeric estimates into the water/nutrient reasoners, not to replace their
guarded risk classification.

References:
- Allen, R.G.; Pereira, L.S.; Raes, D.; Smith, M. (1998). "Crop
  Evapotranspiration - Guidelines for Computing Crop Water Requirements."
  FAO Irrigation and Drainage Paper 56. Rome: Food and Agriculture
  Organization of the United Nations. Full text (free, public UN
  publication): https://www.fao.org/4/x0490e/x0490e00.htm
  Chapter 2 covers the Penman-Monteith ETo equation (eq. 6-13) used below;
  chapter 6 covers crop coefficients (Kc) and ETc (eq. 58).
- Fertilizer nutrient-content percentages (N / P2O5 / K2O by weight) in
  FERTILIZER_ANALYSIS are standard fertilizer-grade analysis values, e.g.
  as tabulated by FAO's "Fertilizer and Plant Nutrition Bulletin" series
  and by land-grant university extension services (e.g. Cornell, Colorado
  State CMG nutrient-management guides); these are widely published
  reference numbers, not a single citable formula.
- P2O5-to-P and K2O-to-K elemental conversion factors are the standard
  IUPAC/agronomy constants (0.4364 and 0.8301 respectively).

Caveats (read before using this for real dosing/irrigation decisions):
- reference_et_penman_monteith approximates net radiation directly from
  the supplied solar radiation input rather than computing FAO-56's full
  net radiation balance (eq. 38-40); adequate for a rough estimate, not a
  substitute for the full calculation if precision matters.
- fertilizer_grams_for_target is a simplified sequential allocation
  (DAP covers P, SOP covers K, urea tops up remaining N), not a
  simultaneous multi-nutrient solve, and ignores background N/K/hardness
  already present in the source water.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WeatherInputs:
    """Daily weather inputs for the FAO-56 Penman-Monteith equation."""

    t_mean_c: float
    t_min_c: float
    t_max_c: float
    rh_mean_pct: float
    wind_speed_2m_ms: float
    solar_radiation_mj_m2_day: float
    elevation_m: float = 0.0


def saturation_vapor_pressure_kpa(temp_c: float) -> float:
    """FAO-56 eq. 11: saturation vapor pressure at a given temperature."""
    return 0.6108 * pow(2.71828, (17.27 * temp_c) / (temp_c + 237.3))


def slope_svp_curve(t_mean_c: float) -> float:
    """FAO-56 eq. 13: slope of the saturation vapor pressure curve (kPa/C)."""
    es = saturation_vapor_pressure_kpa(t_mean_c)
    return (4098 * es) / pow(t_mean_c + 237.3, 2)


def psychrometric_constant(elevation_m: float) -> float:
    """FAO-56 eq. 7/8: psychrometric constant (kPa/C) from station elevation."""
    pressure_kpa = 101.3 * pow((293 - 0.0065 * elevation_m) / 293, 5.26)
    return 0.665e-3 * pressure_kpa


def reference_et_penman_monteith(weather: WeatherInputs) -> float:
    """FAO-56 eq. 6: reference evapotranspiration ETo (mm/day).

    Simplified daily form; assumes solar_radiation_mj_m2_day already
    accounts for net radiation minus soil heat flux (G ~ 0 for daily steps,
    per FAO-56 guidance) is out of scope for this sketch, so Rn is
    approximated directly from the supplied radiation input.
    """
    delta = slope_svp_curve(weather.t_mean_c)
    gamma = psychrometric_constant(weather.elevation_m)
    es_min = saturation_vapor_pressure_kpa(weather.t_min_c)
    es_max = saturation_vapor_pressure_kpa(weather.t_max_c)
    es = (es_min + es_max) / 2
    ea = es * (weather.rh_mean_pct / 100.0)
    vpd = max(es - ea, 0.0)

    numerator = 0.408 * delta * weather.solar_radiation_mj_m2_day + gamma * (
        900 / (weather.t_mean_c + 273)
    ) * weather.wind_speed_2m_ms * vpd
    denominator = delta + gamma * (1 + 0.34 * weather.wind_speed_2m_ms)
    return max(numerator / denominator, 0.0)


def crop_evapotranspiration(eto_mm_day: float, kc: float) -> float:
    """FAO-56 eq. 58: ETc = ETo x Kc (mm/day)."""
    if kc < 0:
        raise ValueError("kc must be non-negative")
    return eto_mm_day * kc


def irrigation_volume_liters(
    etc_mm_day: float,
    area_m2: float,
    irrigation_efficiency: float = 0.9,
) -> float:
    """Depth (mm) over an area (m^2) converted to a daily irrigation volume
    (liters), inflated for system efficiency (e.g. drip ~0.9, sprinkler ~0.75).
    """
    if not 0 < irrigation_efficiency <= 1:
        raise ValueError("irrigation_efficiency must be in (0, 1]")
    liters_at_field = etc_mm_day * area_m2  # 1 mm over 1 m^2 == 1 liter
    return liters_at_field / irrigation_efficiency


# --- NPK fertilizer stoichiometry -------------------------------------------

# Nutrient content by weight fraction for common fertilizer salts.
# (N, P2O5, K2O) as fractions, standard fertilizer-grade analysis.
FERTILIZER_ANALYSIS = {
    "urea": {"N": 0.46, "P2O5": 0.0, "K2O": 0.0},
    "dap": {"N": 0.18, "P2O5": 0.46, "K2O": 0.0},  # diammonium phosphate
    "sop": {"N": 0.0, "P2O5": 0.0, "K2O": 0.50},  # sulfate of potash
    "can": {"N": 0.26, "P2O5": 0.0, "K2O": 0.0},  # calcium ammonium nitrate
}

# Conversion factors from oxide form to elemental form.
P2O5_TO_P = 0.4364
K2O_TO_K = 0.8301


@dataclass
class NpkTarget:
    """Target nutrient concentration for a fertigation batch."""

    n_ppm: float
    p_ppm: float
    k_ppm: float
    volume_liters: float


def fertilizer_grams_for_target(target: NpkTarget) -> dict[str, float]:
    """Back-calculate grams of urea/DAP/SOP needed for a target N-P-K (ppm)
    in a given water volume.

    Simplified sequential allocation (not a full linear solve): DAP first
    covers the P target (and contributes some N), SOP covers K, and urea
    tops up any remaining N. Sufficient for a first-pass dosing estimate;
    a real system should solve simultaneously and account for existing
    water hardness/alkalinity contributions to N/K.
    """
    if target.volume_liters <= 0:
        raise ValueError("volume_liters must be positive")
    for name, value in (("n_ppm", target.n_ppm), ("p_ppm", target.p_ppm), ("k_ppm", target.k_ppm)):
        if value < 0:
            raise ValueError(f"{name} must be non-negative")

    total_p_mg = target.p_ppm * target.volume_liters
    total_k_mg = target.k_ppm * target.volume_liters
    total_n_mg = target.n_ppm * target.volume_liters

    p2o5_fraction = FERTILIZER_ANALYSIS["dap"]["P2O5"]
    dap_grams = (total_p_mg / P2O5_TO_P / p2o5_fraction) / 1000 if total_p_mg else 0.0
    n_from_dap_mg = dap_grams * 1000 * FERTILIZER_ANALYSIS["dap"]["N"]

    k2o_fraction = FERTILIZER_ANALYSIS["sop"]["K2O"]
    sop_grams = (total_k_mg / K2O_TO_K / k2o_fraction) / 1000 if total_k_mg else 0.0

    remaining_n_mg = max(total_n_mg - n_from_dap_mg, 0.0)
    urea_grams = (remaining_n_mg / FERTILIZER_ANALYSIS["urea"]["N"]) / 1000 if remaining_n_mg else 0.0

    return {
        "urea_g": round(urea_grams, 2),
        "dap_g": round(dap_grams, 2),
        "sop_g": round(sop_grams, 2),
    }
