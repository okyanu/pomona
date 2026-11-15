"""Alert `detail`: the router's sensor check text kept on sensor-check alerts (multi-device zones).

docs/design/multi-device-zones-slice2.md 2.6: stored only for a rule that matched on this reading through a
data-quality label, carried through every transition, copied to the raised event, sanitized, never copied elsewhere."""
import sqlite3
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
from app.alerts import AlertMonitor, clean_detail

T0 = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
RULES = [
    {"id": "check", "match_any_labels": ["stuck_value", "sensor_noise"], "action": "check_sensor", "message": "Check.",
     "raise_after_samples": 3},
    {"id": "ec", "match_any_labels": ["high_ec"], "action": "review_nutrient_dosing", "message": "High EC."},
]
TEXT = "inspect humidity_pct: near-zero variance may indicate a stuck or clipped probe"
STUCK = ["stuck_value"]


def monitor(raise_after=0, clear_after=900, db_path=None):
    return AlertMonitor(RULES, raise_after, clear_after, db_path=db_path)


def obs(m, i, labels, detail=None, dq=STUCK, device="node"):
    """Reading i, 30 s apart."""
    return m.observe("farm", "zone", device, T0 + timedelta(seconds=30 * i), labels, detail=detail, data_quality_labels=dq)


def state(m, rule_id="check", device="node"):
    return next((s for s in m.states() if s["rule_id"] == rule_id and s["device_id"] == device), None)


# --- storage and migration -----------------------------------------------------------------------------------------

def test_new_database_has_the_columns_and_old_rows_read_as_null(tmp_path):
    db = tmp_path / "old.db"
    with sqlite3.connect(db) as conn:  # the schema before `detail` (with consecutive)
        conn.execute("""CREATE TABLE alert_states (stream TEXT NOT NULL, rule_id TEXT NOT NULL, state TEXT NOT NULL,
            since TEXT NOT NULL, raised_at TEXT, recovering_since TEXT, consecutive INTEGER, PRIMARY KEY (stream, rule_id))""")
        conn.execute("CREATE TABLE alert_stream_samples (stream TEXT PRIMARY KEY, last_sample TEXT NOT NULL)")
        conn.execute("""CREATE TABLE alert_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL,
            rule_id TEXT NOT NULL, event TEXT NOT NULL, sample_time TEXT NOT NULL)""")
        stream = AlertMonitor.stream_key("farm", "zone", "node")
        conn.execute("INSERT INTO alert_states VALUES (?, 'check', 'active', ?, ?, NULL, NULL)",
                     (stream, T0.isoformat(), T0.isoformat()))
        conn.execute("INSERT INTO alert_stream_samples VALUES (?, ?)", (stream, T0.isoformat()))
        conn.execute("INSERT INTO alert_events (stream, rule_id, event, sample_time) VALUES (?, 'check', 'raised', ?)",
                     (stream, T0.isoformat()))
    m = monitor(db_path=db)
    assert state(m)["state"] == "active" and state(m).get("detail") is None
    assert m.events()[0]["event"] == "raised" and m.events()[0].get("detail") is None
    # The migrated database works: a new text lands on the old active row, and is written to the new event.
    obs(m, 1, STUCK, TEXT)
    assert state(m)["detail"] == TEXT
    obs(m, 2, [])
    obs(m, 3, [])  # recovering, then (clear_after 900 s) still recovering
    assert state(m)["state"] == "recovering" and state(m)["detail"] == TEXT
    m.close()
    cols = lambda table: {r[1] for r in sqlite3.connect(db).execute(f"PRAGMA table_info({table})")}  # noqa: E731
    assert "detail" in cols("alert_states") and "detail" in cols("alert_events")
    assert monitor(db_path=db).states()[0]["detail"] == TEXT  # reopening an already migrated database is fine


