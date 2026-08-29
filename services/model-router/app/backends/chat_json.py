"""JSON-only chat clients for local Ollama and OpenAI-compatible runtimes."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import httpx


def parse_json_object(text: str) -> Dict[str, Any]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("model response did not contain a JSON object")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model response must be a JSON object")
    return parsed


def parse_json_array(text: str) -> List[Any]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        raise ValueError("model response did not contain a JSON array")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, list):
        raise ValueError("model response must be a JSON array")
    return parsed


async def ollama_chat_json(
    host: str,
    model: str,
    system: str,
    prompt: str,
    output_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": output_schema or "json",
        "options": {"temperature": 0},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{host.rstrip('/')}/api/chat", json=payload)
        response.raise_for_status()
    return parse_json_object(response.json().get("message", {}).get("content", ""))


async def ollama_chat_json_array(
    host: str,
    model: str,
    system: str,
    prompt: str,
    output_schema: Dict[str, Any],
) -> List[Any]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "format": output_schema,
        "options": {"temperature": 0},
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{host.rstrip('/')}/api/chat", json=payload)
        response.raise_for_status()
    return parse_json_array(response.json().get("message", {}).get("content", ""))


async def openai_compatible_chat_json(
    host: str,
    model: str,
    system: str,
    prompt: str,
) -> Dict[str, Any]:
    payload = {
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 256,
    }
    if model:
        payload["model"] = model
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{host.rstrip('/')}/v1/chat/completions", json=payload)
        response.raise_for_status()
    choices = response.json().get("choices") or []
    if not choices:
        raise ValueError("runtime response did not contain a completion")
    return parse_json_object(choices[0].get("message", {}).get("content", ""))
