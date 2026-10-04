from datetime import datetime, timezone
from typing import Dict, Optional, Literal

from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator


class NumericReadings(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    @field_validator("*", mode="before")
    @classmethod
    def reject_numeric_booleans(cls, value, info):
        annotation = str(cls.model_fields[info.field_name].annotation)
        if isinstance(value, bool) and ("float" in annotation or "int" in annotation):
            raise ValueError("boolean is not a numeric measurement")
        return value


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


# Payload contract version, "MAJOR.MINOR". Senders that omit it are treated as 1.0 (every
# sender before 2026-10 used the 1.x shape). Minor versions only add optional fields, so any
# 1.x is accepted; a different major is rejected instead of being stored as if it were 1.x.
SCHEMA_MAJOR = 1
SCHEMA_VERSION = "1.0"


def check_schema_version(value: str) -> str:
    major = int(value.split(".", 1)[0])
    if major != SCHEMA_MAJOR:
        raise ValueError(f"unsupported schema_version {value}: this Core accepts {SCHEMA_MAJOR}.x")
    return value


class WeatherReading(NumericReadings):
    """Daily weather aggregates for FAO-56 ET calculation (agronomy_calc)."""

    t_mean_c: float = Field(..., ge=-40.0, le=60.0)
    t_min_c: float = Field(..., ge=-40.0, le=60.0)
    t_max_c: float = Field(..., ge=-40.0, le=60.0)
    rh_mean_pct: float = Field(..., ge=0.0, le=100.0)
    wind_speed_2m_ms: float = Field(..., ge=0.0, le=60.0)
    solar_radiation_mj_m2_day: float = Field(..., ge=0.0, le=45.0)
    elevation_m: float = Field(default=0.0, ge=-500.0, le=6000.0)


class NpkTargetReading(NumericReadings):
    """Target nutrient concentration for fertigation dosing (agronomy_calc)."""

    n_ppm: float = Field(..., ge=0.0, le=1000.0)
    p_ppm: float = Field(..., ge=0.0, le=1000.0)
    k_ppm: float = Field(..., ge=0.0, le=1000.0)
    volume_liters: float = Field(..., gt=0.0, le=1_000_000.0)


class SensorEvent(NumericReadings):
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
    received_at: Optional[datetime] = None  # Set by Core, never trusted from the sender.
    sequence: Optional[int] = Field(default=None, ge=0, strict=True)
    boot_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    mqtt_retained: bool = False  # Set by transport, not trusted from sender.
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^[0-9]{1,3}\.[0-9]{1,3}$")

    @field_validator("schema_version")
    @classmethod
    def supported_schema(cls, value):
        return check_schema_version(value)

    @field_validator("timestamp")
    @classmethod
    def timezone_required(cls, value):
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)


class SensorObservation(NumericReadings):
    """One observation from a modular node; not a complete agronomic state."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    device_id: str = Field(..., min_length=1, max_length=128)
    farm_id: str = Field(..., min_length=1, max_length=128)
    zone_id: str = Field(..., min_length=1, max_length=128)
    sensor_id: str = Field(..., min_length=1, max_length=128)
    measurement: Literal["air_temperature_c", "water_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "soil_moisture_pct", "low_level_contact"]
    unit: Literal["C", "%", "pH", "mS/cm", "boolean"]
    value: Optional[float] = None
    quality: Literal["valid", "missing", "suspect", "conflicting", "disconnected"] = "valid"
    timestamp: datetime
    calibration_timestamp: Optional[datetime] = None
    sequence: Optional[int] = Field(default=None, ge=0, strict=True)
    boot_id: Optional[str] = Field(default=None, max_length=128)
    firmware: Optional[str] = Field(default=None, max_length=128)
    received_at: Optional[datetime] = None
    mqtt_retained: bool = False
    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^[0-9]{1,3}\.[0-9]{1,3}$")

    @field_validator("schema_version")
    @classmethod
    def supported_schema(cls, value):
        return check_schema_version(value)

    @model_validator(mode="after")
    def check_measurement(self):
        bounds = {"air_temperature_c": ("C", -40, 80), "water_temperature_c": ("C", -10, 80),
                  "humidity_pct": ("%", 0, 100), "ph": ("pH", 0, 14), "ec_ms_cm": ("mS/cm", 0, 20),
                  "soil_moisture_pct": ("%", 0, 100), "low_level_contact": ("boolean", 0, 1)}
        unit, low, high = bounds[self.measurement]
        if self.unit != unit:
            raise ValueError(f"unit must be {unit} for {self.measurement}")
        if self.timestamp.tzinfo is None or (self.calibration_timestamp and self.calibration_timestamp.tzinfo is None):
            raise ValueError("timestamps must include a timezone")
        if self.value is None and self.quality == "valid":
            raise ValueError("a valid observation requires a value")
        if self.value is not None:
            if self.quality == "valid" and not low <= self.value <= high:
                raise ValueError("valid observation outside transport bounds")
            if self.measurement == "low_level_contact" and self.value not in (0, 1):
                raise ValueError("contact must be 0 or 1")
        return self


class HealthResponse(BaseModel):
    status: str
    service: str
    mqtt_connected: bool
    events_stored: int


class CalibrationPoint(NumericReadings):
    reference: float
    raw: float


class CalibrationEvent(NumericReadings):
    """Operator/device calibration record. Never mutates prior raw readings."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    device_id: str = Field(..., min_length=1, max_length=128)
    farm_id: str = Field(..., min_length=1, max_length=128)
    zone_id: str = Field(..., min_length=1, max_length=128)
    sensor_id: str = Field(..., min_length=1, max_length=128)
    measurement: Literal["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct", "soil_moisture_pct"]
    method: str = Field(..., min_length=1, max_length=64)
    points: list[CalibrationPoint] = Field(..., min_length=1, max_length=6)
    coefficients: Dict[str, float] = Field(default_factory=dict)
    uncertainty: Dict[str, float] = Field(default_factory=dict)
    performed_at: datetime
    performed_by: Optional[str] = Field(default=None, max_length=80)
    notes: Optional[str] = Field(default=None, max_length=500)
    id: Optional[str] = Field(default=None, max_length=64)
    received_at: Optional[datetime] = None

    @field_validator("performed_at")
    @classmethod
    def timezone_required_calibration(cls, value):
        if value.tzinfo is None:
            raise ValueError("performed_at must include a timezone")
        return value.astimezone(timezone.utc)


class CorrectedObservation(NumericReadings):
    """Derived corrected reading tagged to a calibration event. Not raw truth."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    device_id: str = Field(..., min_length=1, max_length=128)
    farm_id: str = Field(..., min_length=1, max_length=128)
    zone_id: str = Field(..., min_length=1, max_length=128)
    sensor_id: str = Field(..., min_length=1, max_length=128)
    measurement: Literal["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct", "soil_moisture_pct"]
    raw_value: float
    corrected_value: float
    uncertainty: Optional[float] = Field(default=None, ge=0.0)
    calibration_event_id: str = Field(..., min_length=1, max_length=64)
    method: str = Field(..., min_length=1, max_length=64)
    quality: Literal["corrected"] = "corrected"
    timestamp: datetime
    human_review_required: bool = False
    id: Optional[str] = Field(default=None, max_length=64)
    received_at: Optional[datetime] = None

    @field_validator("timestamp")
    @classmethod
    def timezone_required_corrected(cls, value):
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return value.astimezone(timezone.utc)


class SensorEventListResponse(BaseModel):
    latest_event: Optional[SensorEvent] = None
    count: int
    events: list
