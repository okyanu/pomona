from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_MODELS_DIR = _REPO_ROOT / "models" / "registry"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    model_router_host: str = "0.0.0.0"
    model_router_port: int = 8081
    models_dir: Path = _DEFAULT_MODELS_DIR
    pomona_llm_backend: str = "stub"
    hf_model_id: str = "Okyanus/ai-pomona-agronomist-gemma4"
    hf_base_model_id: str = "google/gemma-4-E2B-it"
    hf_token: str = ""
    ollama_host: str = "http://host.docker.internal:11434"
    ollama_model: str = "ai-pomona-agronomist-gemma4"
    default_model_id: str = "ai-pomona-agronomist-gemma4"

    @property
    def backend(self) -> str:
        return self.pomona_llm_backend.strip().lower()


settings = Settings()

SENSOR_FIELDS: List[str] = [
    "air_temperature_c",
    "humidity_pct",
    "ec_ms_cm",
    "ph",
    "co2_ppm",
    "light_umol",
    "soil_moisture_pct",
    "crop",
    "growth_stage",
]
