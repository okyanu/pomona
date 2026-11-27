"""Pair check (docs/design/slow-drift-pair-check.md, Design 4 and 4b): Core's `stream_baseline[field]["pair"]` says how far
a probe usually reads from the other probes of its zone and what they read now; the router flags the probe when that
difference has moved by the limit or more."""

import importlib.util
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.sensor_quality import (
    PAIR_DRIFT_LIMITS,
    STEP_LIMITS,
    apply_persistent_checks,
    derive_sensor_quality,
)
from app.main import MAX_KNOWN_CHECK_CHARS

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
FARM = {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"}
FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"]
REPO = Path(__file__).resolve().parents[3]
FLAG = "baseline_drift_possible"


def packet(index, **updates):
    base = {"ph": 6.0 + 0.01 * (index % 3), "ec_ms_cm": 2.5 + 0.01 * (index % 2), "air_temperature_c": 24.0 + 0.1 * (index % 4),
            "humidity_pct": 60.0 + 0.2 * (index % 5), "substrate_moisture_pct": 50.0, "soil_moisture_pct": 50.0,
            "timestamp": (T0 + timedelta(seconds=30 * index)).isoformat()}
    return {**base, **updates}


HISTORY = [packet(i) for i in range(11)]


def pair(partner_value, offset=0.0, *, partners=1, partner_device="climate-2", device="climate-1", n=20):
    return {"offset": offset, "n": n, "partner_value": partner_value, "partners": partners,
            "partner_device": partner_device, "device": device}


def entry(median, pair_entry=None):
    out = {"median": median, "n": 20, "window_s": 7200}
    if pair_entry is not None:
        out["pair"] = pair_entry
    return out


def derive(sensor, baseline, history=HISTORY):
    return derive_sensor_quality(FARM, sensor, FIELDS, now=T0 + timedelta(hours=1), history=history, stream_baseline=baseline)


def pair_check_texts(result):
    return [check for check in result["safe_next_checks"] if check.startswith("pair check:")]


# (field, partner value, offset 0: at the limit, just under the limit)
BOUNDARIES = [
    ("air_temperature_c", 20.0, 23.0, 22.99, "°C"),
    ("humidity_pct", 60.0, 70.0, 69.99, "%RH"),
    ("soil_moisture_pct", 50.0, 58.0, 57.99, "%"),
    ("substrate_moisture_pct", 50.0, 58.0, 57.99, "%"),
]


def test_limits_are_the_documented_ones():
    assert PAIR_DRIFT_LIMITS == {"air_temperature_c": 3.0, "humidity_pct": 10.0, "soil_moisture_pct": 8.0,
                                 "substrate_moisture_pct": 8.0}


@pytest.mark.parametrize("field,partner,at_limit,under,unit", BOUNDARIES)
def test_flag_at_the_limit_and_none_just_under(field, partner, at_limit, under, unit):
    baseline = {field: entry(at_limit, pair(partner))}
    flagged = derive(packet(11, **{field: at_limit}), baseline)
    assert FLAG in flagged["data_quality_labels"] and field in flagged["suspect_fields"]
    assert flagged["pair_disagreement_fields"] == [field]
    assert len(pair_check_texts(flagged)) == 1 and pair_check_texts(flagged)[0].startswith(f"pair check: {field} on climate-1 is ")
    clear = derive(packet(11, **{field: under}), {field: entry(under, pair(partner))})
    assert FLAG not in clear["data_quality_labels"] and field not in clear["suspect_fields"]
    assert not pair_check_texts(clear) and "pair_disagreement_fields" not in clear


@pytest.mark.parametrize("field,partner,at_limit,under,unit", BOUNDARIES)
def test_the_usual_offset_is_taken_off(field, partner, at_limit, under, unit):
    limit = PAIR_DRIFT_LIMITS[field]
    # The probe has always read 4 above its partner; the move is 4 + limit - 0.25 from the partner, 0.25 short of the limit.
    short = derive(packet(11, **{field: partner + 4.0 + limit - 0.25}), {field: entry(0.0, pair(partner, 4.0))})
    assert not pair_check_texts(short)
    enough = derive(packet(11, **{field: partner + 4.0 + limit}), {field: entry(0.0, pair(partner, 4.0))})
    assert len(pair_check_texts(enough)) == 1 and "higher" in pair_check_texts(enough)[0]


@pytest.mark.parametrize("field,partner,at_limit,under,unit", BOUNDARIES)
def test_direction_and_unit(field, partner, at_limit, under, unit):
    limit = PAIR_DRIFT_LIMITS[field]
    up = pair_check_texts(derive(packet(11, **{field: partner + limit}), {field: entry(0.0, pair(partner))}))[0]
    down = pair_check_texts(derive(packet(11, **{field: partner - limit}), {field: entry(0.0, pair(partner))}))[0]
    assert f" is {limit:.1f} {unit} higher than usual " in up
    assert f" is {limit:.1f} {unit} lower than usual " in down


def test_text_one_partner_exact():
    # now -11.9 (58.1 against 70.0), usually -1.5: 10.4 lower.
    sensor = packet(11, humidity_pct=58.1)
    result = derive(sensor, {"humidity_pct": entry(58.1, pair(70.0, -1.5, device="climate-1", partner_device="climate-2"))})
    assert result["safe_next_checks"][0] == (
        "pair check: humidity_pct on climate-1 is 10.4 %RH lower than usual against climate-2 (now -11.9, usually -1.5). "
        "Check both with a meter; calibrate only the one that was wrong.")
    assert "record a calibration for this probe" not in " ".join(pair_check_texts(result))


def test_text_three_partners_names_the_median():
    sensor = packet(11, air_temperature_c=24.25)
    result = derive(sensor, {"air_temperature_c": entry(24.25, pair(20.0, 0.5, partners=3, partner_device=None))})
    assert pair_check_texts(result) == [
        "pair check: air_temperature_c on climate-1 is 3.8 °C higher than usual against the median of 3 other probes in this "
        "zone (now 4.2, usually 0.5). Check both with a meter; calibrate only the one that was wrong."]


def test_one_partner_without_a_name_uses_the_median_wording():
    # partners == 1 with partner_device null (or, defensively, not a string case is invalid and ignored elsewhere)
    result = derive(packet(11, air_temperature_c=24.0), {"air_temperature_c": entry(24.0, pair(20.0, 0.0, partner_device=None))})
    assert "against the median of 1 other probes in this zone" in pair_check_texts(result)[0]


def test_several_partners_never_name_the_partner_device():
    result = derive(packet(11, air_temperature_c=24.0),
                    {"air_temperature_c": entry(24.0, pair(20.0, 0.0, partners=2, partner_device="climate-2"))})
    text = pair_check_texts(result)[0]
    assert "against the median of 2 other probes in this zone" in text and "climate-2" not in text


def test_long_device_ids_are_cut_and_the_text_stays_short():
    long_id = "x" * 128
    result = derive(packet(11, substrate_moisture_pct=99.0), {
        "substrate_moisture_pct": entry(99.0, pair(10.0, -99.0, device=long_id, partner_device="y" * 128))})
    text = pair_check_texts(result)[0]
    assert "x" * 31 + "…" in text and "x" * 32 not in text and "y" * 31 + "…" in text and "y" * 32 not in text
    assert len(text) <= 260 and len(text) <= MAX_KNOWN_CHECK_CHARS


def test_longest_possible_text_fits_under_260():
    # The longest field name, the longest ids and long numbers.
    result = derive(packet(11, substrate_moisture_pct=99.9), {
        "substrate_moisture_pct": entry(99.9, pair(-99.9, -99.9, device="d" * 200, partner_device="p" * 200))})
    assert len(pair_check_texts(result)[0]) <= 260


def test_control_characters_are_removed_from_device_ids():
    result = derive(packet(11, air_temperature_c=24.0), {
        "air_temperature_c": entry(24.0, pair(20.0, 0.0, device="cli\nmate\x00-1\t", partner_device="a\x1bb"))})
    text = pair_check_texts(result)[0]
    assert "on climate-1 is" in text and "against ab (" in text
    assert not any(ord(ch) < 32 or ord(ch) == 127 for ch in text)


def test_the_pair_text_is_first_even_when_another_check_fires_first_in_code_order():
    # ph is judged before air temperature in the loop and appends its own check; the pair text still comes first.
    baseline = {"ph": entry(6.0), "air_temperature_c": entry(24.0, pair(20.0, 0.0))}
    result = derive(packet(11, ph=7.6, air_temperature_c=24.0), baseline)
    assert result["safe_next_checks"][0].startswith("pair check:")
    assert any(check.startswith("verify ph with a meter") for check in result["safe_next_checks"][1:])
    assert result["suspect_fields"].count("air_temperature_c") == 1
    assert result["data_quality_labels"].count(FLAG) == 1


def test_a_shared_move_is_not_flagged():
    # Both probes moved by +8 C (usually 4 above the partner): the reading is far from its own past, the difference is unchanged.
    shared = derive(packet(11, air_temperature_c=32.0), {"air_temperature_c": entry(24.0, pair(28.0, 4.0))})
    assert not pair_check_texts(shared) and FLAG not in shared["data_quality_labels"]
    only_one = derive(packet(11, air_temperature_c=32.0), {"air_temperature_c": entry(24.0, pair(20.0, 4.0))})
    assert len(pair_check_texts(only_one)) == 1


def test_a_probe_with_both_moisture_names_gets_one_text():
    baseline = {"soil_moisture_pct": entry(50.0, pair(50.0, 0.0)), "substrate_moisture_pct": entry(50.0, pair(50.0, 0.0))}
    result = derive(packet(11, soil_moisture_pct=60.0, substrate_moisture_pct=61.0), baseline)
    assert len(pair_check_texts(result)) == 1 and "pair check: soil_moisture_pct on" in pair_check_texts(result)[0]
    assert result["pair_disagreement_fields"] == ["soil_moisture_pct"]
    # Only the second name's entry: its own text.
    second = derive(packet(11, soil_moisture_pct=50.0, substrate_moisture_pct=61.0),
                    {"soil_moisture_pct": entry(50.0, pair(50.0, 0.0)), "substrate_moisture_pct": entry(50.0, pair(50.0, 0.0))})
    assert len(pair_check_texts(second)) == 1 and "pair check: substrate_moisture_pct on" in pair_check_texts(second)[0]
    assert second["pair_disagreement_fields"] == ["substrate_moisture_pct"]


def test_other_fields_of_the_same_reading_each_get_their_own_text():
    baseline = {"air_temperature_c": entry(24.0, pair(20.0, 0.0)), "humidity_pct": entry(60.0, pair(40.0, 0.0))}
    result = derive(packet(11, air_temperature_c=24.0, humidity_pct=60.0), baseline)
    assert len(pair_check_texts(result)) == 2
    assert result["pair_disagreement_fields"] == ["air_temperature_c", "humidity_pct"]


def test_no_pair_changes_nothing():
    sensor = packet(11)
    bare = {"air_temperature_c": entry(24.0), "humidity_pct": entry(60.0), "substrate_moisture_pct": entry(50.0)}
    assert derive(sensor, bare) == derive(sensor, None) == derive(sensor, {})
    # A pair that does not flag leaves the whole result as it was without one.
    quiet = {"air_temperature_c": entry(24.0, pair(24.0, 0.0)), "humidity_pct": entry(60.0, pair(60.0, 0.5)),
             "substrate_moisture_pct": entry(50.0, pair(50.0, 0.0))}
    assert derive(sensor, quiet) == derive(sensor, bare)
    assert "pair_disagreement_fields" not in derive(sensor, quiet)
    # Same for a pair on a field that has no pair limit.
    other = {"ph": entry(6.0, pair(9.0, 0.0)), "substrate_temperature_c": entry(20.0, pair(50.0, 0.0))}
    plain = {"ph": entry(6.0), "substrate_temperature_c": entry(20.0)}
    assert derive(packet(11, substrate_temperature_c=20.0), other) == derive(packet(11, substrate_temperature_c=20.0), plain)


def test_no_current_reading_means_no_pair_check():
    sensor = packet(11)
    del sensor["humidity_pct"]
    assert not pair_check_texts(derive(sensor, {"humidity_pct": entry(60.0, pair(10.0, 0.0))}))


def bad_pairs():
    good = pair(20.0, 0.0)
    return [
        "x", 5, [1], [], True,
        {**good, "offset": "0"}, {**good, "offset": True}, {**good, "offset": None}, {**good, "offset": math.nan},
        {**good, "offset": math.inf},
        {**good, "partner_value": "20"}, {**good, "partner_value": False}, {**good, "partner_value": None},
        {**good, "partner_value": -math.inf},
        {**good, "n": 0}, {**good, "n": True}, {**good, "n": 1.5}, {**good, "n": "20"}, {**good, "n": -3},
        {**good, "partners": 0}, {**good, "partners": True}, {**good, "partners": 2.0}, {**good, "partners": None},
        {**good, "partner_device": 5}, {**good, "partner_device": ["a"]},
        {**good, "device": 5}, {**good, "device": None},
        {k: v for k, v in good.items() if k != "offset"}, {k: v for k, v in good.items() if k != "partner_value"},
        {k: v for k, v in good.items() if k != "n"}, {k: v for k, v in good.items() if k != "partners"},
        {k: v for k, v in good.items() if k != "device"},
    ]


@pytest.mark.parametrize("bad", bad_pairs(), ids=lambda b: repr(b)[:70])
def test_a_malformed_pair_is_ignored_by_the_check_itself(bad):
    labels, suspects, checks = [], [], []
    fields = []
    apply_persistent_checks(packet(11, air_temperature_c=24.0), HISTORY, {"air_temperature_c": entry(24.0, bad)},
                            labels, suspects, checks, fields)
    assert labels == [] and suspects == [] and checks == [] and fields == []
    assert FLAG not in derive(packet(11, air_temperature_c=24.0), {"air_temperature_c": entry(24.0, bad)})["data_quality_labels"]


def test_a_good_pair_is_not_ignored_by_the_same_calls():
    labels, suspects, checks, fields = [], [], [], []
    apply_persistent_checks(packet(11, air_temperature_c=24.0), HISTORY, {"air_temperature_c": entry(24.0, pair(20.0, 0.0))},
                            labels, suspects, checks, fields)
    assert labels == [FLAG] and suspects == ["air_temperature_c"] and len(checks) == 1 and fields == ["air_temperature_c"]
    # `pair_fields` is optional.
    labels, suspects, checks = [], [], []
    apply_persistent_checks(packet(11, air_temperature_c=24.0), HISTORY, {"air_temperature_c": entry(24.0, pair(20.0, 0.0))},
                            labels, suspects, checks)
    assert labels == [FLAG] and len(checks) == 1


def evaluate_body(baseline, **extra):
    return {"farm_context": FARM, "sensor": packet(11, humidity_pct=58.1), "history": HISTORY, "mode": "rules_only",
            "stream_baseline": baseline, **extra}


def test_endpoint_carries_the_pair_result_through_to_the_pipeline_response():
    client = TestClient(app)
    good = {"humidity_pct": entry(58.1, pair(70.0, -1.5))}
    response = client.post("/v1/pipeline/evaluate", json=evaluate_body(good))
    assert response.status_code == 200
    quality = response.json()["sensor_quality"]
    assert quality["safe_next_checks"][0].startswith("pair check: humidity_pct on climate-1 is 10.4 %RH lower")
    assert quality["pair_disagreement_fields"] == ["humidity_pct"] and "humidity_pct" in quality["suspect_fields"]
    assert FLAG in quality["data_quality_labels"]
    # It survives the merge of other devices' checks (Design 4b: Core writes the column from this key).
    merged = client.post("/v1/pipeline/evaluate", json=evaluate_body(
        good, known_vetoed_fields=["air_temperature_c"], known_data_quality_labels=["stuck_value"],
        known_safe_next_checks=["inspect air_temperature_c: the same value for 50 minutes"]))
    assert merged.status_code == 200
    merged_quality = merged.json()["sensor_quality"]
    assert merged_quality["pair_disagreement_fields"] == ["humidity_pct"] and "from_device_checks" in merged_quality
    # Nothing flagged: the key is absent.
    quiet = client.post("/v1/pipeline/evaluate", json=evaluate_body({"humidity_pct": entry(58.1, pair(58.0, 0.0))}))
    assert quiet.status_code == 200 and "pair_disagreement_fields" not in quiet.json()["sensor_quality"]
    none = client.post("/v1/pipeline/evaluate", json=evaluate_body(None))
    assert none.status_code == 200 and "pair_disagreement_fields" not in none.json()["sensor_quality"]


def test_endpoint_rejects_a_malformed_pair_with_422():
    client = TestClient(app)
    for bad in bad_pairs():
        if isinstance(bad, dict) and any(isinstance(v, float) and not math.isfinite(v) for v in bad.values()):
            continue  # JSON cannot carry NaN or infinity
        if bad is None:
            continue
        body = evaluate_body({"humidity_pct": entry(58.1, bad)})
        assert client.post("/v1/pipeline/evaluate", json=body).status_code == 422, bad
    # An absent or null `pair` is fine, as for the other optional keys.
    assert client.post("/v1/pipeline/evaluate", json=evaluate_body({"humidity_pct": {**entry(58.1), "pair": None}})).status_code == 200
    assert client.post("/v1/pipeline/evaluate", json=evaluate_body({"humidity_pct": entry(58.1)})).status_code == 200


def test_pair_flag_says_nothing_about_a_field_without_a_pair_limit():
    assert "substrate_temperature_c" not in PAIR_DRIFT_LIMITS and set(PAIR_DRIFT_LIMITS) <= set(STEP_LIMITS)


def test_limits_match_core_and_the_fast_change_step_is_a_third():
    # Core's pair_reference skips a reading whose own step is at least a third of the limit; the two files must agree.
    # trusted_baseline.py is standard library only (the scorer loads it the same way), so it loads by path.
    path = REPO / "services" / "core" / "app" / "trusted_baseline.py"
    spec = importlib.util.spec_from_file_location("trusted_baseline_for_pair_pin", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.PAIR_DRIFT_LIMITS == PAIR_DRIFT_LIMITS
    assert set(module.PAIR_FAST_STEP) == set(PAIR_DRIFT_LIMITS)
    for field, limit in PAIR_DRIFT_LIMITS.items():
        assert module.PAIR_FAST_STEP[field] == limit / 3, field
