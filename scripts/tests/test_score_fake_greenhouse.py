"""Tests for the fake greenhouse scorer. Run with the model-router venv (offline mode imports its pipeline)."""

import copy
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
                                                  "no_card_rule": 0, "max_delay_s": 660.0, "caught_cant_confirm": 0}
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
    report = grade(real_rows("nutrient_uptake_issue"), [])
    assert report["real_episodes"][0]["outcome"] == "no_card_rule"
    assert report["summary"]["real_episodes"]["no_card_rule"] == 1 and score.failures(report) == 0


def test_heat_stress_has_a_rule_so_no_raise_is_a_miss_and_a_raise_is_caught():
    assert grade(real_rows("heat_stress"), [])["real_episodes"][0]["outcome"] == "missed"
    report = grade(real_rows("heat_stress"), [raised(A, "heat_stress_check", 30)])
    assert report["real_episodes"][0]["outcome"] == "caught" and report["summary"]["false_alarms"] == 0


def test_cold_stress_has_a_rule_so_no_raise_is_a_miss_and_a_raise_is_caught():
    assert grade(real_rows("cold_stress"), [])["real_episodes"][0]["outcome"] == "missed"
    report = grade(real_rows("cold_stress"), [raised(A, "cold_stress_check", 30)])
    assert report["real_episodes"][0]["outcome"] == "caught" and report["summary"]["false_alarms"] == 0


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


def test_sensor_check_raised_in_the_recovery_tail_is_attributed_to_the_fault_but_is_not_a_catch():
    report = grade(fault_rows(), [raised(A, "sensor_check", 52)])  # fault active to tick 45; label began on the snap back
    (ep,) = report["fault_episodes"]
    assert ep["outcome"] == "caught_at_recovery" and ep["raised"] is None and ep["raised_at_recovery"]["tick"] == 52
    assert report["summary"]["false_alarms"] == 0  # still the fault's card, not a false alarm
    sensor = report["summary"]["sensor_fault_episodes"]
    assert (sensor["sensor_check_caught"], sensor["missed"], sensor["missed_noticed_only_at_recovery"]) == (0, 1, 1)
    assert "only after the fault ended | MISSED (noticed only when it ended)" in score.markdown(report, "stack", Path("t"))
    # After the tail and the clear window the same raise is a false alarm.
    late = grade(fault_rows(total=200), [raised(A, "sensor_check", 140)])
    assert late["summary"]["false_alarms"] == 1 and late["fault_episodes"][0]["outcome"] == "missed"


def test_a_card_raised_just_after_the_end_counts_only_if_its_label_began_during_the_fault():
    # sensor_check raises on 3 flagged readings in a row. Readings 45, 46, 47: the run began on the last wrong reading.
    slow = grade(fault_rows(), [raised(A, "sensor_check", 47)])["fault_episodes"][0]
    assert slow["outcome"] == "caught" and slow["raised"]["tick"] == 47 and slow["raised_at_recovery"] is None
    # Readings 46, 47, 48: the run began on the first honest reading, so the snap back is what raised it.
    snap = grade(fault_rows(), [raised(A, "sensor_check", 48)])["fault_episodes"][0]
    assert snap["outcome"] == "caught_at_recovery"
    # A raise in the fault is caught whatever follows, and a fault with no card at all is still just missed.
    assert grade(fault_rows(), [raised(A, "sensor_check", 30), raised(A, "sensor_check", 52)])["fault_episodes"][0]["outcome"] == "caught"
    assert grade(fault_rows(), [])["fault_episodes"][0]["outcome"] == "missed"


def test_a_plausible_offset_noticed_only_at_its_end_is_not_a_card_raised():
    report = grade(fault_rows("plausible_offset", "ec_ms_cm", forbid=("ec_ms_cm",)), [raised(A, "sensor_check", 52)])
    (ep,) = report["fault_episodes"]
    assert ep["outcome"] == "undetectable" and ep["raised"] is None and ep["raised_at_recovery"]["tick"] == 52
    assert report["summary"]["undetectable"]["sensor_check_raised"] == 0 and report["summary"]["false_alarms"] == 0
    during = grade(fault_rows("plausible_offset", "ec_ms_cm", forbid=("ec_ms_cm",)), [raised(A, "sensor_check", 20)])
    assert during["summary"]["undetectable"]["sensor_check_raised"] == 1


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


# --- Can't-confirm: the safe catch -----------------------------------------------------------

def frame_info(zone, ticks, vetoed):
    return {(zone, t): {"labels": [], "trust": "partial", "vetoed_fields": list(vetoed), "card_labels": [],
                        "sensor_check_labels": ["baseline_drift_possible"]} for t in ticks}


def test_real_episode_with_only_a_sensor_check_is_caught_as_cant_confirm():
    rows = real_rows(zone=A)  # high_ec from tick 10 to 60
    report = grade(rows, [raised(A, "sensor_check", 14)])
    (ep,) = report["real_episodes"]
    assert ep["outcome"] == "caught_cant_confirm" and ep["raised"]["rule"] == "sensor_check"
    assert ep["field_vetoed"] is None  # stack mode cannot see per-reading vetoes
    assert report["summary"]["real_episodes"]["caught_cant_confirm"] == 1 and report["summary"]["real_episodes"]["missed"] == 0
    assert score.failures(report) == 0 and report["summary"]["false_alarms"] == 0  # a safe catch, not a false alarm
    text = score.markdown(report, "stack", Path("truth.jsonl"))
    assert "caught as can't-confirm (safe)" in text


def test_offline_the_episodes_field_must_have_been_vetoed():
    rows = real_rows(zone=A)
    events = [raised(A, "sensor_check", 14)]
    ec = score.Grader(rows, events, RULES, DEFAULTS, frame_info(A, range(10, 61), ["ec_ms_cm"])).report()
    assert ec["real_episodes"][0]["outcome"] == "caught_cant_confirm" and ec["real_episodes"][0]["field_vetoed"] is True
    other = score.Grader(rows, events, RULES, DEFAULTS, frame_info(A, range(10, 61), ["ph"])).report()
    assert other["real_episodes"][0]["outcome"] == "missed"  # the check was about a different probe


def test_a_sensor_check_card_that_began_before_the_crossing_counts_and_is_not_a_false_alarm():
    rows = []
    for t in range(80):  # the event ramps from tick 2 (no label yet), the label holds from tick 20
        rows.append(row(t, A, expected=["high_ec"] if 20 <= t <= 70 else [], events=["ev"] if 2 <= t <= 75 else []))
    report = grade(rows, [raised(A, "sensor_check", 6)])
    ep = report["real_episodes"][0]
    assert ep["outcome"] == "caught_cant_confirm" and ep["raised"]["already_active"] is True
    assert report["summary"]["false_alarms"] == 0
    assert "sensor_check already active since 12:03:00" in score.markdown(report, "stack", Path("t"))
    # Without a real event under way the same raise is a false alarm.
    assert grade([row(t, A) for t in range(80)], [raised(A, "sensor_check", 6)])["summary"]["false_alarms"] == 1


def test_domain_card_after_a_calibration_is_caught_with_a_note_on_when_cant_confirm_began():
    rows = real_rows(start=20, end=70, total=90)
    report = grade(rows, [raised(A, "sensor_check", 12), raised(A, "high_ec_alert", 48)])
    (ep,) = report["real_episodes"]
    assert ep["outcome"] == "caught" and ep["raised"]["rule"] == "high_ec_alert" and ep["raised"]["delay_s"] == 840.0
    assert ep["cant_confirm_from"]["rule"] == "sensor_check" and ep["cant_confirm_from"]["already_active"] is True
    text = score.markdown(report, "stack", Path("t"))
    assert "can't-confirm (sensor_check) since 12:06:00 (before the crossing)" in text and "| caught |" in text


