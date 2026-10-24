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
import app.store as store_module
from app.advice_cards import suggestion_to_advice_card
from app.alerts import AlertMonitor
from app.rules import InvalidRuleError, load_rules
from app.store import SuggestionStore

T0 = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
RULES = [{"id": "ec", "match_any_labels": ["high_ec"], "action": "review_nutrient_dosing", "message": "High EC."},
         {"id": "slow", "match_any_labels": ["high_ph"], "action": "check_water_dosing_system", "message": "pH.",
          "response_window_seconds": 600}]
CONTEXT = {"farm_id": "farm", "zone_id": "zone", "sensor_snapshot": {"device_id": "node"}}


class Clock:
    now = T0

    def __call__(self) -> str:
        return self.now.isoformat()


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    c.now = T0
    monkeypatch.setattr(store_module, "utc_now_iso", c)
    return c


@pytest.fixture
def store(clock):
    s = SuggestionStore()
    yield s
    s.close()


def approved(store, rule_id="ec", context=CONTEXT):
    item = store.add(rule_id, "review", "check", dict(context))
    return store.decide(item["id"], "approved", rules=RULES)


def observe(store, minutes, labels=(), quality=(), farm="farm", zone="zone", device="node", advance=True):
    sample = T0 + timedelta(minutes=minutes)
    if advance:  # the wall clock follows the sample, as when readings arrive live
        store_module.utc_now_iso.now = max(store_module.utc_now_iso.now, sample)
    store.observe_outcomes(farm, zone, device, sample, labels, quality)


def outcome(store, item):
    got = store.get(item["id"])
    return got["outcome_status"], got["outcome_evidence"]


def test_approve_starts_awaiting_and_reject_does_not(store):
    item = approved(store)
    assert item["outcome_status"] == "awaiting"
    assert item["outcome_deadline"] == (T0 + timedelta(seconds=7200)).isoformat()
    assert item["outcome_evidence"] == {
        "required_clean_readings": 3, "watched_labels": ["high_ec"], "readings_seen": 0, "clean_streak": 0,
        "untrusted_readings": 0, "last_sample_time": None, "resolved_sample_time": None}
    other = store.add("ec", "review", "check", dict(CONTEXT))
    rejected = store.decide(other["id"], "rejected", rules=RULES)
    assert rejected["outcome_status"] is None and rejected["outcome_deadline"] is None and rejected["outcome_evidence"] is None


def test_unknown_rule_or_no_rules_leaves_outcome_untracked(store):
    gone = store.add("removed_rule", "review", "check", dict(CONTEXT))
    assert store.decide(gone["id"], "approved", rules=RULES)["outcome_status"] is None
    plain = store.add("ec", "review", "check", dict(CONTEXT))
    assert store.decide(plain["id"], "approved")["outcome_status"] is None


def test_second_decision_does_not_restart_tracking(store, clock):
    item = approved(store)
    clock.now = T0 + timedelta(minutes=30)
    again = store.decide(item["id"], "approved", rules=RULES)
    assert again["outcome_deadline"] == item["outcome_deadline"]


def test_three_clean_readings_confirm(store):
    item = approved(store)
    observe(store, 5)
    observe(store, 10)
    assert outcome(store, item)[0] == "awaiting"
    observe(store, 15)
    status, evidence = outcome(store, item)
    assert status == "confirmed"
    assert evidence["clean_streak"] == 3 and evidence["readings_seen"] == 3
    assert evidence["resolved_sample_time"] == (T0 + timedelta(minutes=15)).isoformat()


def test_labelled_reading_resets_the_streak(store):
    item = approved(store)
    observe(store, 5)
    observe(store, 10)
    observe(store, 15, labels=["high_ec", "other"])
    assert outcome(store, item)[1]["clean_streak"] == 0
    observe(store, 20)
    observe(store, 25)
    assert outcome(store, item)[0] == "awaiting"
    observe(store, 30, labels=["unrelated_label"])
    assert outcome(store, item)[0] == "confirmed"


def test_old_repeated_and_future_samples_do_not_count(store, clock):
    clock.now = T0 + timedelta(minutes=1)
    item = approved(store)
    observe(store, 0)  # sampled before approval
    observe(store, 1)  # at approval
    assert outcome(store, item)[1]["readings_seen"] == 0
    observe(store, 5)
    observe(store, 5)  # repeat
    observe(store, 3)  # older than the last counted sample
    assert outcome(store, item)[1]["readings_seen"] == 1
    observe(store, 7, advance=False)  # more than 60 s ahead of the wall clock
    assert outcome(store, item)[1]["readings_seen"] == 1


def test_other_zone_farm_and_device_do_not_count(store):
    item = approved(store)
    observe(store, 5, zone="elsewhere")
    observe(store, 6, farm="other-farm")
    observe(store, 7, device="other-node")
    observe(store, 8, device=None)
    assert outcome(store, item)[1]["readings_seen"] == 0
    observe(store, 9)
    assert outcome(store, item)[1]["readings_seen"] == 1


