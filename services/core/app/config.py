from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    core_host: str = "0.0.0.0"
    core_port: int = 8080
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_pattern: str = "pomona/+/+/sensor/+/state"
    max_events: int = 500


settings = Settings()
