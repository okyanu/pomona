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


@pytest.mark.parametrize("update", [{"sample_time": "2026-10-04T06:00:00"}, {"farm_id": ""}, {"risk_labels": "high_ec"}])
def test_api_observe_validates_input(client, update):
    body = {"farm_id": "farm", "zone_id": "zone", "sample_time": T0.isoformat(), "risk_labels": [], **update}
    assert client.post("/v1/automation/alerts/observe", json=body).status_code == 422