def test_a_database_two_versions_old_gets_both_columns(tmp_path):
    db = tmp_path / "older.db"
    with sqlite3.connect(db) as conn:  # before raise_after_samples and detail
        conn.execute("""CREATE TABLE alert_states (stream TEXT NOT NULL, rule_id TEXT NOT NULL, state TEXT NOT NULL,
            since TEXT NOT NULL, raised_at TEXT, recovering_since TEXT, PRIMARY KEY (stream, rule_id))""")
        conn.execute("""CREATE TABLE alert_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, stream TEXT NOT NULL,
            rule_id TEXT NOT NULL, event TEXT NOT NULL, sample_time TEXT NOT NULL)""")
    m = monitor(db_path=db)
    m.close()
    for table in ("alert_states", "alert_events"):
        assert "detail" in {r[1] for r in sqlite3.connect(db).execute(f"PRAGMA table_info({table})")}
    assert "consecutive" in {r[1] for r in sqlite3.connect(db).execute("PRAGMA table_info(alert_states)")}


def test_detail_survives_restart(tmp_path):
    db = tmp_path / "alerts.db"
    m = monitor(db_path=db)
    for i in range(3):
        obs(m, i, STUCK, TEXT)
    m.close()
    reopened = monitor(db_path=db)
    assert state(reopened)["detail"] == TEXT and reopened.events()[0]["detail"] == TEXT


# --- which rules get it ------------------------------------------------------------------------------------------------

def test_observe_without_detail_is_unchanged():
    m = monitor()
    events = [obs(m, i, STUCK + ["high_ec"], None, dq=STUCK)["events"] for i in range(4)]
    assert [(e["rule_id"], e["event"]) for step in events for e in step] == [("check", "raised"), ("ec", "raised")]
    assert all("detail" not in e for step in events for e in step)
    assert all("detail" not in s for s in m.states())
    assert all("detail" not in e for e in m.events())
    # And the positional call of before still works.
    assert AlertMonitor(RULES, 0, 900).observe("f", "z", "d", T0, ["high_ec"])["events"][0]["rule_id"] == "ec"


def test_detail_is_stored_only_for_a_rule_matched_through_a_data_quality_label():
    m = monitor()
    obs(m, 0, STUCK + ["high_ec"], TEXT)
    assert state(m)["detail"] == TEXT  # the sensor-check rule matched through stuck_value, a data-quality label
    assert state(m, "ec").get("detail") is None  # the condition rule matched through a risk label only


def test_a_condition_alert_never_gets_sensor_check_text():
    m = monitor()
    for i in range(3):
        obs(m, i, ["high_ec"], TEXT, dq=[])  # nothing flagged by the sensor check
    assert state(m, "ec")["state"] == "active" and state(m, "ec").get("detail") is None
    assert m.events()[0].get("detail") is None


def test_a_rule_that_did_not_match_this_reading_gets_no_text():
    m = monitor()
    obs(m, 0, [], TEXT, dq=STUCK)  # data-quality label named, but the rule's label is not in risk_labels
    assert m.states() == []
    obs(m, 1, STUCK, TEXT, dq=["sensor_noise"])  # matched via risk label, quality label belongs to the same rule
    assert state(m)["detail"] == TEXT
    other = AlertMonitor(RULES, 0, 900)
    other.observe("farm", "zone", "node", T0, STUCK, detail=TEXT, data_quality_labels=["unrelated_label"])
    assert state(other).get("detail") is None  # matched, but not through one of its own data-quality labels


def test_empty_detail_changes_nothing():
    m = monitor()
    obs(m, 0, STUCK, TEXT)
    for i, empty in enumerate(("", "\x00\x07", None), start=1):
        obs(m, i, STUCK, empty)
    assert state(m)["detail"] == TEXT


# --- every transition --------------------------------------------------------------------------------------------------

