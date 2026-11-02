"""The engine path: no network, the vendored files are the repo's, and a session agrees with the offline scorer."""

import json
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from helpers import A, B, CAL, SPACE, START, STOP

import fake_greenhouse as fg
import game
import score_fake_greenhouse as score

REPO = SPACE.parents[1]


def test_the_engine_runs_with_sockets_blocked(monkeypatch):
    """A whole session (physics, Core's checks, the pipeline in rules_only, the alert monitor, the grader) needs no network."""
    def blocked(*args, **kwargs):
        raise AssertionError("the engine tried to use the network")

    session = game.Session.start_new(8)
    for name, patch in (("socket", blocked), ("create_connection", blocked), ("getaddrinfo", blocked),
                        ("gethostbyname", blocked)):
        monkeypatch.setattr(socket, name, patch)
    try:
        session.command({"op": "start", "name": "jump", "zone": B, "field": "ph"})
        session.advance(80)
        session.command({"op": "start", "name": "heat_spike", "zone": A})
        session.advance(60)
        view = session.view()
        assert view["clock"]["tick"] == game.WARMUP_TICKS + 140
        assert any(card["sensor"] for z in view["zones"] for card in z["cards"])
        assert view["episodes"]
    finally:
        session.close()


def test_the_pipeline_audit_writes_are_off():
    pipeline = game.ipp.load_pipeline()
    assert pipeline.write_pipeline_audit({"anything": 1}) is None  # replaced by a no-op: no files are written


def test_vendor_matches_the_repo_and_has_what_the_engine_loads():
    result = subprocess.run([sys.executable, str(REPO / "scripts" / "build_fool_space.py"), "--check"],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    info = json.loads((SPACE / "vendor" / "BUILD_INFO.json").read_text())
    assert info["commit"] and len(info["short_commit"]) == 7 and isinstance(info["dirty"], bool)
    assert "examples/simulators/inprocess_pomona.py" in info["files"]
    assert "services/automation-engine/app/rules.yaml" in info["files"]
    assert game.info()["build"]["short_commit"] == info["short_commit"]


def test_the_space_imports_from_vendor_alone():
    """A fresh interpreter, only the Space folder on the path: nothing may come from the repo checkout."""
    code = ("import sys; sys.path.insert(0, %r); import game, inprocess_pomona as ipp; "
            "s = game.Session.start_new(1); s.advance(5); s.close(); "
            "files = [m.__file__ for m in sys.modules.values() if getattr(m, '__file__', None)]; "
            "bad = [f for f in files if %r in f and %r not in f]; print('BAD', bad) if bad else print('OK')"
            % (str(SPACE), str(REPO), str(SPACE)))
    result = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, cwd="/")
    assert result.returncode == 0 and result.stdout.strip() == "OK", result.stdout + result.stderr


# --- A session against the offline scorer ---------------------------------------------------------------

def fake_clock(step_s=30.0):
    state = {"now": game.START}

    def now():
        value = state["now"]
        state["now"] = value + timedelta(seconds=step_s)
        return value

    return now


DEMO_LIKE = [  # (command, ticks to run before the next one): faults, events, a calibration, a hidden trick
    ({"op": "start", "name": "spike", "zone": A, "field": "ph"}, 30),
    ({"op": "start", "name": "jump", "zone": B, "field": "ph"}, 20),
    ({"op": "stop", "name": "jump", "zone": B, "field": "ph"}, 15),
    ({"op": "start", "name": "drift", "zone": A, "field": "ec_ms_cm"}, 30),
    ({"op": "stop", "name": "drift", "zone": A, "field": "ec_ms_cm"}, 20),
    ({"op": "start", "name": "stuck", "zone": A, "field": "air_temperature_c"}, 20),
    ({"op": "stop", "name": "stuck", "zone": A, "field": "air_temperature_c"}, 15),
    ({"op": "start", "name": "dropout", "zone": B}, 15),
    ({"op": "stop", "name": "dropout", "zone": B}, 10),
    ({"op": "start", "name": "dead_clock", "zone": B}, 10),
    ({"op": "stop", "name": "dead_clock", "zone": B}, 10),
    ({"op": "start", "name": "plausible_offset", "zone": A, "field": "ec_ms_cm"}, 30),
    ({"op": "stop", "name": "plausible_offset", "zone": A, "field": "ec_ms_cm"}, 20),
    ({"op": "start", "name": "heat_spike", "zone": A}, 70),
    ({"op": "start", "name": "nutrient_over_concentration", "zone": B}, 80),
    ({"op": "calibrate", "zone": B, "field": "ec_ms_cm"}, 40),
    ({"op": "start", "name": "humid_night", "zone": B}, 70),
    ({"op": "hidden"}, 60),
    ({"op": "stop", "name": "heat_spike", "zone": A}, 30),
    ({"op": "stop", "name": "nutrient_over_concentration", "zone": B}, 30),
    ({"op": "stop", "name": "humid_night", "zone": B}, 30),
    ({"op": "reveal"}, 60),
]


def outcomes(real, faults, alarms):
    """Everything the grader decides, in a form two runs can be compared on."""
    return ([(e["zone"], e["label"], e["rule"], tuple(e["events"]), e["start_tick"], e["end_tick"], e["outcome"],
              e.get("raised"), e.get("cant_confirm_from")) for e in real],
            [(e["zone"], e["fault"], e["field"], e["start_tick"], e["end_tick"], e["outcome"], e.get("raised"),
              [(w["rule"], w["tick"]) for w in e["wrong_cards"]]) for e in faults],
            [(a["zone"], a["rule"], a["tick"]) for a in alarms])


