"""Checks that judge a reading by its own stream's habits (Core's `stream_baseline` extras).

  * adaptive stuck for pH/EC: a probe that normally changes every sample and then freezes; a drain probe that
    holds one value for hours is never judged
  * a step in air temperature faster than air can change, against the newest trusted reading
  * noise on humidity / air temperature, scaled to the sample interval
"""

from datetime import datetime, timedelta, timezone
import random

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sensor_quality import (
    ADAPTIVE_STUCK_FLOOR, ADAPTIVE_STUCK_MIN_CHANGE_SHARE, ADAPTIVE_STUCK_MIN_STEPS, NOISE_STEP_FLOOR,
    NOISE_STEP_LIMIT_5MIN, STEP_MAX_RATE_C_PER_MIN, STEP_MIN_C, adaptive_stuck_limit, derive_sensor_quality,
)

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
FARM = {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"}


def when(index, step_s=30):
    return T0 + timedelta(seconds=step_s * index)


def packet(index, step_s=30, **values):
    return {"timestamp": when(index, step_s).isoformat(), **values}


def derive(sensor, history, baseline, fields):
    now = datetime.fromisoformat(sensor["timestamp"]) + timedelta(seconds=1) if "timestamp" in sensor else T0
    return derive_sensor_quality(FARM, sensor, fields, now=now, history=history, stream_baseline=baseline)


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


# --- adaptive stuck for pH and EC ---------------------------------------------------------------------------

def moving(**extra):
    return {"median": 6.0, "n": 200, "window_s": 7200, "change_share": 0.9, "change_steps": 199, "longest_run_s": 60.0,
            **extra}


def frozen_case(minutes, field="ph", value=6.1, norm=None):
    """A probe frozen for `minutes` (30 s samples) at the latest reading, and Core's stats for it."""
    count = int(minutes * 2)
    history = [packet(i, **{field: value}) for i in range(count - 11, count)]
    sensor = packet(count, **{field: value})
    stats = {**(norm or moving()), "median": value, "last_change_at": iso(when(0))}
    return sensor, history, {field: stats}


@pytest.mark.parametrize("field,value", [("ph", 6.1), ("ec_ms_cm", 2.6)])
def test_a_probe_that_normally_moves_is_stuck_after_the_floor(field, value):
    assert ADAPTIVE_STUCK_FLOOR == timedelta(minutes=15)
    for minutes, flagged in ((14, False), (16, True), (45, True)):
        sensor, history, baseline = frozen_case(minutes, field, value)
        result = derive(sensor, history, baseline, [field])
        assert ("stuck_value" in result["data_quality_labels"]) is flagged, minutes
        assert (field in result["suspect_fields"]) is flagged
    text = " ".join(derive(*frozen_case(16, field, value), [field])["safe_next_checks"])
    assert "16 minutes" in text and "normally changes on 90%" in text and "calibration" in text


def test_a_drain_probe_that_sits_still_is_never_judged():
    # Real drain pH changes in 3 to 18 % of its steps and holds one value for hours.
    for norm in ({"change_share": 0.05, "change_steps": 199, "longest_run_s": 3600.0 * 8},
                 {"change_share": 0.18, "change_steps": 199, "longest_run_s": 3600.0}):
        for minutes in (30, 600):
            assert derive(*frozen_case(minutes, norm=moving(**norm)), ["ph"])["data_quality_labels"] == []


def test_a_probe_that_normally_rests_needs_a_freeze_far_beyond_its_longest_rest():
    norm = moving(longest_run_s=20 * 60.0)  # it has held one value for 20 minutes before
    assert derive(*frozen_case(60, norm=norm), ["ph"])["data_quality_labels"] == []  # 60 < 4 x 20
    assert derive(*frozen_case(85, norm=norm), ["ph"])["data_quality_labels"] == ["stuck_value"]


def test_the_adaptive_check_needs_the_stream_habits_and_a_repeated_value():
    sensor, history, baseline = frozen_case(40)
    assert derive(sensor, history, {"ph": {"median": 6.1, "n": 200, "last_change_at": iso(when(0))}}, ["ph"]) \
        ["data_quality_labels"] == []  # an older Core sends no habits: nothing changes
    short = {"ph": {**baseline["ph"], "change_steps": ADAPTIVE_STUCK_MIN_STEPS - 1}}
    assert derive(sensor, history, short, ["ph"])["data_quality_labels"] == []  # too little history to know the habit
    shy = {"ph": {**baseline["ph"], "change_share": ADAPTIVE_STUCK_MIN_CHANGE_SHARE - 0.01}}
    assert derive(sensor, history, shy, ["ph"])["data_quality_labels"] == []
    moved = packet(len(history) + 1, ph=6.12)  # the value moved: the run is over
    assert derive(moved, history, baseline, ["ph"])["data_quality_labels"] == []
    for bad in ("x", None, True, -5, float("nan")):
        broken = {"ph": {**baseline["ph"], "longest_run_s": bad}}
        assert derive(sensor, history, broken, ["ph"])["data_quality_labels"] == []
    assert adaptive_stuck_limit({}) is None


# --- a step faster than air can change ------------------------------------------------------------------------

def air_stats(last_value, last_index, **extra):
    return {"median": last_value, "n": 50, "window_s": 7200, "last_value": last_value, "last_at": iso(when(last_index)),
            **extra}


def air_history(count=11, start=0):
    return [packet(start + i, air_temperature_c=24.0 + 0.1 * (i % 3)) for i in range(count)]


@pytest.mark.parametrize("jump,flagged", [(4.0, True), (-4.0, True), (3.2, True), (2.5, False), (0.5, False)])
def test_a_sudden_air_temperature_step_is_flagged_against_the_newest_trusted_reading(jump, flagged):
    history = air_history()
    sensor = packet(11, air_temperature_c=24.0 + jump)  # 30 s after the newest trusted reading (index 10)
    result = derive(sensor, history, {"air_temperature_c": air_stats(24.0, 10)}, ["air_temperature_c"])
    assert ("sensor_drift_possible" in result["data_quality_labels"]) is flagged
    assert ("air_temperature_c" in result["suspect_fields"]) is flagged
    if flagged:
        assert "second thermometer" in " ".join(result["safe_next_checks"])


def test_a_step_stays_flagged_until_the_allowance_has_grown_to_cover_it():
    # The stepped readings are vetoed, so the newest trusted reading stays at index 10: +4 C is impossible for
    # 4 minutes (1 C per minute: index 18 is 240 s on) and then accepted as the new level.
    assert (STEP_MIN_C, STEP_MAX_RATE_C_PER_MIN) == (3.0, 1.0)
    baseline = {"air_temperature_c": air_stats(24.0, 10)}
    history = air_history()
    verdicts = {index: "sensor_drift_possible" in derive(packet(index, air_temperature_c=28.0), history, baseline,
                                                         ["air_temperature_c"])["data_quality_labels"]
                for index in (11, 14, 17, 18, 19, 21)}
    assert verdicts == {11: True, 14: True, 17: True, 18: False, 19: False, 21: False}


def test_a_heat_spike_ramp_and_slow_real_changes_stay_quiet():
    # The simulator's heat spike climbs about 0.5 C per minute: 0.25 C per 30 s sample, always trusted.
    for index in range(11, 120):
        history = [packet(i, air_temperature_c=24.0 + 0.25 * i) for i in range(max(0, index - 11), index)]
        sensor = packet(index, air_temperature_c=24.0 + 0.25 * index)
        baseline = {"air_temperature_c": air_stats(24.0 + 0.25 * (index - 1), index - 1)}
        assert "sensor_drift_possible" not in derive(sensor, history, baseline, ["air_temperature_c"])["data_quality_labels"]
    # 5-minute samples: 4 C between two samples is only 0.8 C per minute, inside the allowance.
    slow = derive(packet(11, step_s=300, air_temperature_c=28.0), [packet(i, step_s=300, air_temperature_c=24.0) for i in range(11)],
                  {"air_temperature_c": air_stats(24.0, 0) | {"last_at": iso(when(10, 300))}}, ["air_temperature_c"])
    assert "sensor_drift_possible" not in slow["data_quality_labels"]


def test_the_step_check_is_air_only_and_ignores_missing_or_malformed_stats():
    sensor = packet(11, air_temperature_c=30.0, humidity_pct=90.0)
    history = [packet(i, air_temperature_c=24.0, humidity_pct=60.0) for i in range(11)]
    humidity = {"median": 60.0, "n": 50, "last_value": 60.0, "last_at": iso(when(10))}
    assert derive(sensor, history, {"humidity_pct": humidity}, ["humidity_pct"])["data_quality_labels"] == []
    for stats in ({"median": 24.0, "n": 5}, {"median": 24.0, "n": 5, "last_value": 24.0},
                  {"median": 24.0, "n": 5, "last_value": "x", "last_at": iso(when(10))},
                  {"median": 24.0, "n": 5, "last_value": 24.0, "last_at": "no"}):
        assert derive(sensor, history, {"air_temperature_c": stats}, ["air_temperature_c"])["data_quality_labels"] == [], stats


# --- noise on humidity and air temperature ----------------------------------------------------------------------

def noisy_series(field, base, sigma, step_s, count=12, seed=3):
    rng = random.Random(seed)
    return [packet(i, step_s=step_s, **{field: round(base + rng.gauss(0, sigma), 2)}) for i in range(count)]


def quiet_reference(field, value):
    return {field: {"median": value, "n": 50, "window_s": 7200}}


def run_noise(field, base, sigma, step_s):
    series = noisy_series(field, base, sigma, step_s)
    return derive(series[-1], series[:-1], quiet_reference(field, base), [field])


def test_ten_times_the_normal_noise_is_flagged_on_humidity_and_air_at_30_seconds():
    for field, base, healthy, noisy in (("humidity_pct", 62.0, 0.8, 8.0), ("air_temperature_c", 24.0, 0.1, 1.0)):
        assert run_noise(field, base, healthy, 30)["data_quality_labels"] == []
        result = run_noise(field, base, noisy, 30)
        assert result["data_quality_labels"] == ["noisy_signal_possible"] and result["suspect_fields"] == [field]
        assert "shielding" in " ".join(result["safe_next_checks"])


def test_the_limit_scales_with_the_sample_interval_and_never_drops_below_its_floor():
    assert NOISE_STEP_LIMIT_5MIN == {"humidity_pct": 10.0, "air_temperature_c": 2.0}
    assert NOISE_STEP_FLOOR == {"humidity_pct": 3.0, "air_temperature_c": 0.4}
    # A humidity median step of ~5 %RH: ordinary between 5-minute samples (limit 10), not between 30-second ones (3.2).
    for step_s, flagged in ((300, False), (30, True)):
        series = [packet(i, step_s=step_s, humidity_pct=60.0 + (5.0 if i % 2 else 0.0)) for i in range(12)]
        result = derive(series[-1], series[:-1], quiet_reference("humidity_pct", 60.0), ["humidity_pct"])
        assert ("noisy_signal_possible" in result["data_quality_labels"]) is flagged, step_s
    # At 1-second samples the floor still allows a healthy probe its own noise (2 %RH steps).
    series = [packet(i, step_s=1, humidity_pct=60.0 + (2.0 if i % 2 else 0.0)) for i in range(12)]
    assert derive(series[-1], series[:-1], quiet_reference("humidity_pct", 60.0), ["humidity_pct"])["data_quality_labels"] == []


def test_a_real_like_swing_or_a_plateau_is_not_noise():
    # A sustained climb (an irrigation or vent event) moves every sample the same way: median step 2 %RH at 30 s.
    climb = [packet(i, humidity_pct=50.0 + 2.0 * i) for i in range(12)]
    assert derive(climb[-1], climb[:-1], quiet_reference("humidity_pct", 50.0), ["humidity_pct"])["data_quality_labels"] == []
    # A single outlier among steady readings leaves the median step small.
    spike = [packet(i, humidity_pct=60.0 if i != 6 else 85.0) for i in range(12)]
    assert derive(spike[-1], spike[:-1], quiet_reference("humidity_pct", 60.0), ["humidity_pct"])["data_quality_labels"] == []
    # Too few readings, or none with a usable timestamp, say nothing.
    few = noisy_series("humidity_pct", 62.0, 8.0, 30, count=5)
    assert derive(few[-1], few[:-1], quiet_reference("humidity_pct", 62.0), ["humidity_pct"])["data_quality_labels"] == []
    no_time = [{"humidity_pct": 62.0 + (9.0 if i % 2 else 0.0)} for i in range(12)]
    assert "noisy_signal_possible" not in derive(no_time[-1], no_time[:-1], quiet_reference("humidity_pct", 62.0),
                                                 ["humidity_pct"])["data_quality_labels"]


def test_without_a_reference_the_new_checks_do_not_run():
    # The 11-packet checks are mirrored by the Sensor Data Checker page's JavaScript; these stream checks are not.
    series = noisy_series("humidity_pct", 62.0, 8.0, 30)
    assert derive(series[-1], series[:-1], None, ["humidity_pct"])["data_quality_labels"] == []


# --- the API ---------------------------------------------------------------------------------------------------------

def test_the_api_accepts_the_new_optional_stream_keys_and_rejects_malformed_ones():
    client = TestClient(app)
    sensor, history, baseline = frozen_case(40)
    stats = baseline["ph"] | {"last_value": 6.1, "last_at": iso(when(0))}
    body = {"farm_context": FARM, "sensor": sensor, "history": history, "mode": "rules_only",
            "expected_fields": ["ph"], "stream_baseline": {"ph": stats}}
    ok = client.post("/v1/pipeline/evaluate", json=body)
    assert ok.status_code == 200 and "stuck_value" in ok.json()["sensor_quality"]["data_quality_labels"]
    old = client.post("/v1/pipeline/evaluate", json={**body, "stream_baseline": {"ph": {"median": 6.1, "n": 20}}})
    assert old.status_code == 200  # a Core without the extras still works
    for bad in ({"last_value": "x"}, {"last_value": True}, {"last_at": "yesterday"}, {"change_share": -0.1},
                {"change_steps": "many"}, {"longest_run_s": True}):
        response = client.post("/v1/pipeline/evaluate", json={**body, "stream_baseline": {"ph": {**stats, **bad}}})
        assert response.status_code == 422, bad
