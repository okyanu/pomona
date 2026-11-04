"""Sessions: rebuild from the scenario, replay links, every trick, the hidden trick."""

import json

import pytest
import engine_api
from helpers import A, B, CAL, START, STOP, act, play, refused

import game

SCRIPT = [
    ("cmd", START("stuck", A, "air_temperature_c")), ("ff", 30), ("cmd", STOP("stuck", A, "air_temperature_c")),
    ("ff", 30), ("cmd", START("heat_spike", A)), ("ff", 60), ("cmd", START("jump", B, "ph")), ("ff", 30),
    ("cmd", STOP("jump", B, "ph")), ("cmd", CAL(B, "ph")), ("cmd", {"op": "hidden"}), ("ff", 60),
    ("cmd", START("plausible_offset", A, "ec_ms_cm")), ("ff", 40),
]


def dumps(value):
    return json.dumps(value, sort_keys=True)


def test_rebuild_from_scenario_equals_the_cached_session(make_engine):
    first = make_engine()
    live = play(first, SCRIPT)
    # same engine: the session is the live one; another engine has none and replays the scenario
    assert first.session is not None
    cached = act(first, scenario=live["scenario"])
    rebuilt = act(make_engine(), scenario=live["scenario"])
    assert dumps(cached["view"]) == dumps(live["view"]) == dumps(rebuilt["view"])
    assert cached["scenario"] == rebuilt["scenario"] == live["scenario"]


def test_a_rebuilt_session_keeps_playing_like_the_live_one(make_engine):
    live_client, other = make_engine(), make_engine()
    live = play(live_client, SCRIPT)
    rebuilt = act(other, scenario=live["scenario"])  # replay, then both go on with the same steps
    next_live = act(live_client, scenario=live["scenario"], commands=[START("humid_night", B)], advance=90)
    next_rebuilt = act(other, scenario=rebuilt["scenario"], commands=[START("humid_night", B)], advance=90)
    assert dumps(next_live["view"]) == dumps(next_rebuilt["view"])


def test_replay_link_scenario_reproduces_identical_verdicts(make_engine):
    played = play(make_engine(), SCRIPT + [("cmd", STOP("heat_spike", A)), ("ff", 60)])
    # the link carries the seed and the steps; the page rebuilds the same scenario from them, a stranger's browser replays it
    shared = json.loads(json.dumps(played["scenario"]))
    replayed = act(make_engine(), scenario=shared)
    assert replayed["view"]["episodes"] == played["view"]["episodes"]
    assert replayed["view"]["totals"] == played["view"]["totals"]
    assert any(e["verdict"] for e in played["view"]["episodes"])  # there was something to grade


def test_same_seed_same_world_different_seed_different_world(engine):
    one, again, other = (act(engine, seed=seed)["view"] for seed in (5, 5, 6))
    assert one["zones"] == again["zones"]
    assert one["zones"] != other["zones"]


# every trick: (name, zone, field)
TRICK_CASES = [
    ("stuck", A, "ph"), ("drift", A, "ec_ms_cm"), ("jump", B, "ph"), ("spike", A, "ph"), ("noisy", B, "humidity_pct"),
    ("dropout", B, None), ("dead_clock", A, None), ("plausible_offset", A, "ec_ms_cm"),
    ("heat_spike", A, None), ("cold_night", B, None), ("humid_night", B, None), ("nutrient_over_concentration", B, None), ("dry_zone", A, None),
]


def test_the_cases_cover_every_trick():
    assert {c[0] for c in TRICK_CASES} == set(game.TRICKS)


@pytest.mark.parametrize("name,zone,field", TRICK_CASES)
def test_each_trick_starts_runs_shows_in_the_timeline_and_stops(engine, name, zone, field):
    # ticks to run, ticks to wind down: the overdose ramps for an hour (and back down for an hour), the dry zone needs 35 min to dry
    run, wind_down = {"nutrient_over_concentration": (160, 150), "dry_zone": (90, 90)}.get(name, (60, 90))
    result = play(engine, [("cmd", START(name, zone, field)), ("ff", run)])
    view = result["view"]
    bands = view["timeline"]["tricks"][zone]
    assert [b["name"] for b in bands] == [name], "the trick leaves exactly one band in its zone's timeline"
    assert view["timeline"]["tricks"][B if zone == A else A] == []
    zone_view = next(z for z in view["zones"] if z["id"] == zone)
    if name != "spike":  # a spike removes itself after one sample
        assert [t["name"] for t in zone_view["tricks"]] == [name]
    assert [e["title"] for e in view["episodes"]] == [game.TRICKS[name]["title"]]
    if name != "spike":
        assert all(e["status"] == "running" for e in view["episodes"])
    # stop it and let it wind down: the episode is finished and has a verdict
    result = play(engine, [("cmd", START(name, zone, field)), ("ff", run), ("cmd", STOP(name, zone, field)), ("ff", wind_down)])
    episodes = [e for e in result["view"]["episodes"] if e["kind"] != "alarm"]
    assert episodes and all(e["status"] == "done" for e in episodes), episodes
    assert all(e["verdict"] in game.VERDICTS for e in episodes)
    zone_view = next(z for z in result["view"]["zones"] if z["id"] == zone)
    assert zone_view["tricks"] == []


