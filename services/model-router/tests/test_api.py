import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "pomona-model-router"
    assert body["huggingface_repo"] == "Okyanus/ai-pomona-agronomist-gemma4"


def test_list_models():
    response = client.get("/v1/models")
    assert response.status_code == 200
    models = response.json()
    assert any(m["id"] == "ai-pomona-agronomist-gemma4" for m in models)


def test_advisor_explain_stub():
    payload = {
        "instruction": "Explain risks for this reading.",
        "sensor": {
            "crop": "tomato",
            "growth_stage": "flowering",
            "air_temperature_c": 31.2,
            "humidity_pct": 88,
            "ec_ms_cm": 3.4,
            "ph": 7.5,
        },
    }
    response = client.post("/v1/advisor/explain", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["backend"] == "stub"
    assert body["human_review_required"] is True
    assert len(body["likely_risks"]) >= 1
