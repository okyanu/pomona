import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.main as automation_main
from app.alerts import AlertMonitor
from app.config import settings
from app.rules import InvalidRuleError, load_rules

T0 = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
RULES = [{"id": "ec", "match_any_labels": ["high_ec"], "action": "review_nutrient_dosing", "message": "High EC."},
         {"id": "ph", "match_any_labels": ["high_ph", "low_ph"], "action": "check_water_dosing_system", "message": "pH."}]


def monitor(raise_after=600, clear_after=900, rules=RULES, db_path=None):
    return AlertMonitor(rules, raise_after, clear_after, db_path=db_path)


def feed(m, labels_by_minute, step=5):
    """Observe one reading every `step` minutes; returns the events of each reading."""
    out = []
    for i, labels in enumerate(labels_by_minute):
        out.append(m.observe("farm", "zone", "node", T0 + timedelta(minutes=step * i), labels)["events"])
    return out


def kinds(events):
    return [(e["rule_id"], e["event"]) for step in events for e in step]


def test_label_must_persist_before_alert_is_raised():
    m = monitor()
    events = feed(m, [["high_ec"]] * 2)  # 0 and 5 min: still waiting
    assert kinds(events) == []
    assert m.states()[0]["state"] == "pending"
    events = feed(m, [["high_ec"]] * 5)  # replays 0..5 (ignored), then 10, 15, 20 min
    assert kinds(events) == [("ec", "raised")]
    assert m.states()[0]["state"] == "active"


def test_flicker_while_pending_cancels_and_restarts_the_wait():
    m = monitor()
    events = feed(m, [["high_ec"], ["high_ec"], [], ["high_ec"], ["high_ec"], ["high_ec"]])
    # Gone at 10 min, so the wait restarts at 15 min and ends at 25 min.
    assert kinds(events) == [("ec", "raised")]
    assert len(events[5]) == 1 and events[5][0]["sample_time"] == (T0 + timedelta(minutes=25)).isoformat()


def test_one_raised_and_one_recovered_event_per_incident_despite_flicker():
    m = monitor(raise_after=0, clear_after=900)
    pattern = [["high_ec"], [], ["high_ec"], [], [], ["high_ec"], [], [], [], []]
    events = feed(m, pattern)
    assert kinds(events) == [("ec", "raised"), ("ec", "recovered")]
    # Recovered only after 15 quiet minutes: gone at 30 min, recovered at 45 min.
    assert events[-1][0]["sample_time"] == (T0 + timedelta(minutes=45)).isoformat()
    assert m.states() == []


def test_recovering_alert_shows_its_state_until_cleared():
    m = monitor(raise_after=0, clear_after=900)
    feed(m, [["high_ec"], []])
    state = m.states()[0]
    assert state["state"] == "recovering"
    assert state["raised_at"] == T0.isoformat()
    assert state["recovering_since"] == (T0 + timedelta(minutes=5)).isoformat()


def test_old_and_repeated_samples_never_move_an_alert():
    m = monitor(raise_after=0)
    m.observe("farm", "zone", "node", T0 + timedelta(minutes=10), ["high_ec"])
    assert m.observe("farm", "zone", "node", T0 + timedelta(minutes=10), [])["ignored"] is True
    assert m.observe("farm", "zone", "node", T0, [])["ignored"] is True
    assert m.states()[0]["state"] == "active"


def test_streams_and_rules_are_independent():
    m = monitor(raise_after=0)
    m.observe("farm", "zone", "a", T0, ["high_ec"])
    m.observe("farm", "zone", "b", T0, ["low_ph"])
    m.observe("farm", "other", "a", T0, ["high_ec", "high_ph"])
    assert sorted((s["device_id"], s["rule_id"]) for s in m.states(zone_id="zone")) == [("a", "ec"), ("b", "ph")]
    assert len(m.states(zone_id="other")) == 2


def test_per_rule_windows_override_defaults():
    rules = [{**RULES[0], "raise_after_seconds": 0, "clear_after_seconds": 0}, RULES[1]]
    m = monitor(rules=rules)
    events = feed(m, [["high_ec", "high_ph"], []])
    assert kinds(events) == [("ec", "raised"), ("ec", "recovered")]


