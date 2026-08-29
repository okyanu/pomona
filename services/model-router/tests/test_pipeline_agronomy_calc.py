import asyncio
import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.pipeline import evaluate_pipeline

FARM_CONTEXT = {
    "farm_id": "demo-arizona-tomato",
    "zone_id": "greenhouse-a",
    "crop": "tomato",
    "growth_stage": "fruiting",
    "system_type": "greenhouse_substrate",
}
SENSOR = {
    "timestamp": "2026-08-29T06:00:00Z",
    "air_temperature_c": 30.0,
    "humidity_pct": 60.0,
    "substrate_moisture_pct": 45.0,
    "ph": 6.0,
    "ec_ms_cm": 2.0,
    "substrate_temperature_c": 27.0,
}
EXPECTED_FIELDS = [
    "air_temperature_c",
    "humidity_pct",
    "ph",
    "ec_ms_cm",
    "substrate_moisture_pct",
]


def test_agronomy_calc_absent_without_optional_context():
    result = asyncio.run(
        evaluate_pipeline(
            FARM_CONTEXT,
            SENSOR,
            EXPECTED_FIELDS,
            None,
            "assistant_model",
            "rules_only",
        )
    )
    assert result["agronomy_calc"] is None


def test_agronomy_calc_present_with_weather_and_target():
    farm_context = {
        **FARM_CONTEXT,
        "weather": {
            "t_mean_c": 29.2,
            "t_min_c": 25.6,
            "t_max_c": 34.8,
            "rh_mean_pct": 66,
            "wind_speed_2m_ms": 2.0,
            "solar_radiation_mj_m2_day": 14.0,
            "elevation_m": 2,
        },
        "zone_area_m2": 20,
        "crop_kc": 1.15,
        "npk_target": {"n_ppm": 150, "p_ppm": 50, "k_ppm": 200, "volume_liters": 100},
    }
    result = asyncio.run(
        evaluate_pipeline(
            farm_context,
            SENSOR,
            EXPECTED_FIELDS,
            None,
            "assistant_model",
            "rules_only",
        )
    )
    calc = result["agronomy_calc"]
    assert calc is not None
    assert calc["irrigation"]["expected_irrigation_liters"] > 0
    assert calc["fertilizer"]["dap_g"] > 0