def test_a_card_active_from_an_earlier_fault_counts_only_if_this_fault_was_flagged():
    rows = [row(t, A, faults=[("stuck", "air_temperature_c")] if 40 <= t <= 60 else [],
                forbid=["air_temperature_c"] if 40 <= t <= 60 else [],
                recovering=["stuck"] if 61 <= t <= 71 else []) for t in range(90)]
    events = [raised(A, "sensor_check", 5)]  # raised long before, never recovered in the log
    stack = grade(rows, events)
    assert stack["fault_episodes"][0]["outcome"] == "caught" and stack["fault_episodes"][0]["raised"]["already_active"]
    flagged = score.Grader(rows, events, RULES, DEFAULTS, frame_info(A, range(44, 52), ["air_temperature_c"])).report()
    assert flagged["fault_episodes"][0]["outcome"] == "caught"
    silent = score.Grader(rows, events, RULES, DEFAULTS, {(A, 3): frame_info(A, [3], [])[(A, 3)]}).report()
    assert silent["fault_episodes"][0]["outcome"] == "missed"  # nothing flagged in this fault's window
    tail_only = score.Grader(rows, events, RULES, DEFAULTS, frame_info(A, range(64, 70), ["air_temperature_c"])).report()
    assert tail_only["fault_episodes"][0]["outcome"] == "missed"  # flagged only on the snap back: the old card is not vouched for


def test_aftermath_of_a_real_event_is_counted_apart_offline():
    rows = [row(t, A, events=["ev"] if 5 <= t <= 15 else []) for t in range(60)]
    info = {(A, t): {"labels": ["baseline_drift_possible"], "trust": "partial", "vetoed_fields": ["ec_ms_cm"],
                     "card_labels": [], "sensor_check_labels": ["baseline_drift_possible"]} for t in (30, 31, 50)}
    level = score.Grader(rows, [], RULES, DEFAULTS, info).reading_level()
    # ticks 30 and 31 are within an hour of the event's end; all three are (60 frames = 30 minutes).
    assert level["normal_with_sensor_check_event_aftermath"] == 3 and level["normal_with_sensor_check_outside_tail"] == 0


def test_labels_of_one_rule_are_different_cards():
    # low_ph and high_ph are both on the ph_out_of_range rule, but they are different cards.
    def level(expected, got, kind):
        rows = [row(0, A, kind="normal", expected=[expected])] if kind == "normal" else \
            [row(0, A, faults=[("stuck", "ph")], expected=[expected])]
        info = {(A, 0): {"labels": [got], "trust": "trusted", "vetoed_fields": [], "card_labels": [got], "sensor_check_labels": []}}
        return score.Grader(rows, [], RULES, DEFAULTS, info).reading_level()
    assert level("low_ph", "high_ph", "fault")["wrong_cards"] == 1
    assert level("low_ph", "low_ph", "fault")["wrong_cards"] == 0
    assert level("low_ph", "high_ph", "normal")["normal_with_card"] == 1
    assert level("low_ph", "low_ph", "normal")["normal_with_card"] == 0


def test_extreme_reading_check_is_not_a_sensor_check_rule():
    assert score.Grader([], [], RULES, DEFAULTS).sensor_rules == {"sensor_check", "sensor_flatline"}
    # In a sensor fault it is not a caught sensor check; in a real episode it is not a can't-confirm catch.
    report = grade(fault_rows(), [raised(A, "extreme_reading_check", 30)])
    sensor = report["summary"]["sensor_fault_episodes"]
    assert sensor["sensor_check_caught"] == 0 and report["fault_episodes"][0]["outcome"] != "caught"
    report = grade(real_rows(zone=A), [raised(A, "extreme_reading_check", 14)])
    assert report["real_episodes"][0]["outcome"] == "missed"
    assert report["summary"]["real_episodes"]["caught_cant_confirm"] == 0
    # and its label does not turn a normal frame into a frame with a card or a sensor check.
    rows = [row(0, A, kind="normal")]
    info = {(A, 0): {"labels": ["sensor_anomaly"], "trust": "trusted", "vetoed_fields": [], "card_labels": [],
                     "sensor_check_labels": []}}
    level = score.Grader(rows, [], RULES, DEFAULTS, info).reading_level()
    assert level["normal_with_card"] == 0 and level["normal_with_sensor_check_outside_tail"] == 0


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
            body = {"count": 0, "events": [{"timestamp": t} if isinstance(t, str) else t  # a dict carries a device_id
                                           for t in self.stored.get(query["zone_id"], [])]}
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
        "normal_with_sensor_check_inside_tail": 0, "normal_with_sensor_check_event_aftermath": 0,
        "normal_tail_frames": 11, "faulty_frames": 1,
        "wrong_cards": 0, "trusted_wrong_cards": 0, "cannot_confirm_frames": 0, "partial_frames": 1}
    s = report["summary"]
    assert s["dead_clock"] == {"total": 1, "rejected_by_core": 1, "accepted_by_core": 0}
    assert s["sensor_fault_episodes"]["total"] == 1 and s["false_alarms"] == 0 and s["real_episodes"]["total"] == 0
    assert report["fault_episodes"][0]["outcome"] == "too_short_to_raise"  # 12 samples, 10 minutes needed
    spike = next(e for e in report["fault_episodes"] if e["fault"] == "spike")
    assert spike["sensor_check_frames"] == 1  # the sensor check fired on the one bad reading, then nothing lasted
    assert "nothing raised (sensor check seen on 1 readings" in (tmp_path / "r.md").read_text()
    assert report["alerts_now"] == []  # the one-sample spike cancelled its own pending alert


def test_offline_cant_confirm_then_calibration_flow(tmp_path):
    """A fast EC rise: Pomona says can't-confirm; once a calibration accepts the level the high_ec card follows."""
    def run(steps, name):
        scenario = tmp_path / f"{name}.json"
        scenario.write_text(json.dumps({"seed": 7, "duration_ticks": 100, "steps": steps}))
        truth, out = tmp_path / f"{name}-truth.jsonl", tmp_path / f"{name}.json.out"
        assert fg.main(["--dry-run", "--out", str(tmp_path / f"{name}-e.jsonl"), "--truth-log", str(truth),
                        "--scenario", str(scenario)], clock=fake_clock()) == 0
        assert score.main(["--truth", str(truth), "--offline", "--json", str(out)]) == 0
        return json.loads(out.read_text())

    ramp = {"at_tick": 20, "start": "nutrient_over_concentration", "zone": B, "params": {"ramp_min": 10}}
    alone = run([ramp], "alone")["real_episodes"][0]
    assert alone["outcome"] == "caught_cant_confirm" and alone["field_vetoed"] is True and alone["raised"]["already_active"]
    confirmed = run([ramp, {"at_tick": 48, "calibrate": "ec_ms_cm", "zone": B}], "confirmed")
    ep = confirmed["real_episodes"][0]
    assert ep["outcome"] == "caught" and ep["raised"]["rule"] == "high_ec_alert"
    assert ep["cant_confirm_from"]["rule"] == "sensor_check" and ep["raised"]["time"] > ep["cant_confirm_from"]["time"]
    assert confirmed["summary"]["false_alarms"] == 0 and confirmed["summary"]["real_episodes"]["missed"] == 0


