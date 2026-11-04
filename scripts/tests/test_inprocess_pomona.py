"""Tests for the step-wise engine (examples/simulators/inprocess_pomona.py). Run with the model-router venv."""

import json
import re
import socket
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "examples" / "simulators"))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import fake_greenhouse as fg
import inprocess_pomona as engine
import score_fake_greenhouse as score

A = "greenhouse-a"
BASE = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)


def fake_clock(step_s=30.0):
    state = {"now": BASE}

    def now():
        value = state["now"]
        state["now"] = value + timedelta(seconds=step_s)
        return value

    return now


def make_truth(tmp_path, scenario, name):
    """Truth log of a dry-run of the scenario (a file path or a dict) with a virtual 30 s clock."""
    if isinstance(scenario, dict):
        path = tmp_path / f"{name}-scenario.json"
        path.write_text(json.dumps(scenario))
    else:
        path = scenario
    truth = tmp_path / f"{name}-truth.jsonl"
    assert fg.main(["--dry-run", "--fast", "--out", str(tmp_path / f"{name}-events.jsonl"),
                    "--truth-log", str(truth), "--scenario", str(path)], clock=fake_clock()) == 0
    return score.load_truth(truth)


@pytest.fixture(scope="module")
def demo_rows(tmp_path_factory):
    return make_truth(tmp_path_factory.mktemp("demo"), ROOT / "examples" / "simulators" / "scenarios" / "demo.json", "demo")


def replay_stepwise(rows):
    """Drive the engine reading by reading, like a live session would: calibrations first, then the reading."""
    events, frames = [], {}
    with engine.InProcessPomona(score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()),
                                score.alert_defaults()) as pomona:
        for row in sorted(rows, key=lambda r: (r["tick"], r["zone_id"])):
            for item in row.get("calibrations", []):
                pomona.calibrate(row["zone_id"], item["field"], item["at"])
            if not row["published"]:
                continue
            got = pomona.observe(row["sent"])
            if got["accepted"]:
                events += got["alert_events"]
                frames[(row["zone_id"], row["tick"])] = got
    return events, frames


def test_stepwise_observe_on_demo_gives_the_scorer_path_events(demo_rows):
    scored_events, scored_info, scored_states = score.replay_offline(
        demo_rows, score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()), score.alert_defaults())
    events, frames = replay_stepwise(demo_rows)
    assert events == scored_events and {e["event"] for e in events} == {"raised", "recovered"}
    assert set(frames) == set(scored_info)
    for key, info in scored_info.items():
        got = frames[key]
        assert {"labels": got["labels"], "trust": got["trust"], "vetoed_fields": got["vetoed_fields"],
                "card_labels": got["card_labels"], "sensor_check_labels": got["sensor_check_labels"]} == info


class PlainBaseline:
    """The reference the engine's per-stream StreamBaseline must equal: stream_baseline over the stored readings."""

    def __init__(self, window_s, min_n, max_age_s, scan_limit):
        self.args, self.scan_limit, self.seen = (window_s, min_n, max_age_s), scan_limit, []

    def add(self, packet):
        self.seen.append(packet)

    def baseline(self, calibrations, now):
        base = engine.load_module("pomona_trusted_baseline", engine.CORE_APP / "trusted_baseline.py")
        return base.stream_baseline(self.seen[-self.scan_limit:], calibrations, now, *self.args)


def test_incremental_baseline_gives_the_engine_the_same_results_as_the_plain_stream_baseline(demo_rows):
    """Every pipeline result (labels, trust, vetoes, the full verdict) is identical whichever computes the reference."""
    def run(plain):
        with engine.InProcessPomona(score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()),
                                    score.alert_defaults()) as pomona:
            if plain:
                pomona._baseline = type("Plain", (), {
                    "StreamBaseline": PlainBaseline, "DEFAULT_WINDOW_S": pomona._baseline.DEFAULT_WINDOW_S,
                    "DEFAULT_MIN_N": pomona._baseline.DEFAULT_MIN_N, "DEFAULT_MAX_AGE_S": pomona._baseline.DEFAULT_MAX_AGE_S,
                    "DEFAULT_SCAN_LIMIT": pomona._baseline.DEFAULT_SCAN_LIMIT})
            results = []
            for row in sorted(demo_rows, key=lambda r: (r["tick"], r["zone_id"])):
                for item in row.get("calibrations", []):
                    pomona.calibrate(row["zone_id"], item["field"], item["at"])
                if row["published"]:
                    got = pomona.observe(row["sent"], include_result=True)
                    got.get("pipeline", {}).pop("pipeline_id", None)  # a fresh random id per call
                    results.append(got)
            return json.dumps(results, sort_keys=True, default=str)

    fast, plain = run(plain=False), run(plain=True)
    same = fast == plain  # not `assert fast == plain`: pytest would diff two huge strings on a failure
    assert same and len(fast) > 100_000


def test_observe_reports_dead_clock_as_core_rejection_without_a_trace(demo_rows):
    sent = next(r["sent"] for r in demo_rows if r["published"] and r["sent"])
    with engine.InProcessPomona(score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()),
                                score.alert_defaults()) as pomona:
        dead = pomona.observe({**sent, "timestamp": "1970-01-01T00:00:00Z"})
        assert dead["accepted"] is False and dead["rejection"] == "dead_clock" and "labels" not in dead
        assert pomona.observe({**sent, "timestamp": "not a time"})["rejection"] == "invalid_timestamp"
        assert pomona.observe({k: v for k, v in sent.items() if k != "timestamp"})["rejection"] == "invalid_timestamp"
        assert pomona._history == {} and pomona._streams == {} and pomona.states() == []
        good = pomona.observe(sent)
        assert good["accepted"] is True and good["rejection"] is None and good["alert_events"] == []


