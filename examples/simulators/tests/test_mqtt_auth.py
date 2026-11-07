"""The simulators log in to the broker with MQTT_USERNAME / MQTT_PASSWORD; an empty username means no login."""

import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SIM_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SIM_DIR))


class FakeClient:
    def __init__(self, *args, **kwargs):
        self.credentials = None
        self.connected_to = None

    def username_pw_set(self, username, password=None):
        self.credentials = (username, password)

    def connect(self, host, port, keepalive=60):
        self.connected_to = (host, port)

    def loop_start(self):
        pass


@pytest.fixture
def fake_paho(monkeypatch):
    client_module = ModuleType("paho.mqtt.client")
    client_module.Client = FakeClient
    client_module.CallbackAPIVersion = SimpleNamespace(VERSION2=2)
    mqtt_package, paho_package = ModuleType("paho.mqtt"), ModuleType("paho")
    mqtt_package.client, paho_package.mqtt = client_module, mqtt_package
    for name, module in (("paho", paho_package), ("paho.mqtt", mqtt_package), ("paho.mqtt.client", client_module)):
        monkeypatch.setitem(sys.modules, name, module)


def test_fake_greenhouse_publisher_logs_in(fake_paho):
    import fake_greenhouse as fg
    assert fg.MqttPublisher("localhost", 1883, "pomona", "s3cret").client.credentials == ("pomona", "s3cret")
    assert fg.MqttPublisher("localhost", 1883).client.credentials is None
    assert fg.MqttPublisher("localhost", 1883, "", "ignored").client.credentials is None


def test_greenhouse_tomato_logs_in_from_the_environment(fake_paho, monkeypatch):
    monkeypatch.setenv("MQTT_USERNAME", "pomona")
    monkeypatch.setenv("MQTT_PASSWORD", "s3cret")
    sys.modules.pop("greenhouse_tomato", None)
    tomato = importlib.import_module("greenhouse_tomato")
    assert tomato.build_client().credentials == ("pomona", "s3cret")
    monkeypatch.setenv("MQTT_USERNAME", "")
    sys.modules.pop("greenhouse_tomato", None)
    tomato = importlib.import_module("greenhouse_tomato")
    assert tomato.build_client().credentials is None
    sys.modules.pop("greenhouse_tomato", None)
