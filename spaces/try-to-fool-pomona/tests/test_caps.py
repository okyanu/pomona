"""Caps: simulated hours, one request's size, commands per session; and the sliced rebuild."""

import json

import pytest
from helpers import A, B, START, STOP, act, play, refused

import engine_api
import game


def test_the_caps_are_the_ones_in_the_plan():
    assert game.MAX_HOURS == 24 and game.MAX_TICKS == 2880 and game.TICK_S == 30
    assert game.MAX_ADVANCE_TICKS == 240 and game.MAX_COMMANDS == 300


def test_a_session_stops_at_the_cap_and_reveals_the_hidden_trick(engine, monkeypatch):
    monkeypatch.setattr(game, "MAX_TICKS", 60)
    start = act(engine, seed=4)
    result = act(engine, scenario=start["scenario"], commands=[{"op": "hidden"}], advance=1)
    result = act(engine, scenario=result["scenario"], advance=game.MAX_ADVANCE_TICKS)  # asks for more than is left
    clock = result["view"]["clock"]
    assert clock["tick"] == 60 and clock["at_cap"] is True
    assert result["view"]["hidden"]["revealed"] is True, "the end of the session reveals the blind test"
    again = act(engine, scenario=result["scenario"], advance=20)
    assert again["view"]["clock"]["tick"] == 60  # nothing more is simulated
    refused(engine, scenario={**result["scenario"], "ticks": 61})  # a scenario past the cap


def test_one_request_cannot_ask_for_more_than_two_simulated_hours(engine):
    base = act(engine, seed=1)
    refused(engine, scenario=base["scenario"], advance=game.MAX_ADVANCE_TICKS + 1)
    ok = act(engine, scenario=base["scenario"], advance=game.MAX_ADVANCE_TICKS)
    assert ok["view"]["clock"]["elapsed_min"] == (game.WARMUP_TICKS + game.MAX_ADVANCE_TICKS) / 2


def test_a_request_takes_at_most_eight_commands(engine):
    base = act(engine, seed=1)
    refused(engine, scenario=base["scenario"], commands=[{"op": "hidden"}] * 9)
    refused(engine, scenario=base["scenario"], commands=[{"op": "hidden"}], advance=True)


def test_a_session_has_a_command_limit(engine, monkeypatch):
    monkeypatch.setattr(game, "MAX_COMMANDS", 3)
    result = act(engine, seed=1)
    for _ in range(3):
        result = act(engine, scenario=result["scenario"], commands=[START("humid_night", A)])
    refused(engine, scenario=result["scenario"], commands=[START("heat_spike", A)])


# --- Rebuilding in slices (a replay link, a reload) ----------------------------------------------------------

def sliced(engine, scenario):
    """What the worker does: begin, then step until done, reporting progress."""
    plan = engine.begin({"scenario": scenario})
    ticks = []
    while plan["rebuild"]:
        step = engine.step()
        ticks.append(step["tick"])
        assert step["total"] == scenario["ticks"]
        if step["done"]:
            break
    return plan, ticks


def test_a_sliced_rebuild_equals_session_build_and_reports_progress(make_engine):
    played = play(make_engine(), [("cmd", START("jump", B, "ph")), ("ff", 240), ("ff", 130), ("cmd", STOP("jump", B, "ph")),
                                  ("cmd", {"op": "hidden"}), ("ff", 240), ("ff", 97)])
    scenario = played["scenario"]
    engine = make_engine()
    plan, ticks = sliced(engine, scenario)
    assert plan == {"rebuild": True, "total": scenario["ticks"]}
    assert ticks == sorted(ticks) and ticks[-1] == scenario["ticks"] and len(ticks) >= scenario["ticks"] // engine_api.REBUILD_SLICE_TICKS
    after = act(engine, scenario=scenario)  # the finished rebuild is the live session: no second rebuild
    direct = game.Session.build(scenario)
    try:
        assert json.dumps(after["view"], sort_keys=True) == json.dumps(direct.view(), sort_keys=True)
        assert json.dumps(after["view"], sort_keys=True) == json.dumps(played["view"], sort_keys=True)
    finally:
        direct.close()
    # nothing to rebuild when the live session already is the scenario
    assert engine.begin({"scenario": scenario}) == {"rebuild": False, "total": scenario["ticks"]}
    assert engine.begin({"seed": 1}) == {"rebuild": False, "total": 0}


def test_a_new_request_drops_a_half_finished_rebuild(make_engine):
    played = play(make_engine(), [("ff", 240), ("ff", 240)])
    engine = make_engine()
    assert engine.begin({"scenario": played["scenario"]})["rebuild"]
    assert engine.step()["done"] is False
    result = act(engine, seed=2)  # the visitor started a new session meanwhile
    assert result["view"]["clock"]["tick"] == game.WARMUP_TICKS
    with pytest.raises(ValueError):
        engine.step()


def test_a_scenario_that_fails_midway_is_refused_and_leaves_no_half_built_session(engine):
    with pytest.raises(ValueError):
        engine.begin({"scenario": {"seed": 1, "ticks": 5, "commands": [{"t": 9, "op": "hidden"}]}})  # bad before it starts
    bad = {"v": 1, "seed": 1, "ticks": 300, "commands": [{"t": 100, "op": "start", "name": "nope", "zone": A}]}
    assert engine.begin({"scenario": bad})["rebuild"]
    with pytest.raises(ValueError):
        while not engine.step()["done"]:
            pass  # the bad command only fails when the replay reaches it
    assert engine._pending is None and engine.session is None
    with pytest.raises(ValueError):
        engine.step()