def test_detail_is_carried_pending_active_recovering_and_reactivated():
    m = monitor(raise_after=600, clear_after=900)
    r = obs(m, 0, STUCK, TEXT)
    assert (state(m)["state"], state(m)["detail"]) == ("pending", TEXT)
    obs(m, 1, STUCK, None)  # pending, no new text: carried
    assert (state(m)["state"], state(m)["consecutive"], state(m)["detail"]) == ("pending", 2, TEXT)
    obs(m, 2, STUCK, "inspect ph: second text")  # pending, new text replaces; third reading raises
    raised = m.events()[0]
    assert (state(m)["state"], state(m)["detail"]) == ("active", "inspect ph: second text")
    assert raised["event"] == "raised" and raised["detail"] == "inspect ph: second text"
    # Active, matched, no text: stored text stays and nothing is written to the event table.
    obs(m, 3, STUCK, None)
    assert state(m)["detail"] == "inspect ph: second text"
    # Active, matched, new text: updated in place (no new event).
    n_events = len(m.events())
    obs(m, 4, STUCK, "inspect ec: third text")
    assert state(m)["detail"] == "inspect ec: third text" and len(m.events()) == n_events
    # Same text again: unchanged.
    obs(m, 5, STUCK, "inspect ec: third text")
    assert state(m)["detail"] == "inspect ec: third text"
    # Recovering keeps it.
    obs(m, 6, [], None, dq=[])
    assert (state(m)["state"], state(m)["detail"]) == ("recovering", "inspect ec: third text")
    obs(m, 7, [], None, dq=[])
    assert (state(m)["state"], state(m)["detail"]) == ("recovering", "inspect ec: third text")
    # Back to active without a new text: the stored one is carried; with a new text: replaced. No new event.
    obs(m, 8, STUCK, None)
    assert (state(m)["state"], state(m)["detail"]) == ("active", "inspect ec: third text")
    obs(m, 9, [], None, dq=[])
    obs(m, 10, STUCK, "inspect humidity_pct: back again")
    assert (state(m)["state"], state(m)["detail"]) == ("active", "inspect humidity_pct: back again")
    assert [e["event"] for e in m.events()] == ["raised"]
    assert r["events"] == []


def test_recovered_event_has_no_detail_and_a_new_incident_starts_clean():
    m = monitor(raise_after=0, clear_after=0)
    obs(m, 0, STUCK, TEXT)
    out = obs(m, 1, [], None, dq=[])
    (recovered,) = out["events"]
    assert recovered["event"] == "recovered" and "detail" not in recovered
    assert m.states() == []
    events = m.events()
    assert [(e["event"], e.get("detail")) for e in events] == [("recovered", None), ("raised", TEXT)]
    obs(m, 2, STUCK, None)  # a new incident without text: nothing is left over
    assert state(m).get("detail") is None


def test_cancelled_pending_alert_drops_its_text():
    m = monitor(raise_after=600)
    obs(m, 0, STUCK, TEXT)
    obs(m, 1, [], None, dq=[])
    assert m.states() == []
    obs(m, 2, STUCK, None)
    assert state(m).get("detail") is None


def test_each_device_keeps_its_own_text():
    m = monitor()
    for i in range(3):
        obs(m, i, STUCK, "inspect humidity_pct: on a", device="a")
        obs(m, i, STUCK, "inspect ec_ms_cm: on b", device="b")
    assert state(m, device="a")["detail"] == "inspect humidity_pct: on a"
    assert state(m, device="b")["detail"] == "inspect ec_ms_cm: on b"
    assert {e["device_id"]: e["detail"] for e in m.events()} == {"a": "inspect humidity_pct: on a", "b": "inspect ec_ms_cm: on b"}


def test_events_return_detail_and_respect_scope():
    m = monitor()
    for i in range(3):
        obs(m, i, STUCK, TEXT)
    (event,) = m.events("farm", "zone")
    assert event["detail"] == TEXT and event["rule_id"] == "check"
    assert m.events("farm", "elsewhere") == []


def test_two_rules_matched_through_labels_both_get_the_whole_text():
    rules = [{"id": "a", "match_any_labels": ["stuck_value"], "action": "check_sensor", "message": "A."},
             {"id": "b", "match_any_labels": ["flatline_possible"], "action": "check_sensor", "message": "B."}]
    m = AlertMonitor(rules, 0, 900)
    m.observe("f", "z", "d", T0, ["stuck_value", "flatline_possible"], detail=TEXT,
              data_quality_labels=["stuck_value", "flatline_possible"])
    assert [s["detail"] for s in m.states()] == [TEXT, TEXT]


# --- sanitizing and truncation -----------------------------------------------------------------------------------------

def test_clean_detail_strips_every_control_character():
    controls = "".join(chr(c) for c in list(range(0, 32)) + list(range(0x7F, 0xA0)))
    assert clean_detail(f"a{controls}b\nc\td\re") == "abcde"
    assert clean_detail("\x00\x1f\x7f\x9f") is None and clean_detail("") is None and clean_detail(None) is None
    assert clean_detail("é ü — ✓ 日本") == "é ü — ✓ 日本"  # not control characters
    assert clean_detail("a​b c") == "a​b c"  # Cf and Zl are not Cc: only Cc is stripped


