from datetime import datetime, timezone
from typing import Dict, Optional, Literal

from pydantic import BaseModel, Field, ConfigDict, ValidationInfo, model_validator, field_validator

from app.config import settings


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


def fmt_reading(value: Optional[float], spec: str) -> str:
    """A reading for a log line: `-` when the probe did not report."""
    return "-" if value is None else spec % value


def _hours_text(seconds: float) -> str:
    return f"{seconds / 3600:.1f} h" if seconds >= 3600 else f"{seconds / 60:.0f} min"


def _future_message(value: datetime, ahead_s: float) -> str:
    stamp = value.astimezone(timezone.utc).isoformat()
    steps = round(ahead_s / 900)  # time-zone offsets are whole multiples of 15 minutes
    if 1 <= steps <= 56 and abs(ahead_s - steps * 900) <= 120:  # up to +14:00, the largest UTC offset
        offset = f"+{steps * 15 // 60:02d}:{steps * 15 % 60:02d}"
        return (f"timestamp {stamp} is {_hours_text(ahead_s)} ahead of Core's clock; this looks like a time-zone offset: "
                f"if the device or file uses local time, stamp it with its UTC offset (e.g. {offset}) or convert to UTC")
    return (f"timestamp {stamp} is {_hours_text(ahead_s)} ahead of Core's clock; "
            "check the device clock and NTP sync (Core compares UTC)")


def check_sample_time(value: datetime, info: ValidationInfo) -> datetime:
    """Reject sample times from a clock that is unset (before the floor) or ahead of Core's. Stored rows are read back unchecked."""
    floor = settings.min_sample_time
    stored = bool(info.context and info.context.get("stored"))
    if value.tzinfo is None or stored:
        return value
    if value < floor:
        raise ValueError(
            f"timestamp {value.isoformat()} is before the minimum accepted sample time {floor.isoformat()}; "
            "check the device clock, NTP sync or RTC battery")
    ahead_s = (value - utc_now()).total_seconds()
    if settings.max_future_sample_s and ahead_s > settings.max_future_sample_s:
        raise ValueError(_future_message(value, ahead_s))
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


# The fields a packet's readings come from. weather, npk_target, zone_area_m2 and crop_kc are context, not readings.
READING_FIELDS = ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph", "soil_moisture_pct",
                  "substrate_temperature_c", "substrate_moisture_pct")


class SensorEvent(NumericReadings):
    device_id: str = Field(..., min_length=1, max_length=128)
    farm_id: str = Field(..., min_length=1, max_length=128)
    zone_id: str = Field(..., min_length=1, max_length=128)
    crop: str = Field(default="tomato", min_length=1, max_length=64)
    growth_stage: str = Field(default="flowering", min_length=1, max_length=64)
    system_type: str = Field(default="greenhouse_substrate", min_length=1, max_length=64)
    # A probe that did not report is absent or null: Core never fills a default, and the model-router says
    # "can't confirm" for the missing reading. A packet needs at least one reading (READING_FIELDS).
    air_temperature_c: Optional[float] = Field(default=None, ge=-40.0, le=80.0)
    humidity_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    ec_ms_cm: Optional[float] = Field(default=None, ge=0.0, le=20.0)
    ph: Optional[float] = Field(default=None, ge=0.0, le=14.0)
    soil_moisture_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
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
    timestamp: datetime  # Required: Core never invents a sample time.
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
    def timezone_required(cls, value, info: ValidationInfo):
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return check_sample_time(value.astimezone(timezone.utc), info)

    @model_validator(mode="after")
    def has_a_reading(self):
        if all(getattr(self, name) is None for name in READING_FIELDS):
            raise ValueError("a packet needs at least one reading: " + ", ".join(READING_FIELDS))
        return self


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

    @field_validator("timestamp")
    @classmethod
    def sample_time_floor(cls, value, info: ValidationInfo):
        return check_sample_time(value, info)

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


class FarmTimeInfo(BaseModel):
    """The farm's time zone, for display. Core stores and compares UTC only."""
    farm_timezone: str
    utc_offset_now: str  # e.g. "+04:00"
    next_offset_change: Optional[str] = None  # ISO UTC instant of the next UTC-offset change within 400 days
    offset_after_change: Optional[str] = None
    tzdata_version: Optional[str] = None  # the tzdata package, when installed; else the system zoneinfo is used


class HealthResponse(BaseModel):
    status: str
    service: str
    mqtt_connected: bool
    events_stored: int
    outcome_feed_dropped: int = 0
    time: Optional[FarmTimeInfo] = None


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
    def timezone_required_corrected(cls, value, info: ValidationInfo):
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        return check_sample_time(value.astimezone(timezone.utc), info)


class SensorEventListResponse(BaseModel):
    latest_event: Optional[SensorEvent] = None
    count: int
    events: list
    # Multi-device zones: whether the latest event's zone has another device (docs/design/multi-device-zones.md 1.1), and
    # the fields its device is expected to report then (null in a single-device zone).
    zone_multi_device: bool = False
    latest_device_fields: Optional[list[str]] = None