def test_a_trick_changes_what_pomona_receives_or_thinks(engine):
    quiet = play(engine, [("ff", 80)])["view"]["zones"][0]
    jumped = play(engine, [("cmd", START("jump", A, "ph")), ("ff", 80)])["view"]["zones"][0]
    ph = lambda zone: next(f for f in zone["fields"] if f["key"] == "ph")  # noqa: E731
    assert ph(jumped)["value"] - ph(quiet)["value"] > 1.0
    assert jumped["trust"] != "trusted" and ph(jumped)["vetoed"], "Pomona refuses the shifted pH"
    assert any(card["sensor"] for card in jumped["cards"])


def test_a_dead_clock_is_refused_by_core_and_a_dropout_is_not_scored(engine):
    dead = play(engine, [("cmd", START("dead_clock", B)), ("ff", 20), ("cmd", STOP("dead_clock", B)), ("ff", 30)])
    assert [e["verdict"] for e in dead["view"]["episodes"]] == ["rejected_by_core"]
    assert dead["view"]["totals"]["caught"] == 1
    silent = play(engine, [("cmd", START("dropout", B)), ("ff", 20), ("cmd", STOP("dropout", B)), ("ff", 30)])
    assert [e["verdict"] for e in silent["view"]["episodes"]] == ["not_published"]
    assert silent["view"]["totals"]["not_scored"] == 1


def test_a_plausible_offset_is_unfair_and_a_short_trick_is_too_short(engine):
    unfair = play(engine, [("cmd", START("plausible_offset", A, "ec_ms_cm")), ("ff", 60),
                           ("cmd", STOP("plausible_offset", A, "ec_ms_cm")), ("ff", 40)])
    assert [e["verdict"] for e in unfair["view"]["episodes"]] == ["undetectable"]
    assert unfair["view"]["totals"]["unfair"] == 1
    short = play(engine, [("cmd", START("spike", A, "ph")), ("ff", 40)])
    assert [e["verdict"] for e in short["view"]["episodes"]] == ["too_short_to_raise"]
    assert "at least 10 min" in short["view"]["episodes"][0]["headline"]


def test_a_slow_drift_noticed_only_when_it_ends_is_a_fooled_verdict(engine):
    drift = play(engine, [("cmd", START("drift", A, "air_temperature_c")), ("ff", 80),
                          ("cmd", STOP("drift", A, "air_temperature_c")), ("ff", 40)])
    (episode,) = drift["view"]["episodes"]
    assert episode["verdict"] == "caught_at_recovery" and episode["class"] == "fooled"
    assert episode["headline"] == "You fooled Pomona: it only noticed when your trick ended"
    assert (drift["view"]["totals"]["fooled"], drift["view"]["totals"]["caught"]) == (1, 0)
    running = play(engine, [("cmd", START("drift", A, "air_temperature_c")), ("ff", 80),
                            ("cmd", STOP("drift", A, "air_temperature_c")), ("ff", 8)])
    assert running["view"]["episodes"][0]["class"] == "running"


def test_a_calibration_is_recorded_and_replays(make_engine):
    steps = [("cmd", START("jump", B, "ph")), ("ff", 60), ("cmd", STOP("jump", B, "ph")), ("ff", 10), ("cmd", CAL(B, "ph")), ("ff", 20)]
    first = play(make_engine(), steps)
    assert first["scenario"]["commands"][-1]["op"] == "calibrate"
    again = act(make_engine(), scenario=first["scenario"])
    assert dumps(again["view"]) == dumps(first["view"])


def test_bad_commands_are_refused_and_leave_the_session_alone(engine):
    base = act(engine, seed=3)
    bad = [START("dry_zone", B), START("stuck", A), START("nope", A), START("stuck", "greenhouse-z", "ph"),
           START("stuck", B, "soil_moisture_pct"), START("heat_spike", A, "ph"), CAL(B, "soil_moisture_pct"),
           {"op": "explode"}, {"op": "reveal"}, "not an object"]
    for command in bad:
        refused(engine, scenario=base["scenario"], commands=[command], advance=1)
    # the page still holds its last good scenario, so nothing is lost
    assert act(engine, scenario=base["scenario"])["view"]["clock"]["tick"] == game.WARMUP_TICKS