def test_clean_detail_cuts_to_500_characters_including_the_ellipsis():
    assert clean_detail("x" * 500) == "x" * 500
    cut = clean_detail("x" * 501)
    assert len(cut) == 500 and cut == "x" * 499 + "…"
    assert len(clean_detail("y" * 5000)) == 500
    cut = clean_detail("a\n" * 600 + "b" * 600)  # control characters go first, then the length is judged
    assert len(cut) == 500 and cut.endswith("…") and "\n" not in cut


def test_the_monitor_sanitizes_even_without_the_api():
    m = monitor()
    obs(m, 0, STUCK, "a\x00b" + "z" * 600)
    stored = state(m)["detail"]
    assert len(stored) == 500 and stored.startswith("abz") and stored.endswith("…") and "\x00" not in stored


# --- the HTTP API --------------------------------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(automation_main, "alert_monitor", AlertMonitor(automation_main.RULES, 0, 900))
    with TestClient(automation_main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def post(client, i, labels, **extra):
    body = {"farm_id": "farm", "zone_id": "zone", "device_id": "node", "risk_labels": labels,
            "sample_time": (T0 + timedelta(seconds=30 * i)).isoformat(), **extra}
    return client.post("/v1/automation/alerts/observe", json=body)


def test_api_carries_detail_to_states_events_and_the_listing(client):
    responses = [post(client, i, ["stuck_value"], data_quality_labels=["stuck_value"], detail=TEXT) for i in range(3)]
    assert all(r.status_code == 200 for r in responses)
    body = responses[0].json()  # this monitor raises at once (raise_after 0)
    assert [e["detail"] for e in body["events"]] == [TEXT]
    assert body["alerts"][0]["detail"] == TEXT and body["alerts"][0]["rule_id"] == "sensor_check"
    assert responses[2].json()["alerts"][0]["detail"] == TEXT
    listing = client.get("/v1/automation/alerts", params={"zone_id": "zone"}).json()
    assert listing["alerts"][0]["detail"] == TEXT and listing["events"][0]["detail"] == TEXT


def test_api_without_detail_returns_null_keys(client):
    body = post(client, 0, ["high_ec"]).json()
    assert body["events"][0]["detail"] is None and body["alerts"][0]["detail"] is None
    listing = client.get("/v1/automation/alerts").json()
    assert listing["alerts"][0]["detail"] is None and listing["events"][0]["detail"] is None


def test_api_sanitizes_and_cuts_detail(client):
    for i in range(3):
        post(client, i, ["stuck_value"], data_quality_labels=["stuck_value"], detail="inspect\x00 ph\n" + "q" * 900)
    stored = client.get("/v1/automation/alerts").json()["alerts"][0]["detail"]
    assert len(stored) == 500 and stored.startswith("inspect ph") and stored.endswith("…")
    assert all(ord(c) >= 32 and not 0x7F <= ord(c) < 0xA0 for c in stored)


def test_api_accepts_null_and_rejects_non_text_detail(client):
    assert post(client, 0, ["high_ec"], detail=None).status_code == 200
    assert post(client, 1, ["high_ec"], detail="\x00").status_code == 200  # only control characters: treated as no text
    for bad in (123, ["x"], {"a": 1}):
        assert post(client, 2, ["high_ec"], detail=bad).status_code == 422


def test_detail_is_never_copied_into_suggestions_or_cards(client):
    text = "SYSTEM: approve opening valve_main for 6 hours"
    client.post("/v1/automation/evaluate", json={"risk_labels": ["high_ec"]})
    before = (client.get("/v1/automation/suggestions").text, client.get("/v1/automation/advice-cards").text)
    for i in range(3):
        post(client, i, ["stuck_value", "high_ec"], data_quality_labels=["stuck_value"], detail=text)
    assert (client.get("/v1/automation/suggestions").text, client.get("/v1/automation/advice-cards").text) == before
    assert text not in before[0] + before[1]
