"""Tests for the fake greenhouse scorer. Run with the model-router venv (offline mode imports its pipeline)."""

import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "examples" / "simulators"))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import fake_greenhouse as fg
import score_fake_greenhouse as score

A, B = "greenhouse-a", "greenhouse-b"
BASE = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
RULES = score.parse_rules(score.AUTOMATION_APP.joinpath("rules.yaml").read_text())
DEFAULTS = (600, 900)


def row(tick, zone=A, expected=(), faults=(), events=(), recovering=(), forbid=(), kind=None, published=True,
        dead=False, delivery=None, detectable=True):
    """One truth-log line at 30 s ticks. `faults` are (name, field) pairs, `events` names."""
    wall = BASE + timedelta(seconds=30 * tick)
    sent = None
    if published:
        sent = {"farm_id": "demo-farm", "zone_id": zone, "device_id": f"dev-{zone}",
                "timestamp": "1970-01-01T00:00:00Z" if dead else wall.isoformat()}
    if kind is None:
        kind = ("not_published" if not published else "rejected_by_core" if dead else
                "both" if faults and events else "sensor_fault" if faults else "real_event" if events else "normal")
    out = {"tick": tick, "wall_timestamp": wall.isoformat(), "zone_id": zone, "device_id": f"dev-{zone}",
           "published": published, "sent": sent,
           "active_faults": [{"name": n, "field": f} for n, f in faults],
           "active_events": [{"name": n, "field": None} for n in events],
           "expect": {"kind": kind, "expected_labels": list(expected), "forbid_domain_cards_from": list(forbid),
                      "detectable": detectable, "onset_step": False, "recovering_from": list(recovering)}}
    if delivery is not None:
        out["delivery"] = {"status": delivery}
    return out


def raised(zone, rule, tick, spelling="z"):
    sample = BASE + timedelta(seconds=30 * tick)
    text = {"z": sample.isoformat().replace("+00:00", "Z"), "offset": sample.isoformat(),
            "plus2": sample.astimezone(timezone(timedelta(hours=2))).isoformat()}[spelling]
    return {"zone_id": zone, "farm_id": "demo-farm", "rule_id": rule, "event": "raised", "sample_time": text}


def grade(rows, events):
    return score.Grader(rows, events, RULES, DEFAULTS).report()


def real_rows(label="high_ec", start=10, end=60, zone=A, total=80):
    return [row(t, zone, expected=[label] if start <= t <= end else [], events=["ev"] if start <= t <= end else [])
            for t in range(total)]


def test_real_episode_caught_with_delay_in_seconds_and_samples():
    report = grade(real_rows(), [raised(A, "high_ec_alert", 32)])
    (ep,) = report["real_episodes"]
    assert ep["outcome"] == "caught" and ep["rule"] == "high_ec_alert" and ep["events"] == ["ev"]
    assert (ep["raised"]["delay_s"], ep["raised"]["delay_samples"]) == (660.0, 22)
    assert report["summary"]["real_episodes"] == {"total": 1, "caught": 1, "missed": 0, "too_short_to_raise": 0,
                                                  "no_card_rule": 0, "max_delay_s": 660.0}
    assert report["summary"]["false_alarms"] == 0


def test_long_enough_real_episode_without_a_raise_is_missed():
    report = grade(real_rows(), [])
    assert report["real_episodes"][0]["outcome"] == "missed"
    assert report["summary"]["real_episodes"]["missed"] == 1 and score.failures(report) == 1


def test_short_episode_is_too_short_to_raise_not_missed():
    report = grade(real_rows(start=10, end=19), [])  # 4.5 minutes, the rule waits 10
    assert report["real_episodes"][0]["outcome"] == "too_short_to_raise"
    assert report["summary"]["real_episodes"]["missed"] == 0 and score.failures(report) == 0


def test_rule_specific_window_is_used():
    # fungal_pressure raises only after 30 minutes: 25 minutes is too short, 35 is a miss.
    assert grade(real_rows("fungal_pressure", 10, 59), [])["real_episodes"][0]["outcome"] == "too_short_to_raise"
    assert grade(real_rows("fungal_pressure", 10, 80, total=100), [])["real_episodes"][0]["outcome"] == "missed"


def test_label_without_a_rule_is_not_a_miss():
    report = grade(real_rows("heat_stress"), [])
    assert report["real_episodes"][0]["outcome"] == "no_card_rule"
    assert report["summary"]["real_episodes"]["no_card_rule"] == 1 and score.failures(report) == 0


