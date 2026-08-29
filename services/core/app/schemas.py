from datetime import datetime, timezone
from typing import Dict, Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WeatherReading(BaseModel):
    """Daily weather aggregates for FAO-56 ET calculation (agronomy_calc)."""

    t_mean_c: float = Field(..., ge=-40.0, le=60.0)
    t_min_c: float = Field(..., ge=-40.0, le=60.0)
    t_max_c: float = Field(..., ge=-40.0, le=60.0)
    rh_mean_pct: float = Field(..., ge=0.0, le=100.0)
    wind_speed_2m_ms: float = Field(..., ge=0.0, le=60.0)
    solar_radiation_mj_m2_day: float = Field(..., ge=0.0, le=45.0)
    elevation_m: float = Field(default=0.0, ge=-500.0, le=6000.0)


class NpkTargetReading(BaseModel):
    """Target nutrient concentration for fertigation dosing (agronomy_calc)."""

    n_ppm: float = Field(..., ge=0.0, le=1000.0)
    p_ppm: float = Field(..., ge=0.0, le=1000.0)
    k_ppm: float = Field(..., ge=0.0, le=1000.0)
    volume_liters: float = Field(..., gt=0.0, le=1_000_000.0)


class SensorEvent(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128)
    farm_id: str = Field(..., min_length=1, max_length=128)
    zone_id: str = Field(..., min_length=1, max_length=128)
    crop: str = Field(default="tomato", min_length=1, max_length=64)
    growth_stage: str = Field(default="flowering", min_length=1, max_length=64)
    system_type: str = Field(default="greenhouse_substrate", min_length=1, max_length=64)
    air_temperature_c: float = Field(..., ge=-40.0, le=80.0)
    humidity_pct: float = Field(..., ge=0.0, le=100.0)
    ec_ms_cm: float = Field(..., ge=0.0, le=20.0)
    ph: float = Field(..., ge=0.0, le=14.0)
    soil_moisture_pct: float = Field(..., ge=0.0, le=100.0)
    substrate_temperature_c: Optional[float] = Field(default=None, ge=-40.0, le=80.0)
    substrate_moisture_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    # Optional zone-level context for the model-router's FAO-56/NPK
    # calculator (services/model-router/app/agronomy_calc.py). These
    # change slowly (daily weather, fixed zone geometry/target) rather than
    # per-reading, so simulators/devices may repeat the same values across
    # many ticks; absent, the pipeline simply skips the calculation.
    weather: Optional[WeatherReading] = None
    zone_area_m2: Optional[float] = Field(default=None, gt=0.0, le=1_000_000.0)
    crop_kc: Optional[float] = Field(default=None, ge=0.0, le=3.0)
    npk_target: Optional[NpkTargetReading] = None
    timestamp: datetime = Field(default_factory=utc_now)
    source: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    service: str
    mqtt_connected: bool
    events_stored: int


class SensorEventListResponse(BaseModel):
    count: int
    events: list