def test_a_scripted_session_gets_the_offline_scorers_verdicts(tmp_path):
    session = game.Session.start_new(7)
    try:
        for command, ticks in DEMO_LIKE:
            session.command(command)
            session.advance(ticks)
        exported = session.export()
        mine = outcomes(*(session.grade()[k] for k in ("real", "faults", "false_alarms")))
        my_info, my_events = dict(session.frame_info), list(session.alert_events)
    finally:
        session.close()
    assert exported["duration_ticks"] > 600 and any(s["source"] == "hidden" for s in exported["steps"])

    # the exported file is a real scenario: the simulator's loader takes it, and a run of it on the same clock
    # gives a truth log the offline scorer grades the same way
    path = tmp_path / "session.json"
    path.write_text(json.dumps(exported))
    fg.load_scenario(path)
    truth = tmp_path / "truth.jsonl"
    assert fg.main(["--dry-run", "--fast", "--out", str(tmp_path / "events.jsonl"), "--truth-log", str(truth),
                    "--scenario", str(path)], clock=fake_clock()) == 0
    rows = score.load_truth(truth)
    rules, defaults = score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()), score.alert_defaults()
    events, info, _ = score.replay_offline(rows, rules, defaults)
    grader = score.Grader(rows, events, rules, defaults, info)
    real = grader.real_episodes()
    faults = grader.fault_episodes(real)
    theirs = outcomes(real, faults, grader.false_alarms(real, faults))
    assert mine == theirs
    assert {(z, t): i for (z, t), i in my_info.items()} == info
    assert my_events == events
    kinds = {e[6] for e in mine[0]} | {e[5] for e in mine[1]}
    assert {"caught", "undetectable", "rejected_by_core", "not_published"} <= kinds, kinds  # a varied, real run


def test_the_demo_scenario_graded_through_a_session_equals_the_scorer(tmp_path):
    """The repo's own demo.json, fed to a session as its steps: the same verdicts as the scorer on its truth log."""
    scenario = json.loads((REPO / "examples" / "simulators" / "scenarios" / "demo.json").read_text())
    session = game.Session(scenario["seed"])
    session.sim.steps = list(scenario["steps"])  # the scenario's own steps, applied by the simulator as in `make fake-greenhouse`
    try:
        session.advance(scenario["duration_ticks"])
        mine = outcomes(*(session.grade()[k] for k in ("real", "faults", "false_alarms")))
    finally:
        session.close()
    truth = tmp_path / "truth.jsonl"
    path = REPO / "examples" / "simulators" / "scenarios" / "demo.json"
    assert fg.main(["--dry-run", "--fast", "--out", str(tmp_path / "e.jsonl"), "--truth-log", str(truth),
                    "--scenario", str(path)], clock=fake_clock()) == 0
    rows = score.load_truth(truth)
    rules, defaults = score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()), score.alert_defaults()
    events, info, _ = score.replay_offline(rows, rules, defaults)
    grader = score.Grader(rows, events, rules, defaults, info)
    real = grader.real_episodes()
    faults = grader.fault_episodes(real)
    assert mine == outcomes(real, faults, grader.false_alarms(real, faults))
    assert len(mine[0]) + len(mine[1]) >= 8


def test_the_page_download_is_a_scenario_make_fake_greenhouse_loads(tmp_path):
    session = game.Session.start_new(33)
    try:
        for command in ({"op": "start", "name": "stuck", "zone": A, "field": "humidity_pct"},
                        {"op": "calibrate", "zone": A, "field": "ph"}, {"op": "start", "name": "dry_zone", "zone": A}):
            session.command(command)
            session.advance(10)
        exported = session.export()
    finally:
        session.close()
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(exported))
    loaded = fg.load_scenario(path)
    assert loaded["seed"] == 33 and [s["at_tick"] for s in loaded["steps"]] == sorted(s["at_tick"] for s in loaded["steps"])
    assert {next(k for k in ("start", "stop", "calibrate") if k in s) for s in loaded["steps"]} == {"start", "calibrate"}


# --- The four lies that used to fool Pomona, and the real event that must stay a real event -------------------

@pytest.mark.parametrize("name,field,zone", [
    ("stuck", "ph", A), ("stuck", "ph", B), ("stuck", "ec_ms_cm", A), ("stuck", "ec_ms_cm", B),
    ("jump", "air_temperature_c", A), ("jump", "air_temperature_c", B),
    ("noisy", "humidity_pct", A), ("noisy", "humidity_pct", B),
])
def test_the_four_old_gaps_are_caught_after_forty_minutes(name, field, zone):
    session = game.Session.start_new(1)
    try:
        session.command({"op": "start", "name": name, "zone": zone, "field": field})
        session.advance(80)  # 40 simulated minutes
        session.command({"op": "stop", "name": name, "zone": zone, "field": field})
        session.advance(40)
        (fault,) = session.grade()["faults"]
        assert (fault["fault"], fault["field"], fault["outcome"]) == (name, field, "caught"), fault
        assert not fault["wrong_cards"] and not session.grade()["false_alarms"]
    finally:
        session.close()


@pytest.mark.parametrize("zone", [A, B])
def test_a_heat_spike_stays_a_real_event_and_raises_the_heat_card_not_a_sensor_lie(zone):
    session = game.Session.start_new(1)
    try:
        session.command({"op": "start", "name": "heat_spike", "zone": zone})
        session.advance(120)
        session.command({"op": "stop", "name": "heat_spike", "zone": zone})
        session.advance(60)
        board = session.grade()
        (real,) = board["real"]
        assert (real["rule"], real["outcome"]) == ("heat_stress_check", "caught"), real
        assert not board["faults"] and not board["false_alarms"]
        assert not any(e["rule_id"] == "sensor_check" for e in session.alert_events)  # no check-the-sensor card either
    finally:
        session.close()
