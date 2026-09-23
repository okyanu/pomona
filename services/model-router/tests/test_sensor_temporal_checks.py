"""Unit tests for temporal stuck / flatline / baseline-drift checks."""

from datetime import datetime, timedelta, timezone

from app.sensor_quality import derive_sensor_quality


CONTEXT = {"crop": "tomato", "system_type": "greenhouse_substrate"}
FIELDS = ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct"]


def _packet(step: int, **updates):
    now = datetime(2026, 9, 6, 8, tzinfo=timezone.utc) + timedelta(minutes=20 * step)
    sensor = {
        "ph": 6.0,
        "ec_ms_cm": 2.0,
        "air_temperature_c": 24.0 + (step % 2) * 0.1,
        "humidity_pct": 60.0,
        "timestamp": now.isoformat(),
    }
    sensor.update(updates)
    return now, sensor


def test_stable_ph_plateau_is_not_a_temporal_fault():
    history = []
    for step in range(6):
        now, sensor = _packet(step)
        result = derive_sensor_quality(CONTEXT, sensor, FIELDS, now=now, history=history)
        assert result["human_review_required"] is False
        assert "stuck_value" not in result["data_quality_labels"]
        assert "baseline_drift_possible" not in result["data_quality_labels"]
        history.append(sensor)


def test_stuck_temperature_flags_after_window():
    history = []
    detected = False
    for step in range(8):
        # Alternate first, then freeze — prior variation required.
        temp = 24.0 + (step % 2) * 0.1 if step < 3 else 24.0
        now, sensor = _packet(step, air_temperature_c=temp)
        result = derive_sensor_quality(CONTEXT, sensor, FIELDS, now=now, history=history)
        if "stuck_value" in result["data_quality_labels"]:
            detected = True
            assert result["human_review_required"] is True
        history.append(sensor)
    assert detected


def test_baseline_ph_drift_flags_sustained_walk():
    history = []
    detected_at = None
    for step in range(8):
        ph = 6.0 if step < 3 else 6.0 + 0.1 * (step - 2)
        now, sensor = _packet(step, ph=ph, previous_ph=ph - 0.1)
        result = derive_sensor_quality(CONTEXT, sensor, FIELDS, now=now, history=history)
        if "baseline_drift_possible" in result["data_quality_labels"] and detected_at is None:
            detected_at = step
        history.append(sensor)
    assert detected_at is not None
    assert detected_at >= 5
