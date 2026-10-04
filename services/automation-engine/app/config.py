from pathlib import Path
from typing import Optional

from pydantic import Field

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    automation_engine_host: str = "0.0.0.0"
    automation_engine_port: int = 8085
    rules_path: Path = Path(__file__).parent / "rules.yaml"
    max_suggestions: int = Field(default=200, ge=1)
    suggestion_ttl_seconds: int = Field(default=900, ge=1)
    suggestion_sample_max_age_seconds: int = Field(default=3600, ge=1)
    # Alert monitor defaults (rules.yaml may override per rule): a label must last this long
    # before an alert is raised, and stay away this long before it recovers.
    alert_raise_after_seconds: int = Field(default=600, ge=0)
    alert_clear_after_seconds: int = Field(default=900, ge=0)
    # Unset stays ephemeral for serverless/demo deployments; Compose sets a volume path.
    automation_db_path: Optional[Path] = None


settings = Settings()
