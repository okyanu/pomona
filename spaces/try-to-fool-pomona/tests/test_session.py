"""Sessions: rebuild from the scenario, replay links, every trick, the hidden trick."""

import json

import pytest
from helpers import A, B, CAL, START, STOP, act, play

import game

SCRIPT = [
    ("cmd", START("stuck", A, "air_temperature_c")), ("ff", 30), ("cmd", STOP("stuck", A, "air_temperature_c")),
    ("ff", 30), ("cmd", START("heat_spike", A)), ("ff", 60), ("cmd", START("jump", B, "ph")), ("ff", 30),
    ("cmd", STOP("jump", B, "ph")), ("cmd", CAL(B, "ph")), ("cmd", {"op": "hidden"}), ("ff", 60),
    ("cmd", START("plausible_offset", A, "ec_ms_cm")), ("ff", 40),
]


def dumps(value):
    return json.dumps(value, sort_keys=True)


def test_rebuild_from_scenario_equals_the_cached_session(make_client):
    first = make_client()
    live = play(first, SCRIPT)
    # same app: the session comes from the cache; another app has an empty cache and replays the scenario
    cached = act(first, scenario=live["scenario"])
    rebuilt = act(make_client(), scenario=live["scenario"])
    assert len(first.app.state.cache) == 1
    assert dumps(cached["view"]) == dumps(live["view"]) == dumps(rebuilt["view"])
    assert cached["scenario"] == rebuilt["scenario"] == live["scenario"]


def test_a_rebuilt_session_keeps_playing_like_the_live_one(make_client):
    live_client, other = make_client(), make_client()
    live = play(live_client, SCRIPT)
    rebuilt = act(other, scenario=live["scenario"])  # replay, then both go on with the same steps
    next_live = act(live_client, scenario=live["scenario"], commands=[START("humid_night", B)], advance=90)
    next_rebuilt = act(other, scenario=rebuilt["scenario"], commands=[START("humid_night", B)], advance=90)
    assert dumps(next_live["view"]) == dumps(next_rebuilt["view"])


def test_replay_link_scenario_reproduces_identical_verdicts(make_client):
    played = play(make_client(), SCRIPT + [("cmd", STOP("heat_spike", A)), ("ff", 60)])
    # the link carries the seed and the steps; the client rebuilds the same scenario from them, a stranger's server replays it
    shared = json.loads(json.dumps(played["scenario"]))
    replayed = act(make_client(), scenario=shared)
    assert replayed["view"]["episodes"] == played["view"]["episodes"]
    assert replayed["view"]["totals"] == played["view"]["totals"]
    assert any(e["verdict"] for e in played["view"]["episodes"])  # there was something to grade


def test_same_seed_same_world_different_seed_different_world(client):
    one, again, other = (act(client, seed=seed)["view"] for seed in (5, 5, 6))
    assert one["zones"] == again["zones"]
    assert one["zones"] != other["zones"]


# every trick: (name, zone, field)
TRICK_CASES = [
    ("stuck", A, "ph"), ("drift", A, "ec_ms_cm"), ("jump", B, "ph"), ("spike", A, "ph"), ("noisy", B, "humidity_pct"),
    ("dropout", B, None), ("dead_clock", A, None), ("plausible_offset", A, "ec_ms_cm"),
    ("heat_spike", A, None), ("humid_night", B, None), ("nutrient_over_concentration", B, None), ("dry_zone", A, None),
]


def test_the_cases_cover_every_trick():
    assert {c[0] for c in TRICK_CASES} == set(game.TRICKS)


