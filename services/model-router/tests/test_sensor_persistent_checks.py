"""Persistent sensor checks against Core's sticky trusted reference (`stream_baseline`)."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.main import app
from app.pipeline import evaluate_pipeline
from app.sensor_quality import PERSISTENT_STUCK_LIMITS, derive_sensor_quality

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
FARM = {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"}
FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"]


def packet(index, **updates):
    base = {"ph": 6.0 + 0.01 * (index % 3), "ec_ms_cm": 2.5 + 0.01 * (index % 2), "air_temperature_c": 24.0 + 0.1 * (index % 4),
            "humidity_pct": 60.0 + 0.2 * (index % 5), "substrate_moisture_pct": 50.0, "soil_moisture_pct": 50.0,
            "timestamp": (T0 + timedelta(seconds=30 * index)).isoformat()}
    return {**base, **updates}


def stats(median, changed_minutes_ago=None, now_index=11):
    out = {"median": median, "n": 20, "window_s": 7200}
    if changed_minutes_ago is not None:
        out["last_change_at"] = (T0 + timedelta(seconds=30 * now_index) - timedelta(minutes=changed_minutes_ago)).isoformat()
    return out


def derive(sensor, history, baseline, expected=None):
    return derive_sensor_quality(FARM, sensor, expected or FIELDS, now=T0 + timedelta(hours=1), history=history,
                                 stream_baseline=baseline)


HISTORY = [packet(i) for i in range(11)]


def test_without_a_reference_nothing_changes():
    sensor = packet(11, ph=7.6)
    assert derive(sensor, HISTORY, None) == derive(sensor, HISTORY, {}) == derive_sensor_quality(
        FARM, sensor, FIELDS, now=T0 + timedelta(hours=1), history=HISTORY)


@pytest.mark.parametrize("field,median,value,flagged", [
    ("ph", 6.0, 6.3, False), ("ph", 6.0, 6.36, True), ("ph", 6.0, 5.6, True),
    ("ec_ms_cm", 2.5, 2.8, False), ("ec_ms_cm", 2.5, 2.91, True), ("ec_ms_cm", 2.5, 5.1, True),
])
def test_persistent_drift_uses_the_existing_thresholds(field, median, value, flagged):
    sensor = packet(11, **{field: value})
    result = derive(sensor, HISTORY, {field: stats(median)})
    assert ("baseline_drift_possible" in result["data_quality_labels"]) is flagged
    assert (field in result["suspect_fields"]) is flagged
    if flagged:
        text = " ".join(result["safe_next_checks"])
        assert "meter" in text and "calibration" in text and f"{median:g}" in text


def test_drift_is_only_for_ph_and_ec_and_ignores_impossible_values():
    sensor = packet(11, air_temperature_c=35.0, humidity_pct=90.0, substrate_moisture_pct=5.0)
    baseline = {"air_temperature_c": stats(24.0), "humidity_pct": stats(60.0), "substrate_moisture_pct": stats(50.0)}
    assert derive(sensor, HISTORY, baseline)["data_quality_labels"] == []  # real events must not be vetoed
    result = derive(packet(11, ph=13.0), HISTORY, {"ph": stats(6.0)})
    assert result["data_quality_labels"] == ["impossible_ph"]  # that label already covers it


@pytest.mark.parametrize("field,limit_minutes,flag_at,quiet_at", [
    ("air_temperature_c", 45, 46, 44), ("humidity_pct", 30, 31, 29),
    ("substrate_temperature_c", 360, 361, 359), ("water_temperature_c", 180, 181, 179),
])
def test_persistent_stuck_limits_per_field(field, limit_minutes, flag_at, quiet_at):
    assert PERSISTENT_STUCK_LIMITS[field] == timedelta(minutes=limit_minutes)
    value = {"ph": 6.0, "ec_ms_cm": 2.5}.get(field, 21.0)
    history = [packet(i, **{field: value}) for i in range(11)]
    sensor = packet(11, **{field: value})
    for minutes, expected in ((flag_at, True), (quiet_at, False)):
        result = derive(sensor, history, {field: stats(value, changed_minutes_ago=minutes)}, expected=[field])
        assert ("stuck_value" in result["data_quality_labels"]) is expected, minutes
        assert (field in result["suspect_fields"]) is expected
    text = " ".join(derive(sensor, history, {field: stats(value, flag_at)}, expected=[field])["safe_next_checks"])
    assert "calibration" in text and f"{flag_at} minutes" in text


def test_a_changed_value_breaks_the_run_and_missing_data_is_quiet():
    history = [packet(i, air_temperature_c=21.0) for i in range(11)]
    baseline = {"air_temperature_c": stats(21.0, changed_minutes_ago=60)}
    moved = derive(packet(11, air_temperature_c=21.1), history, baseline)
    assert "stuck_value" not in moved["data_quality_labels"]
    assert "stuck_value" not in derive(packet(11, air_temperature_c=21.0), [], baseline)["data_quality_labels"]  # no history
    no_time = {"air_temperature_c": {"median": 21.0, "n": 9}}
    assert "stuck_value" not in derive(packet(11, air_temperature_c=21.0), history, no_time)["data_quality_labels"]


def test_moisture_ph_and_ec_have_no_persistent_stuck_check():
    # Drain probes and placeholders really sit on one value for hours; only the continuous probes are judged.
    history = [packet(i, substrate_moisture_pct=50.0, ph=6.0, ec_ms_cm=2.5) for i in range(11)]
    baseline = {"substrate_moisture_pct": stats(50.0, 600), "soil_moisture_pct": stats(50.0, 600),  # ten hours flat
                "ph": stats(6.0, 600), "ec_ms_cm": stats(2.5, 600)}
    assert derive(packet(11, ph=6.0, ec_ms_cm=2.5), history, baseline)["data_quality_labels"] == []
    assert set(PERSISTENT_STUCK_LIMITS) == {"air_temperature_c", "humidity_pct", "substrate_temperature_c",
                                            "water_temperature_c"}


@pytest.mark.parametrize("bad", ["x", 5, None, {"ph": "x"}, {"ph": {"median": "x"}}, {"ph": {"median": 6.0, "last_change_at": "no"}}])
def test_malformed_reference_is_ignored(bad):
    baseline = bad if isinstance(bad, dict) else bad
    assert derive(packet(11), HISTORY, baseline)["data_quality_labels"] == []


def test_a_persistent_flag_vetoes_the_field_so_no_wrong_domain_card_follows(monkeypatch):
    monkeypatch.setattr(pipeline, "_now", lambda: T0 + timedelta(minutes=7))
    sensor = packet(11, ph=7.6)  # the first reading of a pH step: the 11-packet check cannot see it yet
    call = lambda baseline: asyncio.run(evaluate_pipeline(
        FARM, sensor, [], {"action_type": "continue_monitoring"}, "core_feed", "rules_only", history=HISTORY,
        stream_baseline=baseline))
    plain = call(None)
    assert "high_ph" in plain["nutrient_ph_ec"]["nutrient_risk_labels"] and plain["trust_gate"]["trust_verdict"] == "trusted"
    guarded = call({"ph": stats(6.0)})
    assert "baseline_drift_possible" in guarded["sensor_quality"]["data_quality_labels"]
    assert guarded["trust_gate"]["trust_verdict"] == "partial" and "ph" in guarded["trust_gate"]["vetoed_fields"]
    assert "high_ph" not in guarded["nutrient_ph_ec"]["nutrient_risk_labels"] + guarded["crop_risk"]["risk_labels"]
    # No stream state (the dashboard): byte-identical to before the reference existed.
    assert {k: v for k, v in call(None).items() if k not in ("pipeline_id", "evaluated_at")} == \
        {k: v for k, v in plain.items() if k not in ("pipeline_id", "evaluated_at")}


def test_api_accepts_and_validates_stream_baseline():
    client = TestClient(app)
    body = {"farm_context": FARM, "sensor": packet(11, ph=7.6), "history": HISTORY, "mode": "rules_only",
            "stream_baseline": {"ph": {"median": 6.0, "n": 20, "window_s": 7200,
                                       "last_change_at": T0.isoformat().replace("+00:00", "Z")}}}
    ok = client.post("/v1/pipeline/evaluate", json=body)
    assert ok.status_code == 200
    assert "baseline_drift_possible" in ok.json()["sensor_quality"]["data_quality_labels"]
    assert client.post("/v1/pipeline/evaluate", json={**body, "stream_baseline": None}).status_code == 200
    for bad in ({"ph": {"median": "x", "n": 3}}, {"ph": {"median": 6.0, "n": 1.5}}, {"ph": {"median": 6.0, "n": 0}},
                {"ph": {"median": True, "n": 3}}, {"ph": {"median": 6.0, "n": 3, "last_change_at": "yesterday"}}, {"ph": 5},
                [1]):
        assert client.post("/v1/pipeline/evaluate", json={**body, "stream_baseline": bad}).status_code == 422, bad


def test_a_wandering_probe_needs_a_departure_beyond_its_own_spread():
    # Real drain EC swings with every irrigation: 0.4 from the median is ordinary there, 3 x spread is not.
    wide = {"median": 2.5, "n": 20, "window_s": 7200, "spread": 0.8}
    assert derive(packet(11, ec_ms_cm=3.2), HISTORY, {"ec_ms_cm": wide})["data_quality_labels"] == []
    assert derive(packet(11, ec_ms_cm=5.0), HISTORY, {"ec_ms_cm": wide})["data_quality_labels"] == ["baseline_drift_possible"]
    calm = {"median": 2.5, "n": 20, "window_s": 7200, "spread": 0.05}  # the base threshold still rules a calm probe
    assert derive(packet(11, ec_ms_cm=2.95), HISTORY, {"ec_ms_cm": calm})["data_quality_labels"] == ["baseline_drift_possible"]
