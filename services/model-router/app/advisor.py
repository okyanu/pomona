from typing import Any, Dict, List, Optional

import httpx

from app.config import SENSOR_FIELDS, settings


def format_sensor_summary(sensor: Dict[str, Any]) -> str:
    parts: List[str] = []
    for field in SENSOR_FIELDS:
        value = sensor.get(field)
        if value is not None:
            parts.append(f"{field}={value}")
    return ", ".join(parts) if parts else "no sensor data"


def build_user_message(instruction: str, sensor: Dict[str, Any]) -> str:
    summary = format_sensor_summary(sensor)
    return f"{instruction}\n\nSensor data: {summary}"


def _stub_explanation(instruction: str, sensor: Dict[str, Any]) -> Dict[str, Any]:
    humidity = sensor.get("humidity_pct")
    ph = sensor.get("ph")
    temp = sensor.get("air_temperature_c")
    ec = sensor.get("ec_ms_cm")

    risks: List[str] = []
    checks: List[str] = []
    missing: List[str] = ["drain_ec", "drain_ph", "co2_ppm", "leaf_symptoms"]

    if humidity is not None and humidity > 85:
        risks.append("High humidity increases fungal disease risk during flowering")
        checks.append("Review ventilation and dehumidification schedule")
    if ph is not None and ph > 6.8:
        risks.append("pH above typical tomato hydroponic range may reduce micronutrient uptake")
        checks.append("Check young leaf color and last pH adjustment")
    if temp is not None and temp > 30:
        risks.append("High air temperature increases heat and VPD stress")
        checks.append("Confirm shading and airflow")
    if ec is not None and ec > 3.2:
        risks.append("EC trending high — verify drain EC before changing feed")
        checks.append("Measure drain EC vs feed EC")

    if not risks:
        risks.append("No critical threshold breach in stub analysis — verify with reasoner rules")

    explanation = (
        f"[stub backend] {instruction} "
        f"Based on available readings ({format_sensor_summary(sensor)}), "
        f"review {len(risks)} risk signal(s) before acting."
    )

    return {
        "model_id": settings.default_model_id,
        "backend": "stub",
        "huggingface_repo": settings.hf_model_id,
        "explanation": explanation,
        "likely_risks": risks,
        "missing_data": missing,
        "safe_checks": checks or ["Inspect crop visually", "Compare feed vs drain EC/pH"],
        "human_review_required": True,
        "safety_note": "Advisory only — not for direct pesticide, fertilizer dosing, or actuator control.",
    }


async def _ollama_explanation(instruction: str, sensor: Dict[str, Any]) -> Dict[str, Any]:
    user_message = build_user_message(instruction, sensor)
    payload = {
        "model": settings.ollama_model,
        "messages": [{"role": "user", "content": user_message}],
        "stream": False,
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(f"{settings.ollama_host.rstrip('/')}/api/chat", json=payload)
        response.raise_for_status()
        body = response.json()

    text = body.get("message", {}).get("content", "").strip()
    return {
        "model_id": settings.default_model_id,
        "backend": "ollama",
        "huggingface_repo": settings.hf_model_id,
        "explanation": text,
        "likely_risks": [],
        "missing_data": [],
        "safe_checks": [],
        "human_review_required": True,
        "safety_note": "Advisory only — review before any field action.",
    }


async def _huggingface_explanation(instruction: str, sensor: Dict[str, Any]) -> Dict[str, Any]:
    """Call Hugging Face Inference API for the registered agronomist model."""
    if not settings.hf_token:
        raise ValueError(
            "HF_TOKEN is required for huggingface backend. "
            "Get one at https://huggingface.co/settings/tokens"
        )

    from huggingface_hub import InferenceClient

    user_message = build_user_message(instruction, sensor)
    prompt = (
        f"<start_of_turn>user\n{user_message}<end_of_turn>\n"
        f"<start_of_turn>model\n"
    )

    client = InferenceClient(model=settings.hf_model_id, token=settings.hf_token)
    text = client.text_generation(
        prompt,
        max_new_tokens=350,
        do_sample=False,
        return_full_text=False,
    )
    explanation = text.strip() if isinstance(text, str) else str(text).strip()

    return {
        "model_id": settings.default_model_id,
        "backend": "huggingface",
        "huggingface_repo": settings.hf_model_id,
        "explanation": explanation,
        "likely_risks": [],
        "missing_data": [],
        "safe_checks": [],
        "human_review_required": True,
        "safety_note": "Advisory only — review before any field action.",
    }


async def explain(instruction: str, sensor: Dict[str, Any], backend: Optional[str] = None) -> Dict[str, Any]:
    selected = (backend or settings.backend).lower()

    if selected == "huggingface":
        try:
            return await _huggingface_explanation(instruction, sensor)
        except Exception as exc:
            result = _stub_explanation(instruction, sensor)
            result["backend"] = "stub"
            result["fallback_reason"] = (
                f"Hugging Face inference failed: {exc}. "
                "Your model may need an Inference Provider or Endpoint on HF. "
                f"See docs/HF_USAGE.md and https://huggingface.co/{settings.hf_model_id}"
            )
            return result

    if selected == "ollama":
        try:
            return await _ollama_explanation(instruction, sensor)
        except Exception as exc:
            result = _stub_explanation(instruction, sensor)
            result["backend"] = "stub"
            result["fallback_reason"] = f"ollama unavailable: {exc}"
            return result

    return _stub_explanation(instruction, sensor)