def test_suggestion_without_device_matches_farm_and_zone(store):
    item = approved(store, context={"farm_id": "farm", "zone_id": "zone"})
    observe(store, 5, device="any-node")
    observe(store, 6, device=None)
    assert outcome(store, item)[1]["readings_seen"] == 2


def test_untrusted_readings_do_not_count(store):
    item = approved(store)
    observe(store, 5)
    observe(store, 10, quality=["stuck_value"])
    observe(store, 15, labels=["high_ec"], quality=["stuck_value"])
    status, evidence = outcome(store, item)
    assert (status, evidence["readings_seen"], evidence["clean_streak"], evidence["untrusted_readings"]) == ("awaiting", 1, 1, 2)
    assert evidence["last_sample_time"] == (T0 + timedelta(minutes=15)).isoformat()
    observe(store, 20)
    observe(store, 25)
    assert outcome(store, item)[0] == "confirmed"


def test_window_end_with_label_still_present_is_not_recovered(store, clock):
    item = approved(store)
    for minute in (5, 10, 15):
        observe(store, minute, labels=["high_ec"])
    assert outcome(store, item)[0] == "awaiting"
    clock.now = T0 + timedelta(minutes=120, seconds=30)  # deadline not yet reached on the wall clock
    observe(store, 121, labels=["high_ec"], advance=False)  # sampled past the deadline: closes without counting
    status, evidence = outcome(store, item)
    assert status == "not_recovered" and evidence["readings_seen"] == 3
    assert evidence["finalized_reason"] == "window_ended"
    observe(store, 121, advance=False)  # finalized outcomes are not reopened
    assert outcome(store, item)[0] == "not_recovered"


def test_window_end_with_too_few_readings_is_unconfirmed(store, clock):
    item = approved(store)
    observe(store, 5)
    observe(store, 6, quality=["stuck_value"])
    clock.now = T0 + timedelta(minutes=120, seconds=30)
    observe(store, 121, advance=False)
    status, evidence = outcome(store, item)
    assert status == "unconfirmed" and evidence["readings_seen"] == 1 and evidence["finalized_reason"] == "window_ended"


def test_wall_clock_deadline_with_no_readings_is_unconfirmed(store, clock):
    item = approved(store)
    clock.now = T0 + timedelta(seconds=7199)
    assert outcome(store, item)[0] == "awaiting"
    clock.now = T0 + timedelta(seconds=7200)
    assert [s["outcome_status"] for s in store.list("approved")] == ["unconfirmed"]


def test_wall_clock_deadline_with_enough_labelled_readings_is_not_recovered(store, clock):
    item = approved(store)
    for minute in (5, 10, 15):
        observe(store, minute, labels=["high_ec"])
    clock.now = T0 + timedelta(hours=3)
    assert outcome(store, item)[0] == "not_recovered"


def test_per_rule_window_is_respected(store):
    item = approved(store, "slow")
    assert item["outcome_deadline"] == (T0 + timedelta(seconds=600)).isoformat()


def test_load_rules_response_window(tmp_path):
    def write(value):
        path = tmp_path / "rules.yaml"
        path.write_text(f"rules:\n  - id: r\n    match_any_labels: [high_ec]\n    action: review_nutrient_dosing\n"
                        f"    message: m\n    response_window_seconds: {value!r}\n")
        return path
    assert load_rules(write(900))[0]["response_window_seconds"] == 900
    for bad in (0, -1, 1.5, True, "600", 8 * 24 * 3600):
        with pytest.raises(InvalidRuleError):
            load_rules(write(bad))


def test_shipped_rules_load_without_window_overrides():
    from app.config import settings
    assert all("response_window_seconds" not in r for r in load_rules(settings.rules_path))


def test_outcome_survives_reopen_and_old_db_migrates(tmp_path, clock):
    path = tmp_path / "old.db"
    legacy = sqlite3.connect(path)
    legacy.execute("""CREATE TABLE suggestions (
        seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
        rule_id TEXT NOT NULL, action TEXT NOT NULL, message TEXT NOT NULL,
        context TEXT NOT NULL, status TEXT NOT NULL,
        created_at TEXT NOT NULL, decided_at TEXT, reviewer TEXT)""")
    legacy.execute("INSERT INTO suggestions (id, rule_id, action, message, context, status, created_at, decided_at, reviewer) "
                   "VALUES ('old', 'ec', 'review', 'm', '{}', 'approved', ?, ?, 'Op')",
                   (T0.isoformat(), T0.isoformat()))
    legacy.commit()
    legacy.close()
    store = SuggestionStore(db_path=path)
    old = store.get("old")
    assert old["status"] == "approved" and old["reviewer"] == "Op"
    assert old["outcome_status"] is None and old["outcome_evidence"] is None
    item = approved(store)
    observe(store, 5)
    store.close()
    reopened = SuggestionStore(db_path=path)
    status, evidence = outcome(reopened, item)
    assert status == "awaiting" and evidence["readings_seen"] == 1
    observe(reopened, 10)
    observe(reopened, 15)
    assert outcome(reopened, item)[0] == "confirmed"
    assert reopened.get("old")["outcome_status"] is None
    reopened.close()