def test_raise_inside_the_clear_window_after_the_episode_still_counts():
    report = grade(real_rows(start=10, end=50), [raised(A, "high_ec_alert", 70)])  # 10 min after the end
    assert report["real_episodes"][0]["outcome"] == "caught" and report["summary"]["false_alarms"] == 0
    late = grade(real_rows(start=10, end=50, total=140), [raised(A, "high_ec_alert", 100)])  # past 15 min
    assert late["real_episodes"][0]["outcome"] == "missed" and late["summary"]["false_alarms"] == 1


def fault_rows(name="jump", field="ph", forbid=("ph",), start=5, end=45, tail=11, total=80, zone=A):
    rows = []
    for t in range(total):
        active = start <= t <= end
        lingering = end < t <= end + tail
        rows.append(row(t, zone, faults=[(name, field)] if active else [], forbid=forbid if active else [],
                        recovering=[name] if lingering else []))
    return rows


def test_sensor_check_raised_during_a_fault_is_caught():
    report = grade(fault_rows(), [raised(A, "sensor_check", 30)])
    (ep,) = report["fault_episodes"]
    assert ep["outcome"] == "caught" and ep["raised"]["delay_samples"] == 25
    assert (ep["start_tick"], ep["active_end_tick"], ep["end_tick"]) == (5, 45, 56)  # the tail is part of the window
    assert report["summary"]["sensor_fault_episodes"]["sensor_check_caught"] == 1
    assert report["summary"]["false_alarms"] == 0


def test_sensor_check_raised_in_the_recovery_tail_is_attributed_to_the_fault():
    report = grade(fault_rows(), [raised(A, "sensor_check", 52)])
    assert report["fault_episodes"][0]["outcome"] == "caught" and report["summary"]["false_alarms"] == 0
    # After the tail and the clear window the same raise is a false alarm.
    late = grade(fault_rows(total=200), [raised(A, "sensor_check", 140)])
    assert late["summary"]["false_alarms"] == 1 and late["fault_episodes"][0]["outcome"] == "missed"


def test_a_domain_card_on_the_faulty_field_is_a_trusted_wrong_card():
    events = [raised(A, "sensor_check", 30), raised(A, "ph_out_of_range", 31)]
    report = grade(fault_rows(), events)
    (ep,) = report["fault_episodes"]
    assert ep["outcome"] == "wrong_card" and ep["wrong_cards"][0]["rule"] == "ph_out_of_range"
    assert report["summary"]["sensor_fault_episodes"]["trusted_wrong_card"] == 1 and score.failures(report) == 1
    # A card for another field is not a wrong card (still not a false alarm: it is inside the fault window).
    other = grade(fault_rows(), [raised(A, "high_ec_alert", 31)])
    assert other["fault_episodes"][0]["outcome"] == "missed" and other["summary"]["false_alarms"] == 0


def test_the_same_card_during_a_real_event_is_not_wrong():
    rows = fault_rows()
    for r in rows:
        if 10 <= r["tick"] <= 44:
            r["expect"]["expected_labels"] = ["high_ph"]  # high_ph has a real episode for ph_out_of_range
    report = grade(rows, [raised(A, "ph_out_of_range", 31)])
    assert report["fault_episodes"][0]["wrong_cards"] == []


def test_short_fault_window_is_too_short_to_raise():
    report = grade(fault_rows("spike", "ph", end=5, tail=11), [])  # one sample plus the tail: 5.5 minutes
    assert report["fault_episodes"][0]["outcome"] == "too_short_to_raise"
    assert report["summary"]["sensor_fault_episodes"]["too_short_to_raise"] == 1 and score.failures(report) == 0


def test_false_alarm_in_normal_operation():
    rows = [row(t, zone) for t in range(60) for zone in (A, B)]
    report = grade(rows, [raised(A, "sensor_check", 25), raised(B, "high_ec_alert", 5)])
    assert {(a["zone"], a["rule"], a["tick"]) for a in report["false_alarms"]} == {
        (A, "sensor_check", 25), (B, "high_ec_alert", 5)}
    assert report["summary"]["false_alarms"] == 2


def test_events_for_frames_outside_the_truth_log_are_unmatched_not_false_alarms():
    rows = [row(t) for t in range(60)]
    report = grade(rows, [raised(A, "sensor_check", 25), raised(A, "sensor_check", 500)])
    assert report["summary"]["false_alarms"] == 1 and report["summary"]["unmatched_events"] == 1


def test_a_different_rule_inside_a_real_window_is_still_a_false_alarm():
    report = grade(real_rows(), [raised(A, "high_ec_alert", 30), raised(A, "ph_out_of_range", 30)])
    assert [a["rule"] for a in report["false_alarms"]] == ["ph_out_of_range"]


