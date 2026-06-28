from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SensorEvent(BaseModel):
    device_id: str
    farm_id: str
    zone_id: str
    crop: str = "tomato"
    growth_stage: str = "flowering"
    air_temperature_c: float
    humidity_pct: float
    ec_ms_cm: float
    ph: float
    soil_moisture_pct: float
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