def test_offline_pomona_flags_a_ph_jump_for_as_long_as_it_lasts(tmp_path):
    scenario = tmp_path / "scenario.json"
    scenario.write_text(json.dumps({"seed": 7, "duration_ticks": 90, "steps": [
        {"at_tick": 20, "start": "jump", "zone": B, "field": "ph", "params": {"offset": 1.5}},
        {"at_tick": 70, "stop": "jump", "zone": B}]}))
    truth, out = tmp_path / "truth.jsonl", tmp_path / "out.json"
    fg.main(["--dry-run", "--out", str(tmp_path / "e.jsonl"), "--truth-log", str(truth), "--scenario", str(scenario)],
            clock=fake_clock())
    assert score.main(["--truth", str(truth), "--offline", "--json", str(out)]) == 0
    report = json.loads(out.read_text())
    (ep,) = report["fault_episodes"]
    assert ep["outcome"] == "caught" and ep["raised"]["delay_samples"] <= 3 and ep["wrong_cards"] == []
    # 50 samples (25 minutes) of the fault: every reading after the first was flagged (the 11-packet check alone
    # stopped after about eight), so the sensor check card stayed up and no high_ph card was shown.
    assert ep["sensor_check_frames"] >= 49
    assert report["reading_level"]["trusted_wrong_cards"] <= 1 and report["summary"]["false_alarms"] == 0


def test_offline_a_slow_air_drift_is_noticed_only_when_it_ends(tmp_path):
    report = run_offline(tmp_path, "air-drift", [
        {"at_tick": 20, "start": "drift", "zone": A, "field": "air_temperature_c", "params": {"rate_per_min": 0.1}},
        {"at_tick": 100, "stop": "drift", "zone": A}], 160)
    (ep,) = report["fault_episodes"]
    # 40 minutes at 0.1 C/min: the reading is 4 C off, yet nothing is flagged until it snaps back to the true value.
    assert ep["outcome"] == "caught_at_recovery" and ep["raised"] is None and ep["wrong_cards"] == []
    assert ep["raised_at_recovery"]["tick"] > ep["active_end_tick"] and ep["raised_at_recovery"]["rule"] == "sensor_check"
    sensor = report["summary"]["sensor_fault_episodes"]
    assert (sensor["sensor_check_caught"], sensor["missed"], sensor["missed_noticed_only_at_recovery"]) == (0, 1, 1)
    assert report["summary"]["false_alarms"] == 0


def run_offline(tmp_path, name, steps, ticks):
    scenario = tmp_path / f"{name}.json"
    scenario.write_text(json.dumps({"seed": 7, "duration_ticks": ticks, "steps": steps}))
    truth, out = tmp_path / f"{name}-truth.jsonl", tmp_path / f"{name}-out.json"
    assert fg.main(["--dry-run", "--out", str(tmp_path / f"{name}-e.jsonl"), "--truth-log", str(truth),
                    "--scenario", str(scenario)], clock=fake_clock()) == 0
    assert score.main(["--truth", str(truth), "--offline", "--json", str(out)]) == 0
    return json.loads(out.read_text())


def test_offline_a_six_hour_ph_fault_stays_flagged_with_one_open_incident(tmp_path):
    report = run_offline(tmp_path, "six-hours", [{"at_tick": 20, "start": "jump", "zone": B, "field": "ph",
                                                  "params": {"offset": 1.5}}], 6 * 120)
    (ep,) = report["fault_episodes"]
    assert ep["outcome"] == "caught" and ep["wrong_cards"] == [] and ep["raised"]["delay_samples"] <= 3
    assert ep["sensor_check_frames"] >= 6 * 120 - 20 - 2  # flagged on every reading of the fault, hour after hour
    sensor_events = [e for e in report["alert_events"] if e["zone_id"] == B]
    assert [(e["rule_id"], e["event"]) for e in sensor_events] == [("sensor_check", "raised")]  # never recovered
    assert [(a["rule_id"], a["state"]) for a in report["alerts_now"] if a["zone_id"] == B] == [("sensor_check", "active")]
    assert report["reading_level"]["trusted_wrong_cards"] == 0 and report["summary"]["false_alarms"] == 0


def test_offline_a_calibration_clears_the_flag_and_the_domain_card_raises(tmp_path):
    report = run_offline(tmp_path, "calibrated", [
        {"at_tick": 20, "start": "jump", "zone": B, "field": "ph", "params": {"offset": 1.5}},
        {"at_tick": 60, "calibrate": "ph", "zone": B}], 140)
    events = [(e["rule_id"], e["event"], e["sample_time"]) for e in report["alert_events"] if e["zone_id"] == B]
    assert [(rule, kind) for rule, kind, _ in events] == [
        ("sensor_check", "raised"), ("ph_out_of_range", "raised"), ("sensor_check", "recovered")]
    check_raised, card_raised, check_recovered = (score.parse_ts(when) for _, _, when in events)
    calibrated = score.parse_ts(next(r["calibrations"][0]["at"] for r in score.load_truth(tmp_path / "calibrated-truth.jsonl")
                                    if r.get("calibrations")))
    assert check_raised < calibrated < card_raised < check_recovered  # the card follows the confirmation, not before
    assert (card_raised - calibrated).total_seconds() <= 12 * 60 and [a for a in report["alerts_now"] if a["zone_id"] == B
                                                                      and a["rule_id"] == "sensor_check"] == []


def test_sensor_flatline_is_a_sensor_card_not_a_domain_card():
    assert "sensor_flatline" in score.Grader([], [], RULES, DEFAULTS).sensor_rules
    assert "flatline_possible" not in score.Grader([], [], RULES, DEFAULTS).label_rule
    quiet = [row(t) for t in range(60)]
    assert grade(quiet, [raised(A, "sensor_flatline", 25)])["summary"]["false_alarms"] == 1  # chance flatline: a false alarm
    faulty = fault_rows("stuck", "air_temperature_c", forbid=("air_temperature_c",), start=5, end=45, tail=11, total=80)
    report = grade(faulty, [raised(A, "sensor_flatline", 30)])
    assert report["fault_episodes"][0]["outcome"] == "caught" and report["summary"]["false_alarms"] == 0
    assert report["fault_episodes"][0]["wrong_cards"] == []  # not a wrong domain card
    # During a real event it is the safe can't-confirm, like sensor_check.
    ep = grade(real_rows(zone=A), [raised(A, "sensor_flatline", 14)])["real_episodes"][0]
    assert ep["outcome"] == "caught_cant_confirm"


# --- Blind spots: a real event runs and the probe that would show it goes silent ---------------

BLIND_SPOT_SCENARIO = ROOT / "examples" / "simulators" / "scenarios" / "blind_spot.json"


