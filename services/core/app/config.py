from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from pydantic import Field, field_validator

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.trusted_baseline import DEFAULT_MAX_AGE_S, DEFAULT_MIN_N, DEFAULT_SCAN_LIMIT, DEFAULT_WINDOW_S


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    core_host: str = "0.0.0.0"
    core_port: int = 8080
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    # Broker login. An empty username connects without credentials (a non-Docker dev broker).
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_topic_pattern: str = "pomona/+/+/sensor/+/state"
    mqtt_observation_topic_pattern: str = "pomona/+/+/sensor/+/observation"
    max_events: int = Field(default=100000, ge=1)
    retention_days: int = Field(default=7, ge=1, le=3650)
    # Judge each device of a multi-device zone on its own expected fields (docs/design/multi-device-zones.md).
    # 0 = every zone is single-device, as before.
    multi_device_zones: bool = True
    device_timeout_seconds: int = Field(default=120, ge=1)
    db_path: Path = Path("data/pomona.db")
    api_key: str = ""
    # Sample times before this are a dead clock (ESP32 without NTP stamps 1970, a dead RTC battery 2000).
    min_sample_time: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # Sample times more than this many seconds ahead of Core's clock are rejected: a device or spreadsheet that
    # writes local time but labels it Z lands hours in the future in UTC+ zones. 0 disables the check.
    max_future_sample_s: int = Field(default=300, ge=0)
    # The farm's IANA time zone, shown on /health and the dashboard. Display only: Core stores and compares UTC.
    farm_timezone: str = "UTC"
    # Advisory outcome feed to model-router (rules_only) and automation-engine; empty URL = disabled.
    model_router_url: str = ""
    automation_engine_url: str = ""
    outcome_feed_queue_size: int = Field(default=1000, ge=1)
    # Sticky trusted reference per sensor stream (app/trusted_baseline.py), sent with each evaluation so the
    # router can flag a step or a frozen probe for as long as it lasts: the window the reference median
    # covers, the trusted readings needed to use it, and how many stored readings are scanned back for it.
    trust_baseline_window_s: int = Field(default=DEFAULT_WINDOW_S, ge=60)
    trust_baseline_min_n: int = Field(default=DEFAULT_MIN_N, ge=2)
    # 0 (the default): a flagged level stays flagged until a calibration. Seconds opt into a lapse.
    trust_baseline_max_age_s: int = Field(default=DEFAULT_MAX_AGE_S, ge=0)
    trust_baseline_scan_limit: int = Field(default=DEFAULT_SCAN_LIMIT, ge=10)

    @field_validator("min_sample_time")
    @classmethod
    def floor_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("MIN_SAMPLE_TIME must include a timezone")
        return value

    @field_validator("farm_timezone")
    @classmethod
    def farm_timezone_known(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (KeyError, ValueError, OSError):  # ZoneInfoNotFoundError is a KeyError
            raise ValueError(
                f"FARM_TIMEZONE {value!r} is not a known time zone name; use an IANA name such as "
                "Asia/Dubai or Europe/Berlin (check the spelling)") from None
        return value


settings = Settings()
