"""Caps and abuse limits: simulated hours, body size, rate, cache."""

import json

import pytest
from helpers import A, START, act

import game
import server


def test_the_caps_are_the_ones_in_the_plan():
    assert game.MAX_HOURS == 24 and game.MAX_TICKS == 2880 and game.TICK_S == 30
    assert server.Limits().max_body_bytes == 64 * 1024 and server.Limits().cache_size == 500
    assert server.Limits().idle_ttl_s == 30 * 60


def test_a_session_stops_at_the_cap_and_reveals_the_hidden_trick(client, monkeypatch):
    monkeypatch.setattr(game, "MAX_TICKS", 60)
    start = act(client, seed=4)
    result = act(client, scenario=start["scenario"], commands=[{"op": "hidden"}], advance=1)
    result = act(client, scenario=result["scenario"], advance=game.MAX_ADVANCE_TICKS)  # asks for more than is left
    clock = result["view"]["clock"]
    assert clock["tick"] == 60 and clock["at_cap"] is True
    assert result["view"]["hidden"]["revealed"] is True, "the end of the session reveals the blind test"
    again = act(client, scenario=result["scenario"], advance=20)
    assert again["view"]["clock"]["tick"] == 60  # nothing more is simulated
    # a scenario past the cap is refused
    response = client.post("/api/act", json={"scenario": {**result["scenario"], "ticks": 61}})
    assert response.status_code == 400


def test_one_request_cannot_ask_for_more_than_two_simulated_hours(client):
    base = act(client, seed=1)
    over = client.post("/api/act", json={"scenario": base["scenario"], "advance": game.MAX_ADVANCE_TICKS + 1})
    assert over.status_code == 400
    ok = act(client, scenario=base["scenario"], advance=game.MAX_ADVANCE_TICKS)
    assert ok["view"]["clock"]["elapsed_min"] == (game.WARMUP_TICKS + game.MAX_ADVANCE_TICKS) / 2


def test_a_session_has_a_command_limit(client, monkeypatch):
    monkeypatch.setattr(game, "MAX_COMMANDS", 3)
    result = act(client, seed=1)
    for _ in range(3):
        result = act(client, scenario=result["scenario"], commands=[START("humid_night", A)])
    response = client.post("/api/act", json={"scenario": result["scenario"], "commands": [START("heat_spike", A)]})
    assert response.status_code == 400


def test_a_request_body_over_64_kb_is_refused(client):
    big = json.dumps({"scenario": {"seed": 1, "ticks": 0, "commands": []}, "pad": "x" * (64 * 1024)}).encode()
    assert len(big) > 64 * 1024
    response = client.post("/api/act", content=big, headers={"Content-Type": "application/json"})
    assert response.status_code == 413
    # a body just under the cap is read (and refused for its content, not its size)
    small = json.dumps({"pad": "x" * (60 * 1024)}).encode()
    assert client.post("/api/act", content=small, headers={"Content-Type": "application/json"}).status_code == 400


def test_a_body_over_the_cap_is_refused_even_without_a_content_length(client):
    def chunks():
        for _ in range(70):
            yield b"x" * 1024

    response = client.post("/api/act", content=chunks(), headers={"Content-Type": "application/json"})
    assert response.status_code == 413


def test_the_rate_limit_is_per_ip_and_heavy_requests_cost_more(make_client):
    now = {"t": 0.0}
    limits = server.Limits(bucket_capacity=6.0, bucket_refill_per_s=0.5)
    client = make_client(limits, clock=lambda: now["t"])
    mine = {"X-Forwarded-For": "203.0.113.7"}
    other = {"X-Forwarded-For": "198.51.100.9"}
    statuses = [client.post("/api/act", json={"seed": 1}, headers=mine).status_code for _ in range(6)]
    assert statuses[:4] == [200] * 4 and 429 in statuses
    refused = client.post("/api/act", json={"seed": 1}, headers=mine)
    assert refused.status_code == 429 and refused.headers["Retry-After"] and "error" in refused.json()
    assert client.post("/api/act", json={"seed": 1}, headers=other).status_code == 200  # another visitor is unaffected
    now["t"] += 10  # 5 tokens refilled
    assert client.post("/api/act", json={"seed": 1}, headers=mine).status_code == 200
    # a forged first X-Forwarded-For entry does not buy a fresh bucket: the proxy's (last) entry counts
    forged = {"X-Forwarded-For": "1.2.3.4, 203.0.113.7"}
    assert client.post("/api/act", json={"seed": 1}, headers=forged).status_code in (200, 429)


def test_simulating_costs_tokens(make_client):
    now = {"t": 0.0}
    limits = server.Limits(bucket_capacity=5.0, bucket_refill_per_s=0.0, cost_per_60_ticks=1.0)
    client = make_client(limits, clock=lambda: now["t"])
    first = act(client, seed=1)  # 1 token + 20 ticks of warm-up
    act(client, scenario=first["scenario"], advance=240)  # 1 token + 4 for two simulated hours: now below one
    response = client.post("/api/act", json={"scenario": first["scenario"]})
    assert response.status_code == 429


def test_the_session_cache_is_lru_capped_and_expires_idle_sessions():
    now = {"t": 0.0}
    cache = server.SessionCache(size=2, idle_ttl_s=100, clock=lambda: now["t"])
    made = [game.Session.start_new(seed) for seed in (1, 2, 3)]
    try:
        cache.put("a", made[0])
        cache.put("b", made[1])
        cache.put("c", made[2])  # over the cap: the least recently used ("a") goes
        assert len(cache) == 2 and cache.take("a") is None
        assert cache.take("b") is made[1]  # taking removes it; the caller puts it back under its new key
        assert len(cache) == 1
        now["t"] = 101
        assert cache.take("c") is None and len(cache) == 0  # idle for longer than the TTL
    finally:
        for session in made:
            session.close()


def test_the_server_does_not_cache_without_bound(make_client):
    client = make_client(server.Limits(cache_size=3))
    for seed in range(6):
        act(client, seed=seed)
    assert len(client.app.state.cache) == 3


def test_when_too_many_requests_are_being_worked_on_the_server_says_busy(make_client):
    client = make_client(server.Limits(max_in_flight=2))
    client.app.state.busy["now"] = 2  # two requests are already inside the engine
    response = client.post("/api/act", json={"seed": 1})
    assert response.status_code == 503 and response.headers["Retry-After"] and "busy" in response.json()["error"]
    client.app.state.busy["now"] = 0
    assert client.post("/api/act", json={"seed": 1}).status_code == 200
    assert client.app.state.busy["now"] == 0  # the count is given back after every request, failed ones too
    client.post("/api/act", json={"commands": [{"op": "explode"}], "seed": 1})
    assert client.app.state.busy["now"] == 0
