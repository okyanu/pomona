"""Tests for the fake greenhouse. Run with the Core venv: it provides pytest and Core's SensorEvent."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "examples" / "simulators"
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(ROOT / "services" / "core"))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import fake_greenhouse as fg
from pydantic import ValidationError

from app.schemas import SensorEvent

A, B = "greenhouse-a", "greenhouse-b"
START = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def make_clock(step_s: float = 30.0):
    state = {"now": START}

    def clock() -> datetime:
        now = state["now"]
        state["now"] = now + timedelta(seconds=step_s)
        return now

    return clock


def steps(*items):
    """Scenario steps: ("start", tick, name, zone, field, params) or ("stop", tick, name, zone)."""
    out = []
    for item in items:
        if item[0] == "start":
            _, tick, name, zone, field, params = item
            out.append({"at_tick": tick, "start": name, "zone": zone, "field": field, "params": params})
        else:
            _, tick, name, zone = item
            out.append({"at_tick": tick, "stop": name, "zone": zone})
    return {"steps": out}


def run_sim(ticks, scenario=None, seed=42, **kwargs):
    """All readings, in order: a list of (event or None, truth) pairs."""
    sim = fg.Simulation(seed=seed, clock=make_clock(), scenario=scenario, **kwargs)
    return [(r.event, r.truth) for _ in range(ticks) for r in sim.step()]


def by_zone(rows, zone):
    return [(event, truth) for event, truth in rows if truth["zone_id"] == zone]


def run_main(tmp_path, tag, *args):
    out, truth = tmp_path / f"{tag}-events.jsonl", tmp_path / f"{tag}-truth.jsonl"
    code = fg.main(["--dry-run", "--out", str(out), "--truth-log", str(truth), *args], clock=make_clock())
    assert code == 0
    return out.read_bytes(), truth.read_bytes()


# --- Determinism ---------------------------------------------------------------------------

def test_same_seed_and_scenario_is_byte_identical(tmp_path, capsys):
    scenario = str(SIM_DIR / "scenarios" / "demo.json")
    first = run_main(tmp_path, "one", "--scenario", scenario, "--ticks", "60")
    second = run_main(tmp_path, "two", "--scenario", scenario, "--ticks", "60")
    other = run_main(tmp_path, "three", "--scenario", scenario, "--ticks", "60", "--seed", "8")
    assert first == second
    assert first[0] != other[0] and first[1] != other[1]


def test_registry_has_all_faults_and_events():
    sensor = {"stuck", "drift", "jump", "spike", "noisy", "dropout", "dead_clock", "plausible_offset"}
    real = {"dry_zone", "heat_spike", "humid_night", "nutrient_over_concentration"}
    assert set(fg.REGISTRY) == sensor | real
    assert {n for n, c in fg.REGISTRY.items() if c.kind == "sensor_fault"} == sensor
    assert {n for n, c in fg.REGISTRY.items() if c.kind == "real_event"} == real


# --- Sensor faults change only what is sent -------------------------------------------------

FAULTS = [
    ("stuck", A, "air_temperature_c", {}),
    ("drift", A, "ec_ms_cm", {"rate_per_min": 0.5}),
    ("jump", B, "ph", {"offset": 1.5}),
    ("spike", B, "ph", {}),
    ("noisy", A, "humidity_pct", {}),
    ("noisy", A, "soil_moisture_pct", {}),
    ("plausible_offset", B, "ec_ms_cm", {}),
]


@pytest.mark.parametrize("name,zone,field,params", FAULTS)
def test_sensor_fault_changes_only_its_target_field(name, zone, field, params):
    ticks = 16
    base = run_sim(ticks)
    faulty = run_sim(ticks, steps(("start", 4, name, zone, field, params), ("stop", 12, name, zone)))
    expected = {field} if field != "soil_moisture_pct" else {"soil_moisture_pct", "substrate_moisture_pct"}
    changed = set()
    for (b_event, b_truth), (f_event, f_truth) in zip(base, faulty):
        assert f_truth["true"] == b_truth["true"]  # the truth never moves
        if f_truth["zone_id"] != zone:
            assert f_event == b_event  # the other zone is identical
            continue
        diff = {k for k in b_event if f_event[k] != b_event[k]}
        assert diff <= expected
        changed |= diff
        assert f_truth["expect"]["kind"] == ("sensor_fault" if f_truth["active_faults"] else "normal")
    assert changed == expected
    in_window = [t for _, t in faulty if t["zone_id"] == zone and t["active_faults"]]
    assert in_window and all(set(t["expect"]["forbid_domain_cards_from"]) == expected for t in in_window)
    assert all(t["expect"]["detectable"] == (name != "plausible_offset") for t in in_window)


def test_spike_is_a_single_sample_and_removes_itself():
    rows = by_zone(run_sim(10, steps(("start", 3, "spike", B, "ph", {}))), B)
    assert [e["ph"] for e, _ in rows if e["ph"] > 12] == [13.0]
    assert [bool(t["active_faults"]) for _, t in rows].count(True) == 1
    assert rows[-1][1]["active_faults"] == []


def test_drift_grows_with_real_time():
    rows = by_zone(run_sim(8, steps(("start", 2, "drift", A, "ec_ms_cm", {"rate_per_min": 0.1}))), A)
    base = by_zone(run_sim(8), A)
    gaps = [round(r[0]["ec_ms_cm"] - b[0]["ec_ms_cm"], 2) for r, b in zip(rows, base)]
    assert gaps[:4] == [0.0, 0.0, 0.0, 0.05]  # 0.1 per real minute, 30 s ticks
    assert gaps[-1] == pytest.approx(0.25, abs=0.01)


def test_stuck_holds_the_last_sent_value():
    rows = by_zone(run_sim(10, steps(("start", 4, "stuck", A, "air_temperature_c", {}))), A)
    last = rows[3][0]["air_temperature_c"]
    assert {e["air_temperature_c"] for e, _ in rows[4:]} == {last}


def test_dropout_publishes_nothing_for_that_zone_only():
    scenario = steps(("start", 3, "dropout", B, None, {}), ("stop", 6, "dropout", B))
    rows = run_sim(9, scenario)
    base = run_sim(9)
    for (event, truth), (b_event, _) in zip(rows, base):
        dropped = truth["zone_id"] == B and 3 <= truth["tick"] < 6
        assert (event is None) == dropped
        assert truth["published"] is (not dropped)
        if dropped:
            assert truth["reason"] == "dropout" and truth["sent"] is None and truth["sequence"] is None
            assert truth["expect"]["kind"] == "not_published"
        elif truth["zone_id"] == A:
            assert event == b_event
    sequences = [e["sequence"] for e, t in rows if t["zone_id"] == B and e]
    assert sequences == list(range(len(sequences)))


def test_dead_clock_sends_1970_and_core_rejects_it():
    rows = by_zone(run_sim(6, steps(("start", 2, "dead_clock", A, None, {}), ("stop", 4, "dead_clock", A))), A)
    for event, truth in rows:
        dead = 2 <= truth["tick"] < 4
        assert (event["timestamp"] == "1970-01-01T00:00:00Z") is dead
        assert truth["expect"]["kind"] == ("rejected_by_core" if dead else "normal")
        if dead:
            with pytest.raises(ValidationError):
                SensorEvent(**event)
        else:
            SensorEvent(**event)


# --- Real events change the truth ----------------------------------------------------------

# Fast params so the crossing happens inside a short test (the defaults ramp over 20-60 minutes).
EVENTS = [
    ("heat_spike", {"ramp_min": 5}, A, "air_temperature_c", "heat_stress",
     lambda t: t["air_temperature_c"] >= 30),
    ("humid_night", {"ramp_min": 5}, B, "humidity_pct", "fungal_pressure",
     lambda t: t["humidity_pct"] >= 85),
    ("nutrient_over_concentration", {"ramp_min": 5}, B, "ec_ms_cm", "high_ec",
     lambda t: t["ec_ms_cm"] >= 4.5),
    ("dry_zone", {"drying_pct_per_hour": 600}, A, "soil_moisture_pct", "water_level_risk",
     lambda t: t["soil_moisture_pct"] < 10),
]


@pytest.mark.parametrize("name,params,zone,field,label,crossed", EVENTS)
def test_real_event_changes_truth_and_label_follows_the_crossing(name, params, zone, field, label, crossed):
    ticks = 40
    base = run_sim(ticks)
    rows = run_sim(ticks, steps(("start", 6, name, zone, None, params)))
    other = B if zone == A else A
    assert by_zone(rows, other) == by_zone(base, other)  # an event stays in its zone
    assert by_zone(base, zone)[-1][1]["true"][field] != by_zone(rows, zone)[-1][1]["true"][field]
    assert all(not t["expect"]["expected_labels"] for _, t in base)

    first_label = None
    for (event, truth), (b_event, b_truth) in zip(rows, base):
        if truth["zone_id"] != zone:
            continue
        labels = truth["expect"]["expected_labels"]
        assert (label in labels) == crossed(truth["true"])  # label only when the truth crosses
        assert truth["expect"]["forbid_domain_cards_from"] == []  # readings are correct
        if truth["tick"] < 6:
            assert truth["true"] == b_truth["true"] and event == b_event
        else:
            assert truth["expect"]["kind"] == "real_event"
        if label in labels and first_label is None:
            first_label = truth["tick"]
    assert first_label is not None and first_label > 6  # active for a while before it crosses


def test_dry_zone_needs_a_substrate_zone():
    sim = fg.Simulation(clock=make_clock())
    with pytest.raises(ValueError):
        sim.start("dry_zone", B)


def test_event_and_fault_together_are_kind_both():
    scenario = steps(("start", 2, "heat_spike", A, None, {}), ("start", 3, "jump", A, "ph", {}))
    rows = by_zone(run_sim(6, scenario), A)
    assert [t["expect"]["kind"] for _, t in rows] == ["normal", "normal", "real_event", "both", "both", "both"]


def test_event_ramps_back_down_after_stop():
    scenario = steps(("start", 2, "heat_spike", A, None, {"ramp_min": 5}), ("stop", 16, "heat_spike", A))
    rows = by_zone(run_sim(40, scenario), A)
    assert rows[-1][1]["active_events"] == []
    assert max(t["true"]["air_temperature_c"] for _, t in rows) >= 32.5
    assert rows[-1][1]["expect"]["expected_labels"] == []


def test_default_speed_is_real_time_and_ramps_are_wall_minutes_at_any_speed():
    sim = fg.Simulation(clock=make_clock())
    assert sim.dt_h == pytest.approx(30 / 3600)  # --sim-speed 1: one tick is one interval of sim time

    def levels(speed):
        scenario = steps(("start", 1, "heat_spike", A, None, {"ramp_min": 10}))
        rows = by_zone(run_sim(8, scenario, sim_speed=speed), A)
        return [t["active_events"][0]["level"] for _, t in rows if t["active_events"]]

    assert levels(1.0) == levels(120.0)
    assert levels(1.0)[-1] == pytest.approx(7 * 0.5 / 10, abs=0.01)  # 30 s ticks, 10 minute ramp


def test_recovering_from_marks_the_eleven_samples_after_a_sensor_fault():
    scenario = steps(("start", 3, "jump", B, "ph", {}), ("stop", 6, "jump", B),
                     ("start", 30, "dropout", B, None, {}), ("stop", 33, "dropout", B))
    rows = by_zone(run_sim(40, scenario), B)
    marks = [t["expect"]["recovering_from"] for _, t in rows]
    assert marks[:6] == [[]] * 6
    assert marks[6:17] == [["jump"]] * 11 and marks[17:] == [[]] * 23  # a dropout leaves no bad history
    assert all(t["expect"]["recovering_from"] == [] for _, t in by_zone(run_sim(40), B))


def test_plausible_offset_flags_its_onset_step_only_when_started_mid_stream():
    late = by_zone(run_sim(30, steps(("start", 4, "plausible_offset", A, "ec_ms_cm", {}))), A)
    assert [t["expect"]["onset_step"] for _, t in late] == [False] * 4 + [True] * 11 + [False] * 15
    assert all(not t["expect"]["detectable"] for _, t in late[4:])
    first = by_zone(run_sim(30, steps(("start", 0, "plausible_offset", A, "ec_ms_cm", {}))), A)
    assert not any(t["expect"]["onset_step"] for _, t in first)


# --- Timestamps, payload and Core --------------------------------------------------------

def test_timestamps_are_the_injected_wall_clock_in_utc():
    clock = make_clock(30.0)
    sim = fg.Simulation(clock=clock, start_hour=8.0)
    for tick in range(5):
        for reading in sim.step():
            stamp = datetime.fromisoformat(reading.event["timestamp"])
            assert stamp.utcoffset() == timedelta(0)
            assert stamp == START + timedelta(seconds=30 * tick)
            assert reading.truth["wall_timestamp"] == reading.event["timestamp"]
            assert reading.truth["sim_hour"] != stamp.hour + stamp.minute / 60  # sim time stays in the log


def test_events_validate_against_core_and_carry_identity_fields():
    rows = run_sim(30)
    for event, truth in rows:
        parsed = SensorEvent(**event)
        assert parsed.source == "fake_greenhouse" and parsed.schema_version == "1.0"
        assert truth["sent"] == event
    for zone in (A, B):
        zone_rows = [e for e, _ in by_zone(rows, zone)]
        assert [e["sequence"] for e in zone_rows] == list(range(30))
        assert len({e["boot_id"] for e in zone_rows}) == 1
    assert run_sim(1, seed=1)[0][0]["boot_id"] != run_sim(1, seed=2)[0][0]["boot_id"]


def test_hydroponic_zone_sends_a_placeholder_and_no_substrate_fields():
    event, truth = by_zone(run_sim(3), B)[1]
    assert event["system_type"] == "hydroponic_greenhouse" and event["soil_moisture_pct"] == 50.0
    assert not {"substrate_temperature_c", "substrate_moisture_pct", "weather", "water_temperature_c"} & set(event)
    assert truth["placeholder_fields"] == ["soil_moisture_pct"] and "water_temperature_c" in truth["true"]
    a_event, a_truth = by_zone(run_sim(3), A)[1]
    assert a_event["substrate_moisture_pct"] == a_event["soil_moisture_pct"] and a_truth["placeholder_fields"] == []
    assert {"weather", "zone_area_m2", "crop_kc", "npk_target"} <= set(a_event)


def test_demo_scenario_publishes_only_what_core_accepts_except_dead_clock():
    scenario = fg.load_scenario(SIM_DIR / "scenarios" / "demo.json")
    rows = run_sim(scenario["duration_ticks"], scenario, seed=scenario["seed"])
    kinds = {t["expect"]["kind"] for _, t in rows}
    assert kinds == {"normal", "sensor_fault", "real_event", "rejected_by_core", "not_published"}
    for event, truth in rows:
        if truth["expect"]["kind"] == "rejected_by_core":
            with pytest.raises(ValidationError):
                SensorEvent(**event)
        elif event is not None:
            SensorEvent(**event)
    labels = {label for _, t in rows for label in t["expect"]["expected_labels"]}
    assert labels == {"heat_stress", "fungal_pressure", "high_ec", "water_level_risk"}


# --- Normal baseline stays clear of every card threshold ----------------------------------

def test_normal_run_keeps_margin_from_every_threshold():
    for seed in (42, 1, 2):
        rows = run_sim(24 * 3, seed=seed, sim_speed=120.0)  # three simulated days (time-lapse), both zones
        for event, truth in rows:
            for values in (truth["true"], event):
                assert 17.5 <= values["air_temperature_c"] <= 29.0  # cold <= 16, heat >= 30
                assert values["humidity_pct"] <= 76.0  # fungal >= 85
                assert fg.vpd_kpa(values["air_temperature_c"], values["humidity_pct"]) >= 0.45  # fungal < 0.4
                assert 1.2 <= values["ec_ms_cm"] <= 3.8  # high >= 4.5, hydroponic low <= 0.8
                assert 5.6 <= values["ph"] <= 6.8  # high >= 7.2, low <= 5.3
                if "substrate_temperature_c" in values:
                    assert 17.0 <= values["substrate_temperature_c"] <= 28.0
                if truth["zone_id"] == A:
                    assert 35.0 <= values["soil_moisture_pct"] <= 74.0  # water risk < 10 / > 85, 28 / 78
            assert truth["expect"] == {"kind": "normal", "expected_labels": [], "forbid_domain_cards_from": [],
                                       "detectable": True, "onset_step": False, "recovering_from": []}


def test_real_time_run_changes_slowly_per_pomona_history_window():
    """Pomona's drift check compares readings 11 packets apart: a normal day must not move pH/EC fast."""
    rows = run_sim(720)  # six simulated hours at 30 s samples, both zones
    assert any(t["true"].get("irrigated") for _, t in rows)  # irrigation pulses happen in this window
    for zone in (A, B):
        sent = [e for e, _ in by_zone(rows, zone)]
        for field, limit in (("ph", 0.2), ("ec_ms_cm", 0.25)):
            for i in range(len(sent) - 10):
                window = [e[field] for e in sent[i:i + 11]]
                assert max(window) - min(window) < limit, (zone, field, i)
        assert all(fg.vpd_kpa(e["air_temperature_c"], e["humidity_pct"]) >= 0.45 for e in sent)


# --- CLI ---------------------------------------------------------------------------------

def test_smoke_scenario_runs_end_to_end(tmp_path):
    events, truth = run_main(tmp_path, "smoke", "--scenario", str(SIM_DIR / "scenarios" / "smoke.json"))
    event_lines = [json.loads(line) for line in events.decode().splitlines()]
    truth_lines = [json.loads(line) for line in truth.decode().splitlines()]
    assert len(truth_lines) == 12 * 2  # duration_ticks from the scenario, two zones
    assert len(event_lines) == 12 * 2 - 2  # two dropped ticks in greenhouse-b
    assert {t["expect"]["kind"] for t in truth_lines} == {"normal", "sensor_fault", "real_event", "not_published"}


def test_ticks_flag_overrides_the_scenario_and_truth_log_is_not_in_events(tmp_path):
    events, truth = run_main(tmp_path, "short", "--scenario", str(SIM_DIR / "scenarios" / "smoke.json"),
                             "--ticks", "3")
    assert len(truth.splitlines()) == 6 and len(events.splitlines()) == 6
    assert b"expect" not in events and b"true" not in events
