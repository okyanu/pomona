"""The MQTT client logs in to the broker with the configured credentials (the Docker broker is not anonymous)."""

import sys
from pathlib import Path
from types import SimpleNamespace

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.mqtt_client as mqtt_client_module
from app.config import Settings, settings
from app.mqtt_client import MqttIngestClient


class FakePahoClient:
    def __init__(self, *args, **kwargs):
        self.credentials = None

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)


def fake_paho(monkeypatch):
    monkeypatch.setattr(mqtt_client_module, "mqtt", SimpleNamespace(
        Client=FakePahoClient, CallbackAPIVersion=SimpleNamespace(VERSION2=2)))


def test_client_logs_in_with_the_configured_credentials(monkeypatch):
    fake_paho(monkeypatch)
    monkeypatch.setattr(settings, "mqtt_username", "pomona")
    monkeypatch.setattr(settings, "mqtt_password", "s3cret")
    assert MqttIngestClient()._client.credentials == ("pomona", "s3cret")


def test_client_connects_without_credentials_when_the_username_is_empty(monkeypatch):
    fake_paho(monkeypatch)
    monkeypatch.setattr(settings, "mqtt_username", "")
    monkeypatch.setattr(settings, "mqtt_password", "ignored")
    assert MqttIngestClient()._client.credentials is None


def test_credentials_come_from_the_environment(monkeypatch):
    monkeypatch.setenv("MQTT_USERNAME", "pomona")
    monkeypatch.setenv("MQTT_PASSWORD", "from-env")
    loaded = Settings(_env_file=None)
    assert (loaded.mqtt_username, loaded.mqtt_password) == ("pomona", "from-env")
    monkeypatch.delenv("MQTT_USERNAME")
    monkeypatch.delenv("MQTT_PASSWORD")
    loaded = Settings(_env_file=None)
    assert (loaded.mqtt_username, loaded.mqtt_password) == ("", "")
