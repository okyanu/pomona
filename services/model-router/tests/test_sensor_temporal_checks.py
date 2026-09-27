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


def _series(field, values, fields=None):
    """Run the rules packet by packet over `values` for one field; return labels per step."""
    history, out = [], []
    for step, value in enumerate(values):
        now, sensor = _packet(step, **{field: value})
        result = derive_sensor_quality(CONTEXT, sensor, fields or FIELDS + [field], now=now, history=history[-11:])
        out.append(result["data_quality_labels"])
        history.append(sensor)
    return out


def test_quantized_probe_repeats_are_not_stuck():
    # DS18B20 water temperature in 0.0625 C steps: short repeats are normal.
    water = [17.25, 17.3125, 17.25, 17.25, 17.3125, 17.25, 17.25, 17.3125, 17.3125, 17.25, 17.25, 17.25]
    assert not any("stuck_value" in labels for labels in _series("water_temperature_c", water))


def test_quantized_probe_long_freeze_is_stuck():
    water = [17.25, 17.3125, 17.25, 17.25, 17.3125, 17.25] + [17.25] * 6
    labels = _series("water_temperature_c", water)
    assert "stuck_value" in labels[-1]


def test_slow_noisy_signal_is_not_flatline():
    # Air temperature rising 0.05 C per step with +-0.1 C sensor jitter.
    jitter = [0.08, -0.07, 0.02, -0.09, 0.06, -0.03, 0.09, -0.08, 0.01, -0.06, 0.07, -0.02]
    air = [round(20 + 0.05 * i + j, 2) for i, j in enumerate(jitter)]
    assert not any("flatline_possible" in labels for labels in _series("air_temperature_c", air))


def test_collapsed_variance_is_flatline():
    air = [20.0, 20.3, 19.8, 20.4, 19.9, 20.2, 20.01, 20.02, 20.01, 20.03, 20.02, 20.01]
    labels = _series("air_temperature_c", air)
    assert "flatline_possible" in labels[-1]
    assert "stuck_value" not in labels[-1]


def test_drift_baseline_skips_impossible_reading():
    # An impossible pH 14.9 first in the window must not become the drift baseline.
    ph = [14.9] + [6.2, 6.21, 6.19, 6.2, 6.22, 6.18, 6.2, 6.21, 6.2, 6.19, 6.2]
    labels = _series("ph", ph)
    assert "impossible_ph" in labels[0]
    assert not any("baseline_drift_possible" in step for step in labels[1:])


def test_probe_error_codes_are_impossible_temperatures():
    for field in ("water_temperature_c", "substrate_temperature_c"):
        for value, bad in ((-127.0, True), (85.0, True), (18.5, False)):
            now, sensor = _packet(0, **{field: value})
            result = derive_sensor_quality(CONTEXT, sensor, FIELDS + [field], now=now)
            assert ("impossible_temperature" in result["data_quality_labels"]) is bad, (field, value)
            assert (field in result["suspect_fields"]) is bad
