from pathlib import Path
from typing import List

from pydantic import Field
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
    tomato_risk_ollama_model: str = "pomona-tomato-risk:v0.1.7-local"
    water_irrigation_ollama_model: str = "pomona-water-irrigation:v0.1.8"
    nutrient_ph_ec_ollama_model: str = "pomona-nutrient-ph-ec:v0.1.1"
    mlx_host: str = "http://host.docker.internal:8083"
    water_irrigation_mlx_model: str = ""
    default_model_id: str = "ai-pomona-agronomist-gemma4"
    audit_log_path: Path = _REPO_ROOT / "data" / "pomona-pipeline-audit.jsonl"
    # Seconds to wait for a model. A specialist reasoner's answer is checked against the rules and (in hybrid_guarded)
    # discarded for them, so it gets a short wait; the advisor's explanation is the text people read and gets longer.
    reasoner_timeout_s: float = Field(default=60, gt=0)
    advisor_timeout_s: float = Field(default=60, gt=0)
    # The pipeline audit file is renamed to `<name>.1` when it reaches this size (one rotated file is kept). 0 = never.
    audit_log_max_bytes: int = Field(default=20 * 1024 * 1024, ge=0)
    # Same setting and meaning as Core's MAX_FUTURE_SAMPLE_S: a sample time up to this many seconds ahead of the clock
    # still counts as current (Core accepts it), so the sensor check must not call it a doubtful clock. 0 = Core's
    # check is off and the old 60 s limit applies.
    max_future_sample_s: int = Field(default=300, ge=0)

    @property
    def future_slack_s(self) -> int:
        return self.max_future_sample_s or 60

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