def test_advice_card_carries_outcome(store):
    item = approved(store)
    observe(store, 5)
    card = suggestion_to_advice_card(store.get(item["id"]))
    assert card["outcome"]["status"] == "awaiting"
    assert card["outcome"]["deadline"] == item["outcome_deadline"]
    assert card["outcome"]["clean_streak"] == 1 and card["outcome"]["required_clean_readings"] == 3
    pending = store.add("ec", "review", "check", dict(CONTEXT))
    assert suggestion_to_advice_card(pending)["outcome"] is None


@pytest.fixture
def client(monkeypatch, store):
    monkeypatch.setattr(automation_main, "suggestion_store", store)
    monkeypatch.setattr(automation_main, "alert_monitor", AlertMonitor(automation_main.RULES, 600, 900))
    with TestClient(automation_main.app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_api_flow_from_approval_to_confirmed_outcome(client, clock):
    created = client.post("/v1/automation/evaluate", json={"risk_labels": ["high_ec"], "context": dict(CONTEXT)}).json()
    suggestion_id = created["suggestions"][0]["id"]
    assert created["suggestions"][0]["outcome_status"] is None
    approved_item = client.post(f"/v1/automation/suggestions/{suggestion_id}/approve").json()
    assert approved_item["outcome_status"] == "awaiting"
    clock.now = T0 + timedelta(minutes=10)

    def observe_api(minute, **extra):
        return client.post("/v1/automation/alerts/observe", json={
            "farm_id": "farm", "zone_id": "zone", "device_id": "node",
            "sample_time": (T0 + timedelta(minutes=minute)).isoformat(), **extra})

    assert observe_api(5, data_quality_labels=["stuck_value"]).status_code == 200
    for minute in (6, 7, 8):
        assert observe_api(minute, risk_labels=[]).status_code == 200
    assert observe_api(8).json()["ignored"] is True  # repeats never count twice
    item = client.get("/v1/automation/suggestions").json()["suggestions"][0]
    assert item["outcome_status"] == "confirmed" and item["outcome_evidence"]["untrusted_readings"] == 1
    card = client.get("/v1/automation/advice-cards").json()["cards"][0]
    assert card["outcome"]["status"] == "confirmed"
    assert client.post("/v1/automation/alerts/observe", json={
        "farm_id": "farm", "zone_id": "zone", "sample_time": T0.isoformat(),
        "data_quality_labels": "x"}).status_code == 422


SENSOR_RULES = [{"id": "sensor_check", "match_any_labels": ["impossible_ph", "stale_reading"], "action": "check_sensor",
                 "message": "Check the sensor."}]


def approved_sensor_check(store):
    item = store.add("sensor_check", "check_sensor", "check", dict(CONTEXT))
    return store.decide(item["id"], "approved", rules=SENSOR_RULES)


def test_watched_quality_label_is_a_trusted_reading_that_is_not_clean(store):
    item = approved_sensor_check(store)
    observe(store, 5)
    observe(store, 10, labels=["impossible_ph"], quality=["impossible_ph"])
    status, evidence = outcome(store, item)
    assert (evidence["readings_seen"], evidence["clean_streak"], evidence["untrusted_readings"]) == (2, 0, 0)
    observe(store, 15, quality=["stale_reading", "stuck_value"])  # one watched label is enough
    assert outcome(store, item)[1]["readings_seen"] == 3 and outcome(store, item)[1]["clean_streak"] == 0
    for minute in (20, 25, 30):
        observe(store, minute)
    assert outcome(store, item)[0] == "confirmed"


def test_unwatched_quality_label_stays_untrusted_for_a_sensor_check(store):
    item = approved_sensor_check(store)
    observe(store, 5)
    observe(store, 10, quality=["stuck_value"])
    evidence = outcome(store, item)[1]
    assert (evidence["readings_seen"], evidence["clean_streak"], evidence["untrusted_readings"]) == (1, 1, 1)


def test_watched_quality_label_without_a_matching_rule_stays_untrusted(store):
    item = approved(store)  # watches high_ec only
    observe(store, 5, quality=["impossible_ph"])
    evidence = outcome(store, item)[1]
    assert (evidence["readings_seen"], evidence["untrusted_readings"]) == (0, 1)


def test_sensor_check_never_expires_into_not_recovered_without_enough_trusted_readings(store, clock):
    item = approved_sensor_check(store)
    observe(store, 5, quality=["impossible_ph"])
    clock.now = T0 + timedelta(hours=3)
    assert outcome(store, item)[0] == "unconfirmed"  # 1 trusted reading < 3 required