@pytest.mark.parametrize("name,zone,field", TRICK_CASES)
def test_each_trick_starts_runs_shows_in_the_timeline_and_stops(client, name, zone, field):
    # ticks to run, ticks to wind down: the overdose ramps for an hour (and back down for an hour), the dry zone needs 35 min to dry
    run, wind_down = {"nutrient_over_concentration": (160, 150), "dry_zone": (90, 90)}.get(name, (60, 90))
    result = play(client, [("cmd", START(name, zone, field)), ("ff", run)])
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
    result = play(client, [("cmd", START(name, zone, field)), ("ff", run), ("cmd", STOP(name, zone, field)), ("ff", wind_down)])
    episodes = [e for e in result["view"]["episodes"] if e["kind"] != "alarm"]
    assert episodes and all(e["status"] == "done" for e in episodes), episodes
    assert all(e["verdict"] in game.VERDICTS for e in episodes)
    zone_view = next(z for z in result["view"]["zones"] if z["id"] == zone)
    assert zone_view["tricks"] == []


def test_a_trick_changes_what_pomona_receives_or_thinks(client):
    quiet = play(client, [("ff", 80)])["view"]["zones"][0]
    jumped = play(client, [("cmd", START("jump", A, "ph")), ("ff", 80)])["view"]["zones"][0]
    ph = lambda zone: next(f for f in zone["fields"] if f["key"] == "ph")  # noqa: E731
    assert ph(jumped)["value"] - ph(quiet)["value"] > 1.0
    assert jumped["trust"] != "trusted" and ph(jumped)["vetoed"], "Pomona refuses the shifted pH"
    assert any(card["sensor"] for card in jumped["cards"])


def test_a_dead_clock_is_refused_by_core_and_a_dropout_is_not_scored(client):
    dead = play(client, [("cmd", START("dead_clock", B)), ("ff", 20), ("cmd", STOP("dead_clock", B)), ("ff", 30)])
    assert [e["verdict"] for e in dead["view"]["episodes"]] == ["rejected_by_core"]
    assert dead["view"]["totals"]["caught"] == 1
    silent = play(client, [("cmd", START("dropout", B)), ("ff", 20), ("cmd", STOP("dropout", B)), ("ff", 30)])
    assert [e["verdict"] for e in silent["view"]["episodes"]] == ["not_published"]
    assert silent["view"]["totals"]["not_scored"] == 1


def test_a_plausible_offset_is_unfair_and_a_short_trick_is_too_short(client):
    unfair = play(client, [("cmd", START("plausible_offset", A, "ec_ms_cm")), ("ff", 60),
                           ("cmd", STOP("plausible_offset", A, "ec_ms_cm")), ("ff", 40)])
    assert [e["verdict"] for e in unfair["view"]["episodes"]] == ["undetectable"]
    assert unfair["view"]["totals"]["unfair"] == 1
    short = play(client, [("cmd", START("spike", A, "ph")), ("ff", 40)])
    assert [e["verdict"] for e in short["view"]["episodes"]] == ["too_short_to_raise"]
    assert "at least 10 min" in short["view"]["episodes"][0]["headline"]


def test_a_calibration_is_recorded_and_replays(make_client):
    steps = [("cmd", START("jump", B, "ph")), ("ff", 60), ("cmd", STOP("jump", B, "ph")), ("ff", 10), ("cmd", CAL(B, "ph")), ("ff", 20)]
    first = play(make_client(), steps)
    assert first["scenario"]["commands"][-1]["op"] == "calibrate"
    again = act(make_client(), scenario=first["scenario"])
    assert dumps(again["view"]) == dumps(first["view"])


def test_bad_commands_are_refused_and_leave_the_session_alone(client):
    base = act(client, seed=3)
    bad = [START("dry_zone", B), START("stuck", A), START("nope", A), START("stuck", "greenhouse-z", "ph"),
           START("stuck", B, "soil_moisture_pct"), START("heat_spike", A, "ph"), CAL(B, "soil_moisture_pct"),
           {"op": "explode"}, {"op": "reveal"}, "not an object"]
    for command in bad:
        response = client.post("/api/act", json={"scenario": base["scenario"], "commands": [command], "advance": 1})
        assert response.status_code == 400, command
        assert "error" in response.json()
    # the client still holds its last good scenario, so nothing is lost
    assert act(client, scenario=base["scenario"])["view"]["clock"]["tick"] == game.WARMUP_TICKS