def test_state_survives_restart(tmp_path):
    db = tmp_path / "alerts.db"
    m = monitor(db_path=db)
    feed(m, [["high_ec"]] * 2)
    m.close()
    reopened = monitor(db_path=db)
    events = reopened.observe("farm", "zone", "node", T0 + timedelta(minutes=10), ["high_ec"])["events"]
    assert kinds([events]) == [("ec", "raised")]
    assert reopened.events()[0]["event"] == "raised"


def test_naive_sample_time_is_rejected():
    with pytest.raises(ValueError):
        monitor().observe("farm", "zone", None, datetime(2026, 10, 4, 6, 0), [])


def test_shipped_rules_wait_longer_for_humidity():
    rules = load_rules(settings.rules_path)
    fungal = next(r for r in rules if "fungal_pressure" in r["match_any_labels"])
    assert fungal["raise_after_seconds"] == 1800 and fungal["clear_after_seconds"] == 1800
    m = monitor(rules=rules)
    events = feed(m, [["fungal_pressure", "high_ec"]] * 7)  # 0..30 min
    assert kinds(events) == [("high_ec_alert", "raised"), ("high_humidity_fan", "raised")]


def test_shipped_heat_stress_rule_raises_after_the_default_window_with_an_advisory_action():
    rules = load_rules(settings.rules_path)  # load_rules rejects forbidden actions, so loading proves it is advisory
    heat = next(r for r in rules if r["id"] == "heat_stress_check")
    assert heat["match_any_labels"] == ["heat_stress"] and heat["action"] == "check_ventilation_and_shading"
    assert not {"raise_after_seconds", "clear_after_seconds", "raise_after_samples"} & set(heat)  # default windows
    assert "30" in heat["message"] and "second thermometer" in heat["message"]
    assert kinds(feed(monitor(rules=rules), [["heat_stress"]] * 2)) == []  # 0 and 5 min: still waiting
    assert kinds(feed(monitor(rules=rules), [["heat_stress"]] * 3)) == [("heat_stress_check", "raised")]
    assert kinds(feed(monitor(rules=rules), [["heat_stress"], [], ["heat_stress"], ["heat_stress"]])) == []


SAMPLE_RULES = [{"id": "check", "match_any_labels": ["stuck_value"], "action": "check_sensor", "message": "Check.",
                 "raise_after_samples": 3},
                *RULES]


def feed_seconds(m, labels_by_step, step_s=30):
    out = []
    for i, labels in enumerate(labels_by_step):
        out.append(m.observe("farm", "zone", "node", T0 + timedelta(seconds=step_s * i), labels)["events"])
    return out


def test_label_on_three_consecutive_readings_raises_before_the_time_window():
    m = monitor(rules=SAMPLE_RULES)
    events = feed_seconds(m, [["stuck_value"]] * 4)  # 30 s apart: far under the 600 s default
    assert kinds(events) == [("check", "raised")]
    assert len(events[2]) == 1 and events[2][0]["sample_time"] == (T0 + timedelta(seconds=60)).isoformat()
    assert m.states()[0]["state"] == "active"


def test_two_readings_then_a_clean_one_cancel_and_the_count_restarts():
    m = monitor(rules=SAMPLE_RULES)
    events = feed_seconds(m, [["stuck_value"]] * 2 + [[]] + [["stuck_value"]] * 2)
    assert kinds(events) == [] and m.states()[0]["consecutive"] == 2  # the clean reading reset the count
    assert kinds([m.observe("farm", "zone", "node", T0 + timedelta(seconds=150), ["stuck_value"])["events"]]) == [
        ("check", "raised")]


def test_pending_state_counts_consecutive_readings():
    m = monitor(rules=SAMPLE_RULES)
    m.observe("farm", "zone", "node", T0, ["stuck_value"])
    assert (m.states()[0]["state"], m.states()[0]["consecutive"]) == ("pending", 1)
    m.observe("farm", "zone", "node", T0 + timedelta(seconds=30), ["stuck_value"])
    assert m.states()[0]["consecutive"] == 2


