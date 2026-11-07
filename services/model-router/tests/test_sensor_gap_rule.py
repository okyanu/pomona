"""The gap rule: a packet without a field (a probe that stopped reporting) ends a run and breaks a step.

Without it, values either side of a gap looked adjacent: a stuck run could span a missing reading, and a step
across the gap counted as a jump. Stuck / frozen runs restart after a gap; step and noise checks skip only the
step that crosses it and keep their window length over the other steps.
"""

from datetime import datetime, timedelta, timezone

from app.sensor_quality import derive_sensor_quality

from .test_sensor_stream_habits import frozen_case, quiet_reference, packet, derive

T0 = datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
CONTEXT = {"crop": "tomato", "system_type": "greenhouse_substrate"}
FIELDS = ["air_temperature_c", "humidity_pct", "ph"]


def reading(index, **values):
    return {"timestamp": (T0 + timedelta(minutes=20 * index)).isoformat(), **values}


def quality(packets, fields=FIELDS):
    """Verdict on the last packet, the others as history."""
    sensor = packets[-1]
    now = datetime.fromisoformat(sensor["timestamp"]) + timedelta(seconds=1)
    return derive_sensor_quality(CONTEXT, sensor, fields, now=now, history=packets[:-1])


def series(values, field="air_temperature_c"):
    """One packet per value; `None` is a packet where the probe did not report."""
    return [reading(i, **({} if v is None else {field: v})) for i, v in enumerate(values)]


def labels(packets, field="air_temperature_c"):
    return quality(packets, [field])["data_quality_labels"]


def test_a_stuck_run_never_spans_a_missing_reading():
    assert "stuck_value" in labels(series([20.0, 21.0, 22.0, 24.0, 24.0, 24.0]))  # control: three equal readings
    assert "stuck_value" not in labels(series([20.0, 21.0, 22.0, 24.0, 24.0, None, 24.0]))  # the run restarts after the gap
    assert "stuck_value" not in labels(series([20.0, 21.0, 24.0, 24.0, 24.0, None, 24.0, 24.0]))  # 2 after the gap, not 5
    assert "stuck_value" in labels(series([20.0, 21.0, 22.0, None, 24.0, 24.0, 24.0]))  # 3 after the gap still counts


def test_the_newest_packet_without_the_field_judges_nothing_from_older_readings():
    result = quality(series([20.0, 21.0, 22.0, 24.0, 24.0, 24.0, None]), ["air_temperature_c"])
    assert "stuck_value" not in result["data_quality_labels"]
    assert result["missing_fields"] == ["air_temperature_c"] and "missing_temperature" in result["data_quality_labels"]


def test_the_longest_earlier_run_is_counted_per_run_not_across_a_gap():
    earlier = [20.0, 21.0, 24.0, 24.0, 24.0, 22.0, 23.0]
    frozen = [23.0] * 6  # run of 6 against an earlier longest of 3 (restarted by the gap): 6 >= 2 * 3
    assert "stuck_value" in labels(series(earlier[:5] + [None] + [24.0, 24.0, 24.0] + earlier[5:] + frozen))
    # Without the gap the two 3-runs of 24 are one run of 6, and 6 < 2 * 6 is quiet (the unchanged rule).
    assert "stuck_value" not in labels(series(earlier[:5] + [24.0, 24.0, 24.0] + earlier[5:] + frozen))


def test_a_flatline_window_does_not_span_a_gap():
    wobble = [24.0, 24.2, 24.0, 24.3, 24.1, 24.4]
    flat = [24.4, 24.43, 24.4, 24.43, 24.4, 24.43]
    assert "flatline_possible" in labels(series(wobble + flat))
    assert "flatline_possible" not in labels(series(wobble + flat[:3] + [None] + flat[3:]))


def test_the_flatline_check_survives_a_history_that_is_all_gaps():
    packets = series([24.0, None, 24.1, None, 24.0, None, 24.1, None, 24.0, None, 24.1, None, 24.0, 24.0, 24.0, 24.0, 24.0, 24.0])
    assert "flatline_possible" not in labels(packets)  # no step inside a run: no median to compare with, and no crash


def test_a_step_across_a_gap_is_not_taken_in_the_pH_noise_check():
    jumping = [6.0, 7.0] * 6
    assert "noisy_signal_possible" in labels(series(jumping, "ph"), "ph")  # control: 11 steps of 1.0
    gapped = [v for value in jumping for v in (value, None)][:-1]  # every neighbouring pair is a gap
    assert "noisy_signal_possible" not in labels(series(gapped, "ph"), "ph")
    one_gap = jumping[:6] + [None] + jumping[6:]  # one gap: 10 other steps still show the noise
    assert "noisy_signal_possible" in labels(series(one_gap, "ph"), "ph")


def noisy(count, field="humidity_pct", low=60.0, high=68.0, step_s=30):
    return [packet(i, step_s=step_s, **{field: high if i % 2 else low}) for i in range(count)]


def noise_flag(packets, field="humidity_pct"):
    return "noisy_signal_possible" in derive(packets[-1], packets[:-1], quiet_reference(field, 60.0), [field])["data_quality_labels"]


def test_a_step_across_a_gap_is_not_taken_in_the_persistent_noise_check():
    assert noise_flag(noisy(12))  # control: eleven 8 %RH steps at 30 s
    packets = noisy(12)
    spaced = []
    for p in packets:  # a packet without humidity between every neighbouring pair
        spaced += [p, {"timestamp": p["timestamp"]}]
    spaced = spaced[:-1]
    assert not noise_flag(spaced)  # every step crosses a gap: nothing to judge
    one_gap = packets[:6] + [{"timestamp": packets[5]["timestamp"]}] + packets[6:]
    assert noise_flag(one_gap)  # the window keeps its length: 10 steps remain


def test_the_adaptive_stuck_run_restarts_after_a_gap():
    sensor, history, baseline = frozen_case(6)  # 30 s samples, frozen 6 minutes: flagged
    assert derive(sensor, history, baseline, ["ph"])["data_quality_labels"] == ["stuck_value"]
    gapped = list(history)
    gapped[-2] = {"timestamp": gapped[-2]["timestamp"]}  # the probe skipped one packet: the run is now 2 long
    assert derive(sensor, gapped, baseline, ["ph"])["data_quality_labels"] == []
    gapped[-2] = history[-2]
    gapped[-3] = {"timestamp": gapped[-3]["timestamp"]}  # 3 readings since the gap: still a run
    assert derive(sensor, gapped, baseline, ["ph"])["data_quality_labels"] == ["stuck_value"]