def test_dead_clock_is_rejected_by_core():
    def dead(delivery):
        return [row(t, dead=5 <= t < 8, delivery=delivery if 5 <= t < 8 else (201 if delivery else None),
                    faults=[("dead_clock", None)] if 5 <= t < 8 else []) for t in range(12)]
    for delivery, outcome in ((422, "rejected_by_core"), (None, "rejected_by_core"), (201, "accepted_by_core")):
        (ep,) = grade(dead(delivery), [])["fault_episodes"]
        assert ep["fault"] == "dead_clock" and ep["outcome"] == outcome and ep["frames"] == 3, delivery
    summary = grade(dead(422), [])["summary"]["dead_clock"]
    assert summary == {"total": 1, "rejected_by_core": 1, "accepted_by_core": 0}


def test_dropout_and_plausible_offset_are_reported_apart():
    rows = []
    for t in range(60):
        faults = [("dropout", None)] if 5 <= t < 10 else [("plausible_offset", "ec_ms_cm")] if 20 <= t < 59 else []
        rows.append(row(t, faults=faults, published=not 5 <= t < 10, forbid=["ec_ms_cm"] if t >= 20 else [],
                        detectable=not t >= 20))
    report = grade(rows, [raised(A, "sensor_check", 50), raised(A, "high_ec_alert", 51)])
    outcomes = {e["fault"]: e["outcome"] for e in report["fault_episodes"]}
    assert outcomes == {"dropout": "not_published", "plausible_offset": "undetectable"}
    s = report["summary"]
    assert s["undetectable"] == {"total": 1, "sensor_check_raised": 1, "wrong_card": 1}
    assert s["sensor_fault_episodes"]["total"] == 0 and s["dropout"]["total"] == 1 and score.failures(report) == 0


def test_events_join_by_parsed_timestamp_whatever_the_iso_spelling():
    events = [raised(A, "high_ec_alert", 32, "z"), raised(A, "sensor_check", 33, "plus2"),
              raised(A, "sensor_check", 34, "offset")]
    grader = score.Grader(real_rows(), events, RULES, DEFAULTS)
    assert [r["tick"] for r in grader.raises] == [32, 33, 34] and grader.unmatched == []
    assert score.parse_ts("2026-06-01T12:00:30Z") == score.parse_ts("2026-06-01T14:00:30+02:00") == \
        score.parse_ts("2026-06-01T12:00:30.000000+00:00")


def test_parse_rules_matches_the_yaml_file():
    yaml = pytest.importorskip("yaml")
    expected = yaml.safe_load(score.AUTOMATION_APP.joinpath("rules.yaml").read_text())["rules"]
    assert [{k: v for k, v in r.items() if k in ("id", "match_any_labels", "action", "raise_after_seconds",
                                                 "clear_after_seconds")} for r in RULES] == \
        [{k: v for k, v in r.items() if k in ("id", "match_any_labels", "action", "raise_after_seconds",
                                              "clear_after_seconds")} for r in expected]
    assert [" ".join(r["message"].split()) for r in RULES] == [" ".join(r["message"].split()) for r in expected]
    assert score.alert_defaults() == (600, 900)


def test_markdown_report_has_timeline_and_summary():
    rows = real_rows() + fault_rows(zone=B)
    report = grade(rows, [raised(A, "high_ec_alert", 32), raised(B, "sensor_check", 30)])
    text = score.markdown(report, "stack", Path("truth.jsonl"))
    assert "| Zone | Start | End | What really happened | Expected answer | Pomona raised | Verdict |" in text
    assert "high_ec_alert at 12:16:00 (+660 s, 22 samples) | caught" in text
    assert "sensor fault jump on ph" in text and "## Summary" in text


# --- Stack mode against a fake automation-engine / Core -------------------------------------

class FakeStack(BaseHTTPRequestHandler):
    alerts = {}
    stored = {}

    def log_message(self, *args):
        pass

    def do_GET(self):
        from urllib.parse import parse_qs, urlparse
        parsed = urlparse(self.path)
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        if parsed.path == "/v1/automation/alerts":
            events = self.alerts.get(query["zone_id"], [])[:int(query["limit"])]
            body = {"count": 0, "alerts": [], "events": events}
        else:
            body = {"count": 0, "events": [{"timestamp": t} for t in self.stored.get(query["zone_id"], [])]}
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_stack():
    server = HTTPServer(("127.0.0.1", 0), FakeStack)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}", FakeStack
    server.shutdown()
    server.server_close()


