from datetime import datetime, timezone
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.sensor_quality import derive_sensor_quality


@pytest.mark.parametrize("value", [True, False, "broken", "NaN", "Infinity", {}, [], float("nan")])
def test_invalid_ph_never_healthy(value):
    now = datetime.now(timezone.utc)
    result = derive_sensor_quality({"crop": "tomato", "system_type": "greenhouse"},
                                   {"ph": value, "timestamp": now.isoformat()}, ["ph"], now=now)
    assert result["human_review_required"]
    assert "ph" in result["suspect_fields"]


@pytest.mark.parametrize("timestamp", [None, "bad", "2026-01-01T10:00:00", "2099-01-01T00:00:00Z"])
def test_invalid_clock_requires_review(timestamp):
    result = derive_sensor_quality({"crop": "tomato", "system_type": "greenhouse"}, {"ph": 6.2, "timestamp": timestamp}, ["ph"], now=datetime.now(timezone.utc))
    assert result["human_review_required"]
    assert "timestamp" in result["suspect_fields"]


@pytest.mark.parametrize("patch", [{"sensor": []}, {"sensor": "bad"}, {"farm_context": []}, {"expected_fields": "ph"}, {"expected_fields": [[]]}])
def test_bad_api_containers_return_422(patch):
    response = TestClient(app).post("/v1/reasoners/sensor-quality", json={"input": patch, "mode": "rules_only"})
    assert response.status_code == 422


@pytest.mark.parametrize("value", ["broken", "NaN", True])
def test_api_invalid_ph_requires_review(value):
    response = TestClient(app).post("/v1/reasoners/sensor-quality", json={"mode": "rules_only", "input": {
        "farm_context": {"crop": "tomato", "system_type": "greenhouse"},
        "sensor": {"ph": value, "timestamp": "invalid"}, "expected_fields": ["ph"]}})
    assert response.status_code == 200
    assert response.json()["human_review_required"] is True
