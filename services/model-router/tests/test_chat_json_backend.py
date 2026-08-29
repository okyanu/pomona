import asyncio
import sys
from pathlib import Path


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from app.backends import chat_json


def test_ollama_chat_uses_supplied_output_schema(monkeypatch):
    schema = {
        "type": "object",
        "properties": {"label": {"type": "string", "enum": ["normal"]}},
        "required": ["label"],
        "additionalProperties": False,
    }
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '{"label":"normal"}'}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            captured["url"] = url
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(chat_json.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        chat_json.ollama_chat_json(
            "http://ollama:11434",
            "pomona-test",
            "Return a classification.",
            "Classify this packet.",
            output_schema=schema,
        )
    )

    assert result == {"label": "normal"}
    assert captured["url"] == "http://ollama:11434/api/chat"
    assert captured["payload"]["format"] == schema
    assert captured["payload"]["options"]["temperature"] == 0


def test_ollama_chat_array_uses_schema_and_parses_labels(monkeypatch):
    schema = {
        "type": "array",
        "items": {"type": "string", "enum": ["fungal_pressure"]},
        "uniqueItems": True,
    }
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": '["fungal_pressure"]'}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, json):
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(chat_json.httpx, "AsyncClient", FakeClient)

    result = asyncio.run(
        chat_json.ollama_chat_json_array(
            "http://ollama:11434",
            "pomona-tomato-risk:v0.1.7-local",
            "Return labels.",
            "Classify this packet.",
            schema,
        )
    )

    assert result == ["fungal_pressure"]
    assert captured["payload"]["format"] == schema