def test_offline_blind_spot_scenario_has_no_false_reassurance(tmp_path):
    truth, out, md = tmp_path / "truth.jsonl", tmp_path / "out.json", tmp_path / "report.md"
    assert fg.main(["--dry-run", "--out", str(tmp_path / "e.jsonl"), "--truth-log", str(truth),
                    "--scenario", str(BLIND_SPOT_SCENARIO)], clock=fake_clock()) == 0
    assert score.main(["--truth", str(truth), "--offline", "--json", str(out), "--report", str(md), "--fail-on-miss"]) == 0
    report = json.loads(out.read_text())
    b = report["summary"]["blind_spot"]
    assert (b["total"], b["false_reassurance"], b["cant_confirm"], b["alerted"]) == (7, 0, 6, 1)
    assert b["too_short_to_judge"] == b["no_fault_in_window"] == b["no_real_event"] == 0
    cases = {(c["zone"], c["field"]): c for c in report["blind_spot_cases"]}
    # Core stores every partial packet; the six probes the event depends on end in the sensor_check card (a card is
    # also open for the humidity case from the earlier EC episode, so its first sign is not later than 3 minutes
    # after the silence began), never the passive device flag alone.
    for key in (("greenhouse-a", "soil_moisture_pct"), ("greenhouse-a", "air_temperature_c"), ("greenhouse-a", "ec_ms_cm"),
                ("greenhouse-b", "ec_ms_cm"), ("greenhouse-b", "humidity_pct"), ("greenhouse-b", "air_temperature_c")):
        case = cases[key]
        assert case["outcome"] == "cant_confirm" and not case["silent_flag_only"] and "sensor card" in case["via"], key
        assert case["core_refused_frames"] == 0 and case["signal"]["delay_s"] <= 180, key
    assert report["summary"]["blind_spot"]["cant_confirm_by_silent_flag_only"] == 0
    # the control: an optional probe goes silent, the air probe still shows the heat
    control = cases[("greenhouse-a", "substrate_temperature_c")]
    assert control["outcome"] == "alerted" and control["domain_card"]["rule"] == "heat_stress_check"
    assert report["summary"]["real_episodes"]["missed"] == 0 and report["summary"]["false_alarms"] == 0
    assert "## Blind spots" in md.read_text()


def test_the_pipeline_alone_would_say_cant_confirm_for_a_probe_that_is_missing():
    """The router flags a missing probe within 3 readings (the scenario above reaches it: Core stores partial packets)."""
    sim = fg.Simulation(seed=7, clock=fake_clock())
    events = [r.event for _ in range(14) for r in sim.step() if r.truth["zone_id"] == B]
    with score.InProcessPomona(RULES, DEFAULTS) as engine:
        for event in events[:10]:
            assert engine.observe(event)["sensor_check_labels"] == []
        raised_events = []
        for event in events[10:]:
            got = engine.observe({k: v for k, v in event.items() if k != "ec_ms_cm"})
            assert "missing_ec" in got["labels"] and got["trust"] != "trusted"
            raised_events += got["alert_events"]
        assert [(e["rule_id"], e["event"]) for e in raised_events] == [("sensor_check", "raised")]


# --- Multi-device zones: every join keyed by device (docs/design/multi-device-zones-slice3.md 3.5) -----------------
# Hand-built rows in the truth log's multi-device row format (3.2): a row per device per tick, with `device_id`, the
# device's `sensors` and `expect.device_labels`. Zone A has the devices below; zone B stays a single stream.

C1, C2, S1, S2 = "climate-1", "climate-2", "substrate-1", "substrate-2"
CLIMATE_PROBES = ["air_temperature_c", "humidity_pct"]
LAYOUT = {C1: CLIMATE_PROBES, C2: CLIMATE_PROBES,
          S1: ["ec_ms_cm", "ph", "soil_moisture_pct", "substrate_temperature_c"],
          S2: ["soil_moisture_pct"]}  # a second moisture probe (the pair case)


def drow(tick, device, zone=A, sensors=None, device_labels=None, **kw):
    """One device's truth row of a multi-device zone (`row()` arguments as ever)."""
    out = row(tick, zone, **kw)
    out["device_id"] = device
    if out["sent"]:
        out["sent"]["device_id"] = device
    out["sensors"] = list(LAYOUT[device] if sensors is None else sensors)
    out["expect"]["device_labels"] = list(kw.get("expected", ()) if device_labels is None else device_labels)
    return out


def trio(total=80, zone=A, devices=(C1, C2, S1), per=None, shared=None):
    """Rows for `total` ticks, one per device per tick. `shared` and each `per[device]` are `row()` arguments, or a
    function of the tick returning them."""
    per, shared = per or {}, shared or {}
    out = []
    for tick in range(total):
        for device in devices:
            kw = {}
            for source in (shared, per.get(device) or {}):
                kw.update(source(tick) if callable(source) else source)
            out.append(drow(tick, device, zone, **kw))
    return out


def during(start, end, **kw):
    return lambda tick: kw if start <= tick <= end else {}


def silent_run(field="ec_ms_cm", start=10, end=100):
    """`row()` arguments of a device whose `field` probe is silent (probe_dropout) from start to end."""
    return lambda tick: {"faults": [("probe_dropout", field)]} if start <= tick <= end else {}


def stuck(field="humidity_pct", name="stuck", start=5, end=45, tail=11):
    """`row()` arguments of one device's fault: active start..end, then its recovering_from tail."""
    def at(tick):
        if start <= tick <= end:
            return {"faults": [(name, field)], "forbid": [field]}
        return {"recovering": [name]} if end < tick <= end + tail else {}
    return at


def draised(rule, tick, device, zone=A, event="raised", detail=None):
    out = {**raised(zone, rule, tick), "device_id": device, "event": event}
    if detail:
        out["detail"] = detail
    return out


def dinfo(device, ticks, vetoed=(), labels=(), zone=A):
    """Offline per-reading results of a multi-device zone: keyed (zone, device, tick)."""
    return {(zone, device, t): {"labels": list(labels), "trust": "partial", "vetoed_fields": list(vetoed),
                                "card_labels": [], "sensor_check_labels": ["baseline_drift_possible"]} for t in ticks}


def mgrade(rows, events, info=None):
    return score.Grader(rows, events, RULES, DEFAULTS, info).report()


def test_two_devices_at_the_same_tick_do_not_collide():
    rows = trio(60)
    events = [draised("sensor_check", 25, S1), draised("sensor_check", 25, C1)]  # one sample time, two streams
    grader = score.Grader(rows, events, RULES, DEFAULTS)
    assert grader.unmatched == [] and len(grader.by_sample) == 60 * 3
    assert [r["device"] for r in grader.raises] == [C1, S1]  # sorted by (time, rule, device), not by event order
    assert grader.multi == {A: [C1, C2, S1]}
    report = grader.report()
    assert report["frames"]["total"] == 180 and report["summary"]["unmatched_events"] == 0
    assert [(a["device"], a["tick"]) for a in report["false_alarms"]] == [(C1, 25), (S1, 25)]
    assert mgrade(rows, events[::-1])["false_alarms"] == report["false_alarms"]


def test_each_raise_records_its_device_and_detail_and_a_recovery_closes_its_own_incident():
    events = [draised("sensor_check", 20, S1, detail="check the pH probe"), draised("sensor_check", 20, C1),
              draised("sensor_check", 40, C1, event="recovered")]
    c1, s1 = score.Grader(trio(60), events, RULES, DEFAULTS).raises
    assert (c1["device"], s1["device"], s1["detail"], "detail" in c1) == (C1, S1, "check the pH probe", False)
    assert c1["until"] is not None and s1["until"] is None  # the recovery on climate-1 closed only climate-1's card
    # A single-stream zone ignores the device: no device or detail key leaks into its report.
    single = grade(fault_rows(), [{**raised(A, "sensor_check", 30), "device_id": "other", "detail": "x"}])
    assert set(single["fault_episodes"][0]["raised"]) == {"rule", "time", "tick", "delay_s", "delay_samples", "already_active"}
    # In a multi-device zone the report carries the device and the detail.
    got = mgrade(trio(80, per={C1: stuck()}), [draised("sensor_check", 30, C1, detail="verify humidity on climate-2")])
    assert got["fault_episodes"][0]["raised"]["device"] == C1
    assert got["fault_episodes"][0]["raised"]["detail"] == "verify humidity on climate-2"


