"""With a model backend the rules still decide, so a model gets a short wait and its failure is not echoed to clients.

Timeouts are settings (REASONER_TIMEOUT_S, ADVISOR_TIMEOUT_S). `fallback_reason` carries the exception class name only;
the full text (which can hold a host name, a path or model-written text) goes to the log.
"""

import asyncio
import sys
from pathlib import Path

import httpx
import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app import advisor
from app.backends import chat_json
from app.config import Settings, settings
from app.nutrient_ph_ec import route_nutrient_ph_ec_reasoner
from app.tomato_reasoner import route_tomato_reasoner
from app.water_irrigation import route_water_irrigation_reasoner

SECRET = "http://10.1.2.3:11434/api/chat token=s3cret"
TOMATO = {"crop": "tomato", "system_type": "controlled_greenhouse", "air_temperature_c": 24.0, "humidity_pct": 60.0,
          "ph": 6.2, "ec_ms_cm": 2.4}
PACKET = {"farm_context": {"crop": "tomato", "system_type": "controlled_greenhouse"},
          "sensor": {"ph": 6.2, "ec_ms_cm": 2.4, "substrate_moisture_pct": 50.0},
          "expected_fields": ["ph", "ec_ms_cm", "substrate_moisture_pct"]}


class Recorder:
    timeouts: list = []

    def __init__(self, *args, timeout=None, **kwargs):
        Recorder.timeouts.append(timeout)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, json):
        raise httpx.ConnectError(SECRET)


@pytest.fixture
def recorder(monkeypatch):
    Recorder.timeouts = []
    monkeypatch.setattr(httpx, "AsyncClient", Recorder)
    return Recorder


def test_defaults_are_20_seconds_for_reasoners_and_60_for_the_advisor():
    fresh = Settings()
    assert fresh.reasoner_timeout_s == 60 and fresh.advisor_timeout_s == 60


def test_reasoner_calls_use_the_reasoner_timeout(recorder, monkeypatch):
    for call in (lambda: chat_json.ollama_chat_json("http://h", "m", "s", "p"),
                 lambda: chat_json.ollama_chat_json_array("http://h", "m", "s", "p", {}),
                 lambda: chat_json.openai_compatible_chat_json("http://h", "m", "s", "p")):
        with pytest.raises(httpx.ConnectError):
            asyncio.run(call())
    assert recorder.timeouts == [60, 60, 60]
    monkeypatch.setattr(settings, "reasoner_timeout_s", 7.5)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(chat_json.ollama_chat_json("http://h", "m", "s", "p"))
    assert recorder.timeouts[-1] == 7.5


def test_advisor_call_uses_the_advisor_timeout(recorder, monkeypatch):
    with pytest.raises(httpx.ConnectError):
        asyncio.run(advisor._ollama_explanation("explain", {}))
    assert recorder.timeouts == [60]
    monkeypatch.setattr(settings, "advisor_timeout_s", 90)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(advisor._ollama_explanation("explain", {}))
    assert recorder.timeouts[-1] == 90


@pytest.mark.parametrize("route", [
    lambda: route_tomato_reasoner(TOMATO, "hybrid_guarded", "m", "ollama"),
    lambda: route_nutrient_ph_ec_reasoner(PACKET, "hybrid_guarded", "m", "ollama"),
    lambda: route_water_irrigation_reasoner(PACKET, "hybrid_guarded", "ollama", "m"),
])
def test_fallback_reason_names_the_exception_class_and_leaks_nothing_else(recorder, route, caplog):
    result = asyncio.run(route())
    assert result["source"] == "deterministic_rules"
    assert result["fallback_reason"] == "ollama unavailable or invalid (ConnectError); used deterministic rules"
    assert "10.1.2.3" not in str(result) and "s3cret" not in str(result)
    assert "s3cret" in caplog.text  # the full text is in the log for the operator


def test_advisor_fallback_reason_names_the_exception_class_only(recorder, caplog):
    result = asyncio.run(advisor.explain("explain", {"ph": 6.2}, backend="ollama"))
    assert result["backend"] == "stub"
    assert result["fallback_reason"] == "ollama unavailable (ConnectError)"
    assert "10.1.2.3" not in str(result) and "s3cret" in caplog.text


def test_huggingface_advisor_fallback_reason_names_the_exception_class_only(monkeypatch, caplog):
    async def boom(*args, **kwargs):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(advisor, "_huggingface_explanation", boom)
    result = asyncio.run(advisor.explain("explain", {"ph": 6.2}, backend="huggingface"))
    assert result["fallback_reason"].startswith("Hugging Face inference failed (RuntimeError).")
    assert "10.1.2.3" not in str(result) and "s3cret" in caplog.text
