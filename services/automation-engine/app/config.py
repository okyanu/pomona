from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    automation_engine_host: str = "0.0.0.0"
    automation_engine_port: int = 8085
    rules_path: Path = Path(__file__).parent / "rules.yaml"
    max_suggestions: int = 200


settings = Settings()