def test_an_event_without_device_id_joins_a_single_stream_zone_and_is_unmatched_in_a_multi_device_zone():
    rows = real_rows(zone=B) + trio(80)  # zone B: one stream; zone A: three
    grader = score.Grader(rows, [raised(B, "high_ec_alert", 32), raised(A, "high_ec_alert", 32),
                                 {**raised(B, "sensor_check", 33), "device_id": "not-the-log's-device"}], RULES, DEFAULTS)
    assert [(r["zone"], r["rule"]) for r in grader.raises] == [(B, "high_ec_alert"), (B, "sensor_check")]
    assert [e["zone_id"] for e in grader.unmatched] == [A]  # the device is ignored in B, required in A
    assert grader.report()["summary"]["unmatched_events"] == 1
    # The same event with a device id of the zone joins.
    assert score.Grader(rows, [draised("high_ec_alert", 32, S1)], RULES, DEFAULTS).unmatched == []


def test_a_row_without_a_device_id_is_no_device_so_a_zone_with_one_id_is_single_stream():
    rows = real_rows(zone=B)  # every row carries dev-greenhouse-b
    for r in rows[::2]:
        r["device_id"] = None  # rows the producer sent without a device id
    assert score.multi_device_zones(rows) == {}
    grader = score.Grader(rows, [raised(B, "high_ec_alert", 32)], RULES, DEFAULTS)  # the event has no device id either
    assert grader.multi == {} and grader.unmatched == []
    assert grader.report()["real_episodes"][0]["outcome"] == "caught"
    # Two real ids make a zone multi-device, and its None rows are not a third device.
    assert score.multi_device_zones(trio(3) + [{**row(0, A), "device_id": None}]) == {A: [C1, C2, S1]}


def test_frame_info_keys_are_zone_tick_for_a_single_stream_zone_and_zone_device_tick_for_a_multi_device_zone():
    single = score.Grader([row(0, B, kind="normal")], [], RULES, DEFAULTS, frame_info(B, [0], ["ph"])).reading_level()
    assert single["normal_frames"] == 1 and single["normal_with_sensor_check_outside_tail"] == 1
    multi_rows = trio(1)
    level = score.Grader(multi_rows, [], RULES, DEFAULTS, dinfo(C1, [0])).reading_level()
    assert level["normal_frames"] == 1 and level["normal_with_sensor_check_outside_tail"] == 1  # only climate-1 has a result
    with pytest.raises(ValueError, match="no device"):
        score.Grader(multi_rows, [], RULES, DEFAULTS, frame_info(A, [0], []))  # a (zone, tick) key in a multi-device zone
    # The same two-tuple key is fine next door, in a zone with one device id.
    score.Grader(multi_rows + [row(0, B)], [], RULES, DEFAULTS, frame_info(B, [0], []))
    # A single-stream zone also takes a (zone, device, tick) key: the device is ignored there, so it reads as (zone, tick).
    keyed = {(B, "any-device-id", 0): frame_info(B, [0], ["ph"])[(B, 0)]}
    assert score.Grader([row(0, B, kind="normal")], [], RULES, DEFAULTS, keyed).reading_level() == single


def test_a_card_on_any_device_catches_a_real_event_and_the_report_names_the_device():
    rows = trio(80, shared=during(10, 60, expected=["high_ec"], events=["ev"]))
    for device in (C1, S1):  # the climate device has no EC probe, yet its card is a card for the zone
        report = mgrade(rows, [draised("high_ec_alert", 32, device)])
        (ep,) = report["real_episodes"]
        assert ep["outcome"] == "caught" and ep["raised"]["device"] == device
        assert (ep["raised"]["delay_s"], ep["raised"]["delay_samples"]) == (660.0, 22)
        assert report["summary"]["false_alarms"] == 0
    both = mgrade(rows, [draised("high_ec_alert", 32, C1), draised("high_ec_alert", 40, S1)])
    assert both["summary"]["false_alarms"] == 0  # a real event exempts the raises of every device of its zone
    text = score.markdown(mgrade(rows, [draised("high_ec_alert", 32, C1)]), "stack", Path("t"))
    assert "high_ec_alert at 12:16:00 (+660 s, 22 samples) on climate-1 | caught" in text
    assert "| greenhouse-a | 12:05:00 |" in text  # a real event's Zone column stays the zone


def test_a_sensor_card_counts_on_the_faulted_device():
    rows = trio(80, per={C1: stuck()})
    report = mgrade(rows, [draised("sensor_check", 30, C1)])
    (ep,) = report["fault_episodes"]  # one episode: the stuck probe on climate-1 (the other rows carry no fault)
    assert ep["outcome"] == "caught" and ep["device"] == C1 and ep["partners"] == [C2]
    assert ep["raised"]["device"] == C1 and ep["raised_on_partner"] is None
    # A fault's "raised" text does not name the device (the Zone column already shows zone · device).
    assert score.raised_text(ep) == "sensor_check at 12:15:00 (+750 s, 25 samples)"
    sensor = report["summary"]["sensor_fault_episodes"]
    assert (sensor["total"], sensor["sensor_check_caught"], sensor["sensor_check_caught_on_partner"]) == (1, 1, 0)
    assert report["summary"]["false_alarms"] == 0
    # The same fault with no card at all is missed.
    assert mgrade(rows, [])["fault_episodes"][0]["outcome"] == "missed"


def test_a_partner_card_in_a_fault_too_short_to_raise_counts_only_when_it_is_about_the_field():
    rows = trio(80, per={C1: stuck(start=5, end=10)})  # active 5..10, then the tail: 16 readings, 480 s, raise_after 600 s
    partner = [draised("sensor_check", 12, C2)]
    assert mgrade(rows, [])["fault_episodes"][0]["outcome"] == "too_short_to_raise"
    # Stack mode has no per-reading results, so the partner's card counts (the partner outranks too_short_to_raise).
    stack = mgrade(rows, partner)["fault_episodes"][0]
    assert (stack["outcome"], stack["duration_s"]) == ("caught_on_partner", 480.0)
    # Offline the partner's card is about the fault's field only if its label run says so: a card for air temperature
    # is no catch, so the short fault stays too short to raise.
    short = mgrade(rows, partner, dinfo(C2, range(10, 13), vetoed=["air_temperature_c"]))["fault_episodes"][0]
    assert (short["outcome"], short["raised_on_partner"]) == ("too_short_to_raise", None)


def test_a_partner_card_that_does_not_count_leaves_a_long_fault_missed_offline():
    rows = trio(80, per={C1: stuck()})  # active 5..45, tail to 56: 51 readings, long enough to raise
    outcome = lambda events, info: mgrade(rows, events, info)["fault_episodes"][0]["outcome"]
    # The partner's label run began after the fault ended (its readings 50..52): the snap back, not the lie.
    assert outcome([draised("sensor_check", 52, C2)], dinfo(C2, range(50, 53), vetoed=["humidity_pct"])) == "missed"
    # A card about another field on the partner (air temperature, the run at 28..30) is no catch for humidity.
    assert outcome([draised("sensor_check", 30, C2)], dinfo(C2, range(28, 31), vetoed=["air_temperature_c"])) == "missed"