def test_seconds_still_raise_for_a_rule_with_samples():
    m = monitor(rules=SAMPLE_RULES)
    # Readings 11 minutes apart: the 600 s window is over at the second reading, before three readings.
    events = [m.observe("farm", "zone", "node", T0 + timedelta(minutes=11 * i), ["stuck_value"])["events"]
              for i in range(2)]
    assert kinds(events) == [("check", "raised")] and len(events[1]) == 1


def test_rules_without_samples_are_unchanged():
    m = monitor(rules=SAMPLE_RULES)
    events = feed_seconds(m, [["high_ec"]] * 10)  # five minutes of 30 s readings: ec has no sample count
    assert kinds(events) == []
    assert kinds(feed_seconds(monitor(rules=SAMPLE_RULES), [["high_ec"]] * 21)) == [("ec", "raised")]  # 600 s


def test_shipped_sensor_check_rule_raises_on_three_readings():
    rules = load_rules(settings.rules_path)
    check = next(r for r in rules if r["id"] == "sensor_check")
    assert check["raise_after_samples"] == 3 and "calibration" in check["message"]
    assert all("raise_after_samples" not in r for r in rules if r["id"] != "sensor_check")  # incl. sensor_flatline
    m = monitor(rules=rules)
    assert kinds(feed_seconds(m, [["baseline_drift_possible"]] * 3)) == [("sensor_check", "raised")]


def test_flatline_waits_the_default_window_while_sensor_check_raises_on_readings():
    rules = load_rules(settings.rules_path)
    m = monitor(rules=rules)
    both = feed_seconds(m, [["flatline_possible", "stuck_value"]] * 4)
    assert kinds(both) == [("sensor_check", "raised")]  # flatline alone needs 600 s of sample time
    assert kinds(feed_seconds(monitor(rules=rules), [["flatline_possible"]] * 21)) == [("sensor_flatline", "raised")]
    assert kinds(feed_seconds(monitor(rules=rules), [["flatline_possible"]] * 19)) == []


def test_a_six_hour_fault_keeps_one_incident_open_until_the_labels_stop():
    rules = load_rules(settings.rules_path)
    m = monitor(rules=rules)
    labels = ["baseline_drift_possible"]  # Core's sticky reference flags the probe on every reading of the fault
    events = feed_seconds(m, [labels] * (6 * 120))  # six hours at 30 s
    assert kinds(events) == [("sensor_check", "raised")]  # one raise, never a recovered event while it lasts
    assert [(a["rule_id"], a["state"]) for a in m.states()] == [("sensor_check", "active")]
    # Once the labels stop (a calibration accepted the level) it recovers after the clear window, not before.
    quiet = [m.observe("farm", "zone", "node", T0 + timedelta(seconds=30 * (6 * 120 + i)), [])["events"] for i in range(40)]
    assert kinds(quiet) == [("sensor_check", "recovered")]


def test_old_database_without_the_consecutive_column_is_migrated(tmp_path):
    import sqlite3
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:  # the schema before raise_after_samples
        conn.execute("""CREATE TABLE alert_states (stream TEXT NOT NULL, rule_id TEXT NOT NULL, state TEXT NOT NULL,
            since TEXT NOT NULL, raised_at TEXT, recovering_since TEXT, PRIMARY KEY (stream, rule_id))""")
        conn.execute("CREATE TABLE alert_stream_samples (stream TEXT PRIMARY KEY, last_sample TEXT NOT NULL)")
        conn.execute("""CREATE TABLE alert_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL,
            rule_id TEXT NOT NULL, event TEXT NOT NULL, sample_time TEXT NOT NULL)""")
        stream = AlertMonitor.stream_key("farm", "zone", "node")
        conn.execute("INSERT INTO alert_states VALUES (?, 'check', 'pending', ?, NULL, NULL)", (stream, T0.isoformat()))
        conn.execute("INSERT INTO alert_stream_samples VALUES (?, ?)", (stream, T0.isoformat()))
    m = monitor(rules=SAMPLE_RULES, db_path=db)
    assert m.states()[0]["state"] == "pending" and m.states()[0]["consecutive"] is None
    # The old pending row counts as one reading, so two more raise.
    events = [m.observe("farm", "zone", "node", T0 + timedelta(seconds=30 * i), ["stuck_value"])["events"]
              for i in (1, 2)]
    assert kinds(events) == [("check", "raised")]
    m.close()
    assert monitor(rules=SAMPLE_RULES, db_path=db).states()[0]["state"] == "active"  # reopening is fine too


