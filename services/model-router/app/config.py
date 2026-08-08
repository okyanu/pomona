from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict

_CONFIG_PATH = Path(__file__).resolve()
_REPO_ROOT = _CONFIG_PATH.parents[3] if len(_CONFIG_PATH.parents) > 3 else Path("/app")
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
    reasoner_backend: str = "rules"
    water_irrigation_ollama_model: str = "pomona-water-irrigation:v0.1.8"
    mlx_host: str = "http://host.docker.internal:8083"
    water_irrigation_mlx_model: str = ""
    default_model_id: str = "ai-pomona-agronomist-gemma4"
    audit_log_path: Path = _REPO_ROOT / "data" / "pomona-pipeline-audit.jsonl"

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