def test_min_sample_time_is_cores_default():
    text = (ROOT / "services" / "core" / "app" / "config.py").read_text()
    year, month, day = map(int, re.search(r"min_sample_time: datetime = datetime\((\d+), (\d+), (\d+), tzinfo", text).groups())
    assert engine.MIN_SAMPLE_TIME == datetime(year, month, day, tzinfo=timezone.utc)


def test_rules_only_makes_no_network_calls(demo_rows, monkeypatch):
    """Sockets blocked: a whole demo replay still works, so the engine never touches the network."""
    def blocked(*args, **kwargs):
        raise AssertionError("the engine tried to use the network")

    # Engine built first (its imports may open nothing), then every way to a socket is closed.
    rules, defaults = score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()), score.alert_defaults()
    pomona = engine.InProcessPomona(rules, defaults)
    monkeypatch.setattr(socket, "socket", blocked)
    monkeypatch.setattr(socket, "create_connection", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    try:
        seen = 0
        for row in demo_rows[:400]:
            if row["published"] and row["sent"]:
                seen += pomona.observe(row["sent"])["accepted"]
        assert seen > 300
    finally:
        pomona.close()


def plain_zone_readings(tmp_path, ticks=120):
    rows = make_truth(tmp_path, {"seed": 7, "duration_ticks": ticks, "steps": []}, "plain")
    return [r["sent"] for r in sorted(rows, key=lambda r: r["tick"]) if r["zone_id"] == A and r["sent"]]


def test_calibrate_reanchors_the_trusted_reference(tmp_path):
    readings = plain_zone_readings(tmp_path)
    with engine.InProcessPomona() as pomona:
        got = []
        for i, sent in enumerate(readings):
            if i >= 20:
                sent = {**sent, "ph": 7.4}  # a level the probe never recovers from: a step stays flagged
            if i == 80:
                pomona.calibrate(A, "ph", sent["timestamp"])
            got.append(pomona.observe(sent))
    assert all("ph" not in g["vetoed_fields"] for g in got[:20]) and got[19]["trust"] == "trusted"
    assert all("ph" in g["vetoed_fields"] for g in got[20:80])  # flagged for as long as it lasts
    assert got[40]["trust"] == "partial" and "baseline_drift_possible" in got[40]["sensor_check_labels"]
    assert all("ph" not in g["vetoed_fields"] and g["trust"] == "trusted" for g in got[85:])  # the new level is accepted
    assert "high_ph" in got[100]["labels"]  # and judged as the real thing it now is


def stepped(readings):
    return [{**sent, "ph": 7.4} if i >= 20 else sent for i, sent in enumerate(readings)]


def test_a_calibration_applies_from_its_sample_time_on(tmp_path):
    readings = stepped(plain_zone_readings(tmp_path))
    with engine.InProcessPomona() as plain, engine.InProcessPomona() as later:
        later.calibrate(A, "ph", readings[60]["timestamp"])
        before = [(plain.observe(s), later.observe(s)) for s in readings[:60]]
    assert all({k: a[k] for k in ("labels", "trust", "vetoed_fields")} == {k: b[k] for k in ("labels", "trust", "vetoed_fields")}
               for a, b in before)  # recorded ahead of time, it does not touch earlier readings


def test_a_calibration_of_another_zone_device_or_probe_does_not_clear_the_flag(tmp_path):
    readings = stepped(plain_zone_readings(tmp_path))
    with engine.InProcessPomona() as pomona:
        pomona.calibrate("some-other-zone", "ph", readings[60]["timestamp"])
        pomona.calibrate(A, "ph", readings[60]["timestamp"], device_id="some-other-device")
        pomona.calibrate(A, "ec_ms_cm", readings[60]["timestamp"])
        got = [pomona.observe(s) for s in readings[:110]]
    assert all("ph" in g["vetoed_fields"] for g in got[20:110])


def test_two_engines_in_two_threads_match_one_after_the_other(demo_rows):
    """Concurrent engines share the pipeline's module-level clock: the lock keeps their results the same."""
    rules, defaults = score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()), score.alert_defaults()
    rows = [r for r in demo_rows if r["published"] and r["sent"]][:300]

    def run(out, flip):
        with engine.InProcessPomona(rules, defaults) as pomona:
            for r in rows:
                sent = {**r["sent"], "ph": 7.4} if flip and r["tick"] > 40 else r["sent"]
                got = pomona.observe(sent)
                out.append((got["labels"], got["trust"], got["vetoed_fields"]) if got["accepted"] else got["rejection"])

    alone_a, alone_b, together_a, together_b = [], [], [], []
    run(alone_a, False)
    run(alone_b, True)
    threads = [threading.Thread(target=run, args=(together_a, False)), threading.Thread(target=run, args=(together_b, True))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert together_a == alone_a and together_b == alone_b and alone_a != alone_b
    assert isinstance(engine.PIPELINE_LOCK, type(threading.Lock()))


def test_include_result_and_states(demo_rows):
    first, second = [r["sent"] for r in demo_rows if r["published"] and r["sent"] and r["zone_id"] == A][:2]
    with engine.InProcessPomona() as pomona:
        got = pomona.observe(first, include_result=True)
        assert "trust_gate" in got["pipeline"] and "pipeline" not in pomona.observe(second)
        assert pomona.states() == [] and got["sample_time"] == score.parse_ts(first["timestamp"])