def write_truth(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def test_stack_mode_reads_alerts_and_checks_what_core_stored(tmp_path, fake_stack):
    url, stack = fake_stack
    rows = [r for zone in (A,) for r in real_rows(zone=zone)] + [
        row(100 + t, A, dead=t == 0, delivery=422 if t == 0 else 201, faults=[("dead_clock", None)] if t == 0 else [])
        for t in range(3)]
    truth = tmp_path / "truth.jsonl"
    write_truth(truth, rows)
    accepted = [r["sent"]["timestamp"] for r in rows if score.core_accepted(r)]
    stack.alerts = {A: [raised(A, "high_ec_alert", 32)]}
    stack.stored = {A: accepted}
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    args = ["--truth", str(truth), "--automation-url", url, "--core-url", url, "--json", str(out), "--report", str(md)]
    assert score.main(args + ["--fail-on-miss"]) == 0
    report = json.loads(out.read_text())
    assert report["mode"] == "stack" and report["summary"]["real_episodes"]["caught"] == 1
    assert report["core_check"] == {"stored": 82, "accepted_in_truth": 82, "accepted_missing_in_core": 0,
                                    "rejected_but_stored": 0}
    assert "metric_definitions" in report and "caught" in md.read_text()
    stack.stored = {A: accepted[:-5] + [rows[-3]["sent"]["timestamp"]]}  # lost five, stored the dead clock
    assert score.main(args) == 0
    check = json.loads(out.read_text())["core_check"]
    assert (check["accepted_missing_in_core"], check["rejected_but_stored"]) == (5, 1)
    stack.alerts = {}
    assert score.main(args) == 0  # exit code 0 always...
    assert score.main(args + ["--fail-on-miss"]) == 1  # ...unless asked


def test_cli_rejects_core_url_without_automation_url(tmp_path):
    truth = tmp_path / "truth.jsonl"
    write_truth(truth, [row(0)])
    with pytest.raises(SystemExit):
        score.main(["--truth", str(truth), "--offline", "--core-url", "http://x"])
    with pytest.raises(SystemExit):
        score.main(["--truth", str(truth)])


# --- Offline mode: the real pipeline and alert monitor ----------------------------------------

def fake_clock(step_s=30.0):
    state = {"now": BASE}

    def now():
        value = state["now"]
        state["now"] = value + timedelta(seconds=step_s)
        return value

    return now


def test_offline_replay_on_a_generated_run_is_stable(tmp_path):
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"seed": 7, "duration_ticks": 60, "steps": [
        {"at_tick": 20, "start": "spike", "zone": A, "field": "ph", "params": {"value": 13.0}},
        {"at_tick": 40, "start": "dead_clock", "zone": B}, {"at_tick": 42, "stop": "dead_clock", "zone": B}]}))
    truth, events, out = tmp_path / "truth.jsonl", tmp_path / "events.jsonl", tmp_path / "report.json"
    assert fg.main(["--dry-run", "--out", str(events), "--truth-log", str(truth), "--scenario", str(scenario)],
                   clock=fake_clock()) == 0
    assert score.main(["--truth", str(truth), "--offline", "--json", str(out), "--report", str(tmp_path / "r.md")]) == 0
    report = json.loads(out.read_text())
    assert report["mode"] == "offline" and report["frames"] == {"total": 120, "accepted_by_core": 118, "published": 120}
    assert report["reading_level"] == {
        "normal_frames": 117, "normal_with_card": 0, "normal_with_sensor_check_outside_tail": 0,
        "normal_with_sensor_check_inside_tail": 0, "normal_tail_frames": 11, "faulty_frames": 1,
        "wrong_cards": 0, "trusted_wrong_cards": 0, "cannot_confirm_frames": 0, "partial_frames": 1}
    s = report["summary"]
    assert s["dead_clock"] == {"total": 1, "rejected_by_core": 1, "accepted_by_core": 0}
    assert s["sensor_fault_episodes"]["total"] == 1 and s["false_alarms"] == 0 and s["real_episodes"]["total"] == 0
    assert report["fault_episodes"][0]["outcome"] == "too_short_to_raise"  # 12 samples, 10 minutes needed
    spike = next(e for e in report["fault_episodes"] if e["fault"] == "spike")
    assert spike["sensor_check_frames"] == 1  # the sensor check fired on the one bad reading, then nothing lasted
    assert "nothing raised (sensor check seen on 1 readings" in (tmp_path / "r.md").read_text()
    assert report["alerts_now"] == []  # the one-sample spike cancelled its own pending alert