@pytest.mark.parametrize("scenario", [
    {"seed": 1, "ticks": 0, "commands": [{"t": 5, "op": "start", "name": "stuck", "zone": A, "field": "ph"}]},  # after the end
    {"seed": 1, "ticks": 10, "commands": [{"t": 5, "op": "hidden"}, {"t": 2, "op": "hidden"}]},  # out of order
    {"seed": -1, "ticks": 0, "commands": []}, {"seed": 1, "ticks": 10**9, "commands": []},
    {"seed": 1, "ticks": 0, "commands": [{"t": 0, "op": "start", "name": "Stuck!", "zone": A}]},
    {"seed": 1, "ticks": 0, "commands": [{"t": 0, "op": "start", "extra": 1}]}, {"seed": 1, "ticks": 0},
    {"seed": 1, "ticks": 0, "commands": [], "other": 1}, [], "text", {"seed": True, "ticks": 0, "commands": []},
])
def test_a_malformed_scenario_is_refused(engine, scenario):
    refused(engine, scenario=scenario)


def test_malformed_bodies_are_refused():
    for raw in ("{not json", "[1, 2]", '{"advance": 99999}', '{"advance": true}', '{"commands": "x"}',
                '{"seed": 1.5}', '{"seed": true}', '{"seed": -1}', '{"unknown": 1}',
                '{"commands": [{}, {}, {}, {}, {}, {}, {}, {}, {}]}'):
        answer = json.loads(engine_api.handle("act", raw))
        assert answer["error"] and "result" not in answer, raw


def test_the_text_entry_point_is_what_the_worker_calls():
    answer = json.loads(engine_api.handle("act", json.dumps({"seed": 3, "advance": 5})))
    assert answer["result"]["view"]["clock"]["tick"] == game.WARMUP_TICKS + 5
    assert json.loads(engine_api.handle("act", json.dumps({"scenario": answer["result"]["scenario"]})))["result"]
    assert json.loads(engine_api.handle("info"))["result"]["caps"]["max_hours"] == 24
    assert "error" in json.loads(engine_api.handle("nope", "{}"))
    assert "error" in json.loads(engine_api.handle("step", "{}"))  # no rebuild in progress
    engine_api._ENGINE.close()


# --- The hidden trick ---------------------------------------------------------------------------------------

def hidden_session(engine, seed=21):
    return play(engine, [("cmd", {"op": "hidden"}), ("ff", 120)], seed=seed)


def test_the_hidden_trick_is_chosen_from_the_seed_and_stays_hidden_until_revealed(make_engine):
    one, two = hidden_session(make_engine()), hidden_session(make_engine())
    assert dumps(one["view"]) == dumps(two["view"])
    scenario = json.dumps(one["scenario"])
    assert '"op": "hidden"' in scenario and "name" not in scenario  # the page holds no answer
    # find out what it was by rebuilding the same session and looking at the answer key
    session = game.Session.build(one["scenario"])
    try:
        entry = session.sim.hidden_log[0]
        text = json.dumps(one["view"]) + json.dumps(one["scenario"])
        for word in (entry["name"], game.TRICKS[entry["name"]]["title"]):
            assert word not in text, f"the view leaks the hidden trick ({word})"
        assert one["view"]["hidden"]["revealed"] is False and one["view"]["hidden"]["items"] == []
        assert [e["hidden"] for e in one["view"]["episodes"] if e["kind"] != "alarm"][:1] in ([True], [])
        assert not any(s.get("source") == "hidden" for s in one["view"]["export"]["steps"])
    finally:
        session.close()
    revealed = act(make_engine(), scenario=one["scenario"], commands=[{"op": "reveal"}], advance=90)
    item = revealed["view"]["hidden"]["items"][0]
    assert revealed["view"]["hidden"]["revealed"] and item["title"] == game.TRICKS[entry["name"]]["title"]
    assert item["zone"] == entry["zone"]
    assert any(s.get("source") == "hidden" for s in revealed["view"]["export"]["steps"])
    graded = [e for e in revealed["view"]["episodes"] if e["kind"] != "alarm"]
    assert graded and all(not e["hidden"] and e["status"] == "done" for e in graded)


def test_the_blind_test_has_rules(engine):
    start = act(engine, seed=2)
    refused(engine, scenario=start["scenario"], commands=[{"op": "reveal"}])  # nothing to reveal
    revealed = play(engine, [("cmd", {"op": "hidden"}), ("ff", 10), ("cmd", {"op": "reveal"})], seed=2)
    refused(engine, scenario=revealed["scenario"], commands=[{"op": "hidden"}])  # the blind test is over
    result = start
    for _ in range(game.MAX_HIDDEN):
        result = act(engine, scenario=result["scenario"], commands=[{"op": "hidden"}], advance=1)
    refused(engine, scenario=result["scenario"], commands=[{"op": "hidden"}])