@pytest.mark.parametrize("scenario", [
    {"seed": 1, "ticks": 0, "commands": [{"t": 5, "op": "start", "name": "stuck", "zone": A, "field": "ph"}]},  # after the end
    {"seed": 1, "ticks": 10, "commands": [{"t": 5, "op": "hidden"}, {"t": 2, "op": "hidden"}]},  # out of order
    {"seed": -1, "ticks": 0, "commands": []}, {"seed": 1, "ticks": 10**9, "commands": []},
    {"seed": 1, "ticks": 0, "commands": [{"t": 0, "op": "start", "name": "Stuck!", "zone": A}]},
    {"seed": 1, "ticks": 0, "commands": [{"t": 0, "op": "start", "extra": 1}]}, {"seed": 1, "ticks": 0},
    {"seed": 1, "ticks": 0, "commands": [], "other": 1}, [], "text", {"seed": True, "ticks": 0, "commands": []},
])
def test_a_malformed_scenario_is_a_400(client, scenario):
    response = client.post("/api/act", json={"scenario": scenario})
    assert response.status_code == 400 and "error" in response.json()


def test_malformed_bodies_are_a_400(client):
    for raw in (b"{not json", b"[1, 2]", b'{"advance": 99999}', b'{"advance": true}', b'{"commands": "x"}',
                b'{"seed": 1.5}', b'{"unknown": 1}', b'{"commands": [{}, {}, {}, {}, {}, {}, {}, {}, {}]}'):
        response = client.post("/api/act", content=raw, headers={"Content-Type": "application/json"})
        assert response.status_code == 400, raw


# --- The hidden trick ---------------------------------------------------------------------------------------

def hidden_session(client, seed=21):
    return play(client, [("cmd", {"op": "hidden"}), ("ff", 120)], seed=seed)


def test_the_hidden_trick_is_chosen_from_the_seed_and_stays_hidden_until_revealed(make_client):
    one, two = hidden_session(make_client()), hidden_session(make_client())
    assert dumps(one["view"]) == dumps(two["view"])
    scenario = json.dumps(one["scenario"])
    assert '"op": "hidden"' in scenario and "name" not in scenario  # the client holds no answer
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
    revealed = act(make_client(), scenario=one["scenario"], commands=[{"op": "reveal"}], advance=90)
    item = revealed["view"]["hidden"]["items"][0]
    assert revealed["view"]["hidden"]["revealed"] and item["title"] == game.TRICKS[entry["name"]]["title"]
    assert item["zone"] == entry["zone"]
    assert any(s.get("source") == "hidden" for s in revealed["view"]["export"]["steps"])
    graded = [e for e in revealed["view"]["episodes"] if e["kind"] != "alarm"]
    assert graded and all(not e["hidden"] and e["status"] == "done" for e in graded)


def test_the_blind_test_has_rules(client):
    start = act(client, seed=2)
    refused = client.post("/api/act", json={"scenario": start["scenario"], "commands": [{"op": "reveal"}]})
    assert refused.status_code == 400  # nothing to reveal
    revealed = play(client, [("cmd", {"op": "hidden"}), ("ff", 10), ("cmd", {"op": "reveal"})], seed=2)
    again = client.post("/api/act", json={"scenario": revealed["scenario"], "commands": [{"op": "hidden"}]})
    assert again.status_code == 400  # the blind test is over
    result = start
    for _ in range(game.MAX_HIDDEN):
        result = act(client, scenario=result["scenario"], commands=[{"op": "hidden"}], advance=1)
    too_many = client.post("/api/act", json={"scenario": result["scenario"], "commands": [{"op": "hidden"}]})
    assert too_many.status_code == 400