def test_a_multi_device_row_without_sensors_carries_nothing_so_it_is_no_partner_and_no_cant_confirm():
    def without_sensors(rows, device):
        return [{k: v for k, v in r.items() if k != "sensors"} if r["device_id"] == device else r for r in rows]
    # A fault on climate-1 (humidity): climate-2 has no probes listed, so it is not a partner and its card is no catch.
    rows = without_sensors(trio(80, per={C1: stuck()}), C2)
    (ep,) = mgrade(rows, [draised("sensor_check", 30, C2)])["fault_episodes"]
    assert (ep["outcome"], ep["partners"], ep["raised_on_partner"]) == ("missed", [], None)
    # A real event on high_ec: a card on climate-2 cannot confirm the probe (the EC probe is on substrate-1 only).
    event_rows = without_sensors(trio(80, shared=during(10, 60, expected=["high_ec"], events=["ev"])), C2)
    (episode,) = mgrade(event_rows, [draised("sensor_check", 30, C2)])["real_episodes"]
    assert episode["outcome"] == "missed"
    (episode,) = mgrade(event_rows, [draised("sensor_check", 30, S1)])["real_episodes"]
    assert episode["outcome"] == "caught_cant_confirm"


def test_fault_episodes_are_found_per_stream_and_name_their_partners():
    rows = trio(80, per={C1: stuck("humidity_pct"), C2: stuck("humidity_pct"),
                         S1: stuck("ph", "jump", start=20, end=30)})
    report = mgrade(rows, [draised("sensor_check", 30, C1), draised("sensor_check", 30, C2)])
    eps = {(e["device"], e["fault"]): e for e in report["fault_episodes"]}
    assert set(eps) == {(C1, "stuck"), (C2, "stuck"), (S1, "jump")}  # the same fault on two devices is two episodes
    assert eps[(C1, "stuck")]["partners"] == [C2] and eps[(C2, "stuck")]["partners"] == [C1]
    assert eps[(S1, "jump")]["partners"] == []  # nobody else carries pH
    assert eps[(C1, "stuck")]["outcome"] == eps[(C2, "stuck")]["outcome"] == "caught"
    assert eps[(S1, "jump")]["outcome"] == "missed"  # ten minutes of readings, no card on substrate-1
    # A whole-device fault has no field and no partners; a dropout of one device is not scored.
    drop = trio(60, per={C2: lambda t: {"faults": [("dropout", None)], "published": False} if 10 <= t < 20 else {}})
    (ep,) = mgrade(drop, [])["fault_episodes"]
    assert (ep["device"], ep["partners"], ep["outcome"]) == (C2, [], "not_published")


def test_caught_on_partner_is_its_own_outcome_and_a_pass():
    rows = trio(80, per={C1: stuck()})
    report = mgrade(rows, [draised("sensor_check", 30, C2)])  # stack mode: no per-reading results
    (ep,) = report["fault_episodes"]
    assert ep["outcome"] == "caught_on_partner" and ep["raised"] is None
    assert (ep["raised_on_partner"]["device"], ep["raised_on_partner"]["tick"]) == (C2, 30)
    sensor = report["summary"]["sensor_fault_episodes"]
    assert (sensor["total"], sensor["sensor_check_caught"], sensor["missed"], sensor["sensor_check_caught_on_partner"]) == (1, 0, 0, 1)
    assert report["summary"]["false_alarms"] == 0 and score.failures(report) == 0  # --fail-on-miss does not fail on it
    text = score.markdown(report, "stack", Path("t"))
    assert "| greenhouse-a · climate-1 |" in text and "sensor_check on the partner climate-2 at 12:15:00" in text
    assert "caught on the partner probe (the card asks to check both)" in text
    assert "caught on the partner probe 1." in text


def test_caught_on_partner_precedence_and_what_does_not_count():
    rows = trio(80, per={C1: stuck()})
    outcome = lambda events, rows=rows, info=None: mgrade(rows, events, info)["fault_episodes"][0]["outcome"]
    partner = draised("sensor_check", 30, C2)
    # first match wins: undetectable, wrong_card, caught, caught_on_partner, caught_at_recovery, too_short, missed
    offset = trio(80, per={C1: stuck(name="plausible_offset")})
    assert outcome([partner], offset) == "undetectable"
    assert outcome([partner, draised("high_humidity_fan", 31, C1)]) == "wrong_card"
    assert outcome([partner, draised("sensor_check", 30, C1)]) == "caught"
    # A wrong card is a domain card on the faulted device; the same card on the healthy partner is not this fault's.
    healthy = mgrade(rows, [draised("sensor_check", 30, C1), draised("high_humidity_fan", 31, C2)])
    assert healthy["fault_episodes"][0]["outcome"] == "caught" and healthy["fault_episodes"][0]["wrong_cards"] == []
    late = draised("sensor_check", 52, C1)  # on the faulted device, only after the fault ended
    assert outcome([late]) == "caught_at_recovery"
    assert outcome([late, partner]) == "caught_on_partner"
    # An already open card on a partner does not count (it was raised before the fault began).
    assert outcome([draised("sensor_check", 2, C2)]) == "missed"
    # A card on an unrelated device (no humidity probe) is not a partner's card.
    assert outcome([draised("sensor_check", 30, S1)]) == "missed"
    # A card on a partner whose label run began after the fault's last reading is the snap back, not the lie.
    assert outcome([draised("sensor_check", 52, C2)]) == "missed"


def test_the_label_run_is_counted_in_the_partners_own_stream():
    rows = trio(80, per={C1: stuck()})  # active to tick 45
    # A partner raise at tick 47 follows readings 45, 46, 47 of climate-2: the run began on the fault's last reading.
    # (Counting the zone's readings instead would put the run's start at tick 46, after the fault.)
    assert mgrade(rows, [draised("sensor_check", 47, C2)])["fault_episodes"][0]["outcome"] == "caught_on_partner"
    assert mgrade(rows, [draised("sensor_check", 48, C2)])["fault_episodes"][0]["outcome"] == "missed"


def test_offline_the_partners_card_must_be_about_the_faulted_field():
    rows = trio(80, per={C1: stuck()})
    events = [draised("sensor_check", 30, C2)]
    outcome = lambda info: mgrade(rows, events, info)["fault_episodes"][0]["outcome"]
    run = range(28, 31)  # the three readings the raise follows from
    assert outcome(dinfo(C2, run, vetoed=["humidity_pct"])) == "caught_on_partner"
    assert outcome(dinfo(C2, run, labels=["missing_humidity"])) == "caught_on_partner"  # a missing-data label counts
    assert outcome(dinfo(C2, run, vetoed=["air_temperature_c"])) == "missed"  # a chance card for another field
    assert outcome(dinfo(C2, range(0, 20), vetoed=["humidity_pct"])) == "missed"  # flagged before the run, not in it
    # The moisture probe goes by two names: a pipeline veto of the alias is the same field.
    moisture = trio(80, devices=(S1, S2), per={S1: stuck("soil_moisture_pct")})
    card = [draised("sensor_check", 30, S2)]
    info = dinfo(S2, run, vetoed=["substrate_moisture_pct"])
    assert mgrade(moisture, card, info)["fault_episodes"][0]["outcome"] == "caught_on_partner"


