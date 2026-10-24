from datetime import datetime, timezone
from pathlib import Path
from pydantic import Field, field_validator

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    core_host: str = "0.0.0.0"
    core_port: int = 8080
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_pattern: str = "pomona/+/+/sensor/+/state"
    mqtt_observation_topic_pattern: str = "pomona/+/+/sensor/+/observation"
    max_events: int = Field(default=100000, ge=1)
    retention_days: int = Field(default=7, ge=1, le=3650)
    device_timeout_seconds: int = Field(default=120, ge=1)
    db_path: Path = Path("data/pomona.db")
    api_key: str = ""
    # Sample times before this are a dead clock (ESP32 without NTP stamps 1970, a dead RTC battery 2000).
    min_sample_time: datetime = datetime(2020, 1, 1, tzinfo=timezone.utc)
    # Advisory outcome feed to model-router (rules_only) and automation-engine; empty URL = disabled.
    model_router_url: str = ""
    automation_engine_url: str = ""
    outcome_feed_queue_size: int = Field(default=1000, ge=1)

    @field_validator("min_sample_time")
    @classmethod
    def floor_timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("MIN_SAMPLE_TIME must include a timezone")
        return value


settings = Settings()
