"""A sample time up to MAX_FUTURE_SAMPLE_S ahead (Core accepts it, default 300 s) is not a doubtful device clock.

The Python function keeps its own default of 60 s (the browser demos mirror that); the service passes the setting.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app.config import Settings, settings
from app.main import app
from app.sensor_quality import derive_sensor_quality

client = TestClient(app)
FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"]
CLOCK_CHECK = "sample timestamp is more than"


@pytest.fixture(autouse=True)
def _audit_in_tmp(monkeypatch, tmp_path):
    monkeypatch.setattr("app.audit.settings.audit_log_path", tmp_path / "audit.jsonl")


def packet(seconds_ahead):
    return {"air_temperature_c": 24.0, "humidity_pct": 60.0, "ph": 6.2, "ec_ms_cm": 2.4, "substrate_moisture_pct": 45.0,
            "timestamp": (datetime.now(timezone.utc) + timedelta(seconds=seconds_ahead)).isoformat()}


def pipeline_quality(seconds_ahead):
    response = client.post("/v1/pipeline/evaluate", json={
        "farm_context": {"crop": "tomato", "system_type": "controlled_greenhouse"},
        "sensor": packet(seconds_ahead), "expected_fields": FIELDS})
    assert response.status_code == 200, response.text
    return response.json()["sensor_quality"]


def test_future_slack_is_the_setting_or_60_when_it_is_off():
    assert Settings(max_future_sample_s=300).future_slack_s == 300
    assert Settings(max_future_sample_s=0).future_slack_s == 60


def test_function_default_stays_60_seconds():
    now = datetime.now(timezone.utc)
    sensor = {**packet(0), "timestamp": (now + timedelta(seconds=120)).isoformat()}
    context = {"crop": "tomato", "system_type": "controlled_greenhouse"}
    flagged = derive_sensor_quality(context, sensor, FIELDS, now=now)
    assert "insufficient_context" in flagged["data_quality_labels"]
    assert any("more than 60 seconds" in check for check in flagged["safe_next_checks"])
    allowed = derive_sensor_quality(context, sensor, FIELDS, now=now, future_slack_s=300)
    assert allowed["data_quality_labels"] == []


def test_pipeline_does_not_flag_a_sample_two_minutes_ahead_with_the_default_setting():
    quality = pipeline_quality(120)
    assert not any(CLOCK_CHECK in check for check in quality["safe_next_checks"])
    assert quality["data_quality_labels"] == []


def test_pipeline_still_flags_a_sample_beyond_the_setting():
    quality = pipeline_quality(600)
    assert any("more than 300 seconds" in check for check in quality["safe_next_checks"])


def test_pipeline_with_the_setting_off_keeps_the_old_60_second_rule(monkeypatch):
    monkeypatch.setattr(settings, "max_future_sample_s", 0)
    quality = pipeline_quality(120)
    assert any("more than 60 seconds" in check for check in quality["safe_next_checks"])
    assert not any(CLOCK_CHECK in check for check in pipeline_quality(30)["safe_next_checks"])