def test_false_alarms_are_partner_aware():
    rows = trio(80, per={C1: stuck()})
    alarms = lambda events: [(a["device"], a["rule"]) for a in mgrade(rows, events)["false_alarms"]]
    assert alarms([draised("sensor_check", 30, C2)]) == []  # a sensor card on a partner: the fault's own
    assert alarms([draised("sensor_check", 30, S1)]) == [(S1, "sensor_check")]  # an unrelated device: a false alarm
    assert alarms([draised("high_humidity_fan", 31, C2)]) == [(C2, "high_humidity_fan")]  # a domain card on a partner
    assert alarms([draised("high_ec_alert", 31, C1)]) == []  # any card on the faulted device itself
    # Past the fault and its clear window the faulted device's card is a false alarm too.
    late = trio(200, per={C1: stuck()})
    assert [(a["device"], a["tick"]) for a in mgrade(late, [draised("sensor_check", 140, C1)])["false_alarms"]] == [(C1, 140)]
    # In a single-stream zone a fault hides every raise of the zone, as ever.
    assert grade(fault_rows(), [raised(A, "high_ec_alert", 31)])["summary"]["false_alarms"] == 0


def test_a_silent_probe_exempts_the_raises_of_its_own_device_only():
    rows = trio(80, per={S1: silent_run(end=60)})  # no real event: a probe goes quiet on substrate-1
    alarms = lambda events: [(a["device"], a["rule"]) for a in mgrade(rows, events)["false_alarms"]]
    assert alarms([draised("sensor_check", 30, S1)]) == []
    assert alarms([draised("sensor_check", 30, C1)]) == [(C1, "sensor_check")]
    assert alarms([draised("high_humidity_fan", 30, C1)]) == [(C1, "high_humidity_fan")]


def test_a_cant_confirm_catch_needs_the_card_on_a_device_that_carries_the_labels_field():
    rows = trio(100, shared=during(10, 80, expected=["high_ec"], events=["ev"]))
    on_climate = mgrade(rows, [draised("sensor_check", 14, C1)])  # climate-1 has no EC probe
    assert on_climate["real_episodes"][0]["outcome"] == "missed"
    assert on_climate["summary"]["false_alarms"] == 0  # still a card during a real event: not a false alarm
    on_substrate = mgrade(rows, [draised("sensor_check", 14, S1)])
    assert on_substrate["real_episodes"][0]["outcome"] == "caught_cant_confirm"
    assert on_substrate["real_episodes"][0]["raised"]["device"] == S1
    # Offline the veto may be on any stream of the zone.
    events = [draised("sensor_check", 14, S1)]
    ec = mgrade(rows, events, {**dinfo(S1, range(10, 40), vetoed=["ec_ms_cm"])})
    assert ec["real_episodes"][0]["outcome"] == "caught_cant_confirm" and ec["real_episodes"][0]["field_vetoed"] is True
    ph = mgrade(rows, events, dinfo(S1, range(10, 40), vetoed=["ph"]))
    assert ph["real_episodes"][0]["outcome"] == "missed"


def test_blind_spots_are_per_device_and_the_events_card_on_any_device_counts():
    shared = during(10, 100, expected=["high_ec"], events=["ev"])
    rows = trio(120, shared=shared, per={S1: silent_run()})
    case = lambda events, rows=rows, info=None: next(c for c in mgrade(rows, events, info)["blind_spot_cases"])
    nothing = case([])
    assert (nothing["zone"], nothing["device"], nothing["field"], nothing["outcome"]) == (A, S1, "ec_ms_cm", "false_reassurance")
    assert mgrade(rows, [])["real_episodes"][0]["outcome"] == "blind_spot"
    assert score.failures(mgrade(rows, [])) == 1
    # A sensor card on the silent device is a sign; on another device it is not (its own stream decides).
    own = case([draised("sensor_check", 14, S1)])
    assert own["outcome"] == "cant_confirm" and own["via"] == ["sensor card"]
    assert case([draised("sensor_check", 14, C1)])["outcome"] == "false_reassurance"
    # The event's own card on any device counts as alerted: another probe still showed it.
    alerted = case([draised("high_ec_alert", 40, C1)])
    assert alerted["outcome"] == "alerted" and alerted["domain_card"]["tick"] == 40
    summary = mgrade(rows, [draised("sensor_check", 14, S1)])["summary"]["blind_spot"]
    assert (summary["total"], summary["cant_confirm"]) == (1, 1)
    # The passive device flag is the silent device's own: no accepted packet from it for longer than the timeout,
    # while the other devices keep reporting.
    gone = trio(120, shared=shared, per={S1: lambda t: {**silent_run()(t), **({"published": False} if 10 <= t <= 100 else {})}})
    flagged = case([], gone)
    assert flagged["outcome"] == "cant_confirm" and flagged["via"] == ["device silent"] and flagged["silent_flag_only"]


def test_silent_probe_blocked_counts_the_zones_reporting_devices():
    fungal = score.Grader([], [], RULES, DEFAULTS).label_rule["fungal_pressure"]
    assert score.Grader([], [], RULES, DEFAULTS).window(fungal)[0] == timedelta(minutes=30)
    shared = during(10, 100, expected=["fungal_pressure"], events=["ev"])
    silent = lambda t: {"faults": [("probe_dropout", "humidity_pct")]} if 10 <= t <= 100 else {}
    outcome = lambda rows: mgrade(rows, [])["real_episodes"][0]["outcome"]
    # climate-2 keeps reporting humidity: the episode is a plain miss, not a blind spot.
    assert outcome(trio(120, shared=shared, per={C1: silent})) == "missed"
    # Both humidity probes silent: a blind spot (substrate-1 reports, but carries neither humidity nor air).
    assert outcome(trio(120, shared=shared, per={C1: silent, C2: silent})) == "blind_spot"
    # climate-2 reports for ten minutes, then goes quiet (nothing reaches Core): shorter than the rule's 30 minutes.
    quiet = lambda t: {"published": False, "faults": [("dropout", None)]} if t > 30 else {}
    assert outcome(trio(120, shared=shared, per={C1: silent, C2: quiet})) == "blind_spot"


def test_the_reading_level_judges_each_device_by_its_own_labels():
    def level(rows, got):
        info = {(r["zone_id"], r["device_id"], r["tick"]): got for r in rows if r["zone_id"] == A and r["device_id"] in (C1, S1)}
        info.update({(r["zone_id"], r["tick"]): got for r in rows if r["zone_id"] == B})
        return score.Grader(rows, [], RULES, DEFAULTS, info).reading_level()
    card = {"labels": ["high_ec"], "trust": "trusted", "vetoed_fields": [], "card_labels": ["high_ec"], "sensor_check_labels": []}
    # The truth says high_ec, but only substrate-1's probes could show it: climate-1's card is not expected of it.
    rows = [drow(0, C1, kind="normal", expected=["high_ec"], device_labels=[]),
            drow(0, S1, kind="normal", expected=["high_ec"], device_labels=["high_ec"])]
    assert level(rows, card)["normal_with_card"] == 1  # climate-1's frame; substrate-1's card is right
    quiet = {**card, "card_labels": []}
    faulty = [drow(0, C1, faults=[("stuck", "humidity_pct")], expected=["high_ec"], device_labels=[]),
              drow(0, S1, faults=[("stuck", "ph")], expected=["high_ec"], device_labels=["high_ec"])]
    assert level(faulty, quiet)["wrong_cards"] == 1  # substrate-1 should have shown it, climate-1 should not
    assert level(faulty, card)["wrong_cards"] == 1  # climate-1 showed a card its probes cannot support
    assert level(faulty, quiet)["faulty_frames"] == 2
    # A single-stream zone keeps expected_labels, even if a row carries device_labels.
    single = row(0, B, kind="normal", expected=["high_ec"])
    single["expect"]["device_labels"] = []
    assert level([single], card)["normal_with_card"] == 0