@pytest.mark.parametrize("value", [0, -1, 1.5, True, "3", 1001])
def test_load_rules_rejects_bad_sample_counts(tmp_path, value):
    path = tmp_path / "rules.yaml"
    path.write_text(f"rules:\n  - id: r\n    match_any_labels: [stuck_value]\n    action: check_sensor\n"
                    f"    message: m\n    raise_after_samples: {value!r}\n")
    with pytest.raises(InvalidRuleError):
        load_rules(path)


@pytest.mark.parametrize("value", [-1, 1.5, True, "600", 8 * 24 * 3600])
def test_load_rules_rejects_bad_windows(tmp_path, value):
    path = tmp_path / "rules.yaml"
    path.write_text(f"rules:\n  - id: r\n    match_any_labels: [high_ec]\n    action: review_nutrient_dosing\n"
                    f"    message: m\n    raise_after_seconds: {value!r}\n")
    with pytest.raises(InvalidRuleError):
        load_rules(path)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(automation_main, "alert_monitor",
                        AlertMonitor(automation_main.RULES, 0, 900))
    with TestClient(automation_main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_api_observe_and_list(client):
    body = {"farm_id": "farm", "zone_id": "zone", "device_id": "node",
            "sample_time": T0.isoformat(), "risk_labels": ["high_ec"]}
    first = client.post("/v1/automation/alerts/observe", json=body)
    assert first.status_code == 200
    assert [e["event"] for e in first.json()["events"]] == ["raised"]
    assert first.json()["alerts"][0]["state"] == "active"
    assert client.post("/v1/automation/alerts/observe", json=body).json()["ignored"] is True
    listing = client.get("/v1/automation/alerts", params={"zone_id": "zone"}).json()
    assert listing["count"] == 1 and listing["events"][0]["rule_id"] == "high_ec_alert"
    assert client.get("/v1/automation/alerts", params={"zone_id": "elsewhere"}).json()["count"] == 0
    # Suggestions are untouched by alerts.
    assert client.get("/v1/automation/suggestions").json()["count"] == 0


def test_api_alert_events_limit(client):
    """Each incident adds a raised and a recovered event; `limit` pages past the default 50."""
    for i in range(30):
        for minute, labels in ((0, ["high_ec"]), (20, []), (40, [])):
            body = {"farm_id": "farm", "zone_id": "zone", "device_id": "node", "risk_labels": labels,
                    "sample_time": (T0 + timedelta(hours=i, minutes=minute)).isoformat()}
            assert client.post("/v1/automation/alerts/observe", json=body).status_code == 200
    listing = client.get("/v1/automation/alerts", params={"zone_id": "zone"}).json()
    assert len(listing["events"]) == 50
    everything = client.get("/v1/automation/alerts", params={"zone_id": "zone", "limit": 10000}).json()["events"]
    assert len(everything) > 50 and everything[0] == listing["events"][0]
    assert len(client.get("/v1/automation/alerts", params={"limit": 3}).json()["events"]) == 3
    for bad in (0, 10001, "x"):
        assert client.get("/v1/automation/alerts", params={"limit": bad}).status_code == 422


@pytest.mark.parametrize("update", [{"sample_time": "2026-10-04T06:00:00"}, {"farm_id": ""}, {"risk_labels": "high_ec"}])
def test_api_observe_validates_input(client, update):
    body = {"farm_id": "farm", "zone_id": "zone", "sample_time": T0.isoformat(), "risk_labels": [], **update}
    assert client.post("/v1/automation/alerts/observe", json=body).status_code == 422
