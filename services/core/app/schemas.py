from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


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