def test_core_check_compares_per_stream_in_a_multi_device_zone_and_per_zone_otherwise():
    dead = [drow(10, device, dead=True, delivery=422, faults=[("dead_clock", None)]) for device in (C1, S1)]
    rows = trio(10, devices=(C1, S1)) + dead + [row(t, B) for t in range(10)]
    grader = score.Grader(rows, [], RULES, DEFAULTS)
    at = lambda t: BASE + timedelta(seconds=30 * t)
    stored = {A: [(C1, at(t)) for t in range(10)] + [(S1, at(t)) for t in range(7)]  # substrate-1 lost ticks 7-9
                 + [at(8)] + [(S1, score.parse_ts("1970-01-01T00:00:00Z"))],  # a stored event without a device matches none
              B: [("whatever", at(t)) for t in range(10)]}  # a single-stream zone ignores the device
    check = score.core_check(grader, stored)
    assert (check["stored"], check["accepted_in_truth"], check["accepted_missing_in_core"], check["rejected_but_stored"]) == (29, 30, 3, 1)
    assert check["by_stream"] == {A: {C1: {"accepted_in_truth": 10, "accepted_missing_in_core": 0, "rejected_but_stored": 0},
                                      S1: {"accepted_in_truth": 10, "accepted_missing_in_core": 3, "rejected_but_stored": 1}}}
    # Single-stream zones only: today's four numbers, no new key.
    single = score.core_check(score.Grader(real_rows(zone=B), [], RULES, DEFAULTS), {B: [at(t) for t in range(80)]})
    assert single == {"stored": 80, "accepted_in_truth": 80, "accepted_missing_in_core": 0, "rejected_but_stored": 0}


def test_stack_mode_reads_the_device_of_alerts_and_of_what_core_stored(tmp_path, fake_stack):
    url, stack = fake_stack
    rows = trio(80, per={C1: stuck()})
    truth = tmp_path / "truth.jsonl"
    write_truth(truth, rows)
    stack.alerts = {A: [draised("sensor_check", 30, C2)]}
    stack.stored = {A: [{"timestamp": r["sent"]["timestamp"], "device_id": r["device_id"]} for r in rows]}
    out, md = tmp_path / "r.json", tmp_path / "r.md"
    args = ["--truth", str(truth), "--automation-url", url, "--core-url", url, "--json", str(out), "--report", str(md)]
    assert score.main(args + ["--fail-on-miss"]) == 0  # caught on the partner does not fail
    report = json.loads(out.read_text())
    assert report["summary"]["sensor_fault_episodes"]["sensor_check_caught_on_partner"] == 1
    assert report["summary"]["multi_device"] == {"zones": {A: [C1, C2, S1]}}
    assert report["core_check"]["accepted_missing_in_core"] == 0 and report["core_check"]["accepted_in_truth"] == 240
    assert set(report["core_check"]["by_stream"][A]) == {C1, C2, S1}
    assert "caught on the partner probe 1." in md.read_text()
    # Core's events without a device id match no stream of a multi-device zone.
    stack.stored = {A: [r["sent"]["timestamp"] for r in rows]}
    assert score.main(args) == 0
    assert json.loads(out.read_text())["core_check"]["accepted_missing_in_core"] == 240
    # fetch_core_events keeps each stored event's device when it has one.
    got = score.fetch_core_events(url, "demo-farm", [A])
    assert got == {A: [score.parse_ts(r["sent"]["timestamp"]) for r in rows]}  # no device_id stored: plain sample times


def test_no_new_key_on_single_stream_zones_also_in_a_mixed_log():
    b_rows = real_rows(zone=B, total=100)
    b_events = [raised(B, "high_ec_alert", 32), raised(B, "sensor_check", 90)]
    alone = score.Grader(b_rows, b_events, RULES, DEFAULTS)
    alone_report = alone.report()
    # A log with only single-stream zones carries none of the multi-device keys.
    assert "multi_device" not in alone_report["summary"]
    assert "sensor_check_caught_on_partner" not in alone_report["summary"]["sensor_fault_episodes"]
    assert alone_report["metric_definitions"] == score.METRIC_DEFINITIONS
    assert "partners" not in score.markdown(alone_report, "stack", Path("t"))
    # The same zone B in a log whose zone A has three devices: B's items are the same, key for key.
    a_rows = trio(100, per={C1: stuck()})
    mixed = score.Grader(a_rows + b_rows, b_events + [draised("sensor_check", 30, C2)], RULES, DEFAULTS).report()
    assert mixed["summary"]["multi_device"] == {"zones": {A: [C1, C2, S1]}}
    for key in ("real_episodes", "fault_episodes", "false_alarms"):
        assert [i for i in mixed[key] if i["zone"] == B] == alone_report[key], key
    assert "device" not in mixed["real_episodes"][0]["raised"]
    # Zone B's rows of the markdown keep their text.
    only_b = lambda text: [line for line in text.splitlines() if line.startswith(f"| {B}")]
    assert only_b(score.markdown(mixed, "stack", Path("t"))) == only_b(score.markdown(alone_report, "stack", Path("t")))
    for text in only_b(score.markdown(mixed, "stack", Path("t"))):
        assert " · " not in text
    assert all(" · " not in line for line in score.markdown(alone_report, "stack", Path("t")).splitlines())


def test_the_report_and_print_summary_say_which_zones_have_several_devices(capsys):
    report = mgrade(trio(80, per={C1: stuck()}), [draised("sensor_check", 30, C2)])
    assert report["summary"]["multi_device"] == {"zones": {A: [C1, C2, S1]}}
    for key in ("stream", "partners", "caught_on_partner", "device_labels"):
        assert key in report["metric_definitions"]
    assert "stack mode" in report["metric_definitions"]["caught_on_partner"]
    score.print_summary(report, "offline")
    assert ("[offline] multi-device zones greenhouse-a (climate-1, climate-2, substrate-1): "
            "caught on the partner probe 1") in capsys.readouterr().out


def test_replay_offline_keeps_the_logs_device_order_and_keys_results_by_device():
    sim = fg.Simulation(seed=7, clock=fake_clock())
    rows = []
    for _ in range(6):
        for reading in sim.step():
            truth = reading.truth
            if truth["zone_id"] == B:
                rows.append(truth)
                continue
            for device in ("z-device", "a-device"):  # the log's order is not alphabetical
                copy_ = copy.deepcopy(truth)
                copy_["device_id"] = copy_["sent"]["device_id"] = device
                copy_["sent"]["boot_id"] = f"{copy_['sent']['boot_id']}-{device}"
                copy_["sensors"] = list(fg.SENSOR_ORDER)
                rows.append(copy_)
    events, info, _ = score.replay_offline(rows, RULES, DEFAULTS)
    keys_a = [k for k in info if k[0] == A]
    assert keys_a[:4] == [(A, "z-device", 0), (A, "a-device", 0), (A, "z-device", 1), (A, "a-device", 1)]
    assert all(len(k) == 2 for k in info if k[0] == B) and (B, 0) in info  # a single-stream zone: (zone, tick)
    assert score.Grader(rows, events, RULES, DEFAULTS, info).report()["frames"]["total"] == 6 * 3
