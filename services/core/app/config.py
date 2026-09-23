from pathlib import Path
from pydantic import Field

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


settings = Settings()
