import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.main as automation_main
from app.main import app
from app.rules import FORBIDDEN_ACTIONS, InvalidRuleError, load_rules
from app.store import SuggestionStore
import app.store as store_module
from datetime import datetime, timedelta, timezone


@pytest.fixture(autouse=True)
def clear_store(monkeypatch):
    store = SuggestionStore()
    monkeypatch.setattr(automation_main, "suggestion_store", store)
    yield
    store.close()


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["rules_loaded"] > 0


def test_expiry_blocks_approval_and_survives_restart(tmp_path, monkeypatch):
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(store_module, "utc_now_iso", lambda: now.isoformat())
    path = tmp_path / "expiry.db"
    store = SuggestionStore(db_path=path, ttl_seconds=10)
    item = store.add("rule", "review", "check", {}, event_id="event")
    assert item["status"] == "pending"
    store.close()
    now += timedelta(seconds=10)
    store = SuggestionStore(db_path=path, ttl_seconds=10)
    assert store.decide(item["id"], "approved")["status"] == "expired"
    assert store.add("rule", "review", "check", {}, event_id="event")["status"] == "expired"
    assert not store.list("pending")
    store.close()


def test_expired_api_approval_returns_conflict(client):
    response = client.post("/v1/automation/evaluate", json={"risk_labels": ["high_ec"], "context": {"sensor_timestamp": "2000-01-01T00:00:00Z"}})
    item = response.json()["suggestions"][0]
    assert item["status"] == "expired"
    assert client.post(f"/v1/automation/suggestions/{item['id']}/approve").status_code == 409
    assert client.get("/v1/automation/suggestions?status=expired").json()["count"] == 1


@pytest.mark.parametrize("timestamp", [None, "bad", "2099-01-01T00:00:00Z", "2026-01-01T00:00:00"])
def test_invalid_sample_context_expires_immediately(timestamp):
    store = SuggestionStore()
    assert store.add("rule", "review", "check", {"sensor_timestamp": timestamp})["status"] == "expired"
    store.close()


def test_evaluate_creates_pending_suggestion_for_high_ec(client: TestClient):
    response = client.post(
        "/v1/automation/evaluate",
        json={"risk_labels": ["high_ec", "nutrient_uptake_issue"], "context": {"zone_id": "greenhouse-a"}},
    )
    assert response.status_code == 200
    suggestions = response.json()["suggestions"]
    assert len(suggestions) == 1
    suggestion = suggestions[0]
    assert suggestion["rule_id"] == "high_ec_alert"
    assert suggestion["action"] == "review_nutrient_dosing"
    assert suggestion["requires_approval"] is True
    assert suggestion["status"] == "pending"
    assert suggestion["context"] == {"zone_id": "greenhouse-a"}


def test_evaluate_with_no_matching_labels_creates_nothing(client: TestClient):
    response = client.post("/v1/automation/evaluate", json={"risk_labels": ["missing_critical_data"]})
    assert response.status_code == 200
    assert response.json()["suggestions"] == []


def test_evaluate_can_match_multiple_rules(client: TestClient):
    response = client.post(
        "/v1/automation/evaluate",
        json={"risk_labels": ["fungal_pressure", "high_ph"]},
    )
    assert response.status_code == 200
    rule_ids = {s["rule_id"] for s in response.json()["suggestions"]}
    assert rule_ids == {"high_humidity_fan", "ph_out_of_range"}


def test_approve_and_reject_suggestion_lifecycle(client: TestClient):
    created = client.post("/v1/automation/evaluate", json={"risk_labels": ["high_ec"]}).json()
    suggestion_id = created["suggestions"][0]["id"]

    pending = client.get("/v1/automation/suggestions", params={"status": "pending"}).json()
    assert pending["count"] == 1

    approve = client.post(f"/v1/automation/suggestions/{suggestion_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"
    assert approve.json()["decided_at"] is not None

    still_pending = client.get("/v1/automation/suggestions", params={"status": "pending"}).json()
    assert still_pending["count"] == 0

    # Deciding again does not flip an already-decided suggestion.
    reject_again = client.post(f"/v1/automation/suggestions/{suggestion_id}/reject")
    assert reject_again.json()["status"] == "approved"


def test_decide_unknown_suggestion_returns_404(client: TestClient):
    response = client.post("/v1/automation/suggestions/does-not-exist/approve")
    assert response.status_code == 404


def test_list_suggestions_rejects_invalid_status_filter(client: TestClient):
    response = client.get("/v1/automation/suggestions", params={"status": "bogus"})
    assert response.status_code == 422


def test_load_rules_rejects_forbidden_action(tmp_path):
    bad_rules = tmp_path / "bad_rules.yaml"
    bad_rules.write_text(
        "rules:\n"
        "  - id: unsafe\n"
        "    match_any_labels: [high_ec]\n"
        "    action: autonomous_fertigation_change\n"
        "    message: This should never load.\n"
    )
    with pytest.raises(InvalidRuleError):
        load_rules(bad_rules)


def test_load_rules_rejects_duplicate_ids(tmp_path):
    dup_rules = tmp_path / "dup_rules.yaml"
    dup_rules.write_text(
        "rules:\n"
        "  - id: dup\n"
        "    match_any_labels: [high_ec]\n"
        "    action: review_nutrient_dosing\n"
        "    message: First.\n"
        "  - id: dup\n"
        "    match_any_labels: [high_ph]\n"
        "    action: check_water_dosing_system\n"
        "    message: Second.\n"
    )
    with pytest.raises(InvalidRuleError):
        load_rules(dup_rules)


def test_shipped_rules_never_suggest_a_forbidden_action():
    rules = load_rules(SERVICE_DIR / "app" / "rules.yaml")
    for rule in rules:
        assert rule["action"] not in FORBIDDEN_ACTIONS


def test_sqlite_history_survives_reopen_and_first_decision_wins(tmp_path):
    path = tmp_path / "history.db"
    first = SuggestionStore(db_path=path)
    item = first.add("test", "review", "Inspect only", {"zone_id": "a"})
    other = SuggestionStore(db_path=path)
    approved = first.decide(item["id"], "approved", "Operator A")
    assert other.decide(item["id"], "rejected", "Operator B") == approved
    first.close()
    other.close()
    reopened = SuggestionStore(db_path=path)
    assert reopened.get(item["id"]) == approved
    assert reopened.list("pending") == []
    assert reopened.list("approved")[0]["reviewer"] == "Operator A"
    reopened.close()


def test_sqlite_retention_order_and_detached_context(tmp_path):
    store = SuggestionStore(max_suggestions=2, db_path=tmp_path / "history.db")
    context = {"zone_id": "a"}
    oldest = store.add("one", "review", "one", context)
    context["zone_id"] = "changed"
    assert store.get(oldest["id"])["context"]["zone_id"] == "a"
    second = store.add("two", "review", "two", {})
    newest = store.add("three", "review", "three", {})
    assert store.get(oldest["id"]) is not None
    assert [s["id"] for s in store.list()] == [newest["id"], second["id"], oldest["id"]]
    store.decide(oldest["id"], "rejected")
    store.decide(second["id"], "approved")
    store.decide(newest["id"], "approved")
    assert store.get(oldest["id"]) is None
    with pytest.raises(ValueError):
        store.decide(newest["id"], "execute")
    store.close()


def test_reviewer_label_round_trip_and_validation(client):
    item = client.post("/v1/automation/evaluate", json={"risk_labels": ["high_ec"]}).json()["suggestions"][0]
    url = f'/v1/automation/suggestions/{item["id"]}/approve'
    assert client.post(url, json={"reviewer": "x" * 81}).status_code == 422
    result = client.post(url, json={"reviewer": "Local operator"}).json()
    assert result["reviewer"] == "Local operator"
    assert result["decided_at"]


def test_same_event_retry_reuses_suggestion_across_connections(tmp_path):
    path = tmp_path / "history.db"
    first = SuggestionStore(db_path=path)
    other = SuggestionStore(db_path=path)
    a = first.add("rule", "review", "Inspect", {"pipeline_id": "run-1"}, "event-1")
    b = other.add("rule", "review", "Inspect", {"pipeline_id": "run-2"}, "event-1")
    assert a == b
    first.decide(a["id"], "approved", "operator")
    assert other.add("rule", "review", "Inspect", {}, "event-1")["status"] == "approved"
    assert other.add("rule", "review", "Inspect", {}, "event-2")["id"] != a["id"]
    first.close()
    other.close()


def test_api_event_id_retry_is_idempotent(client):
    payload = {"event_id": "farm-a/device-a/1", "risk_labels": ["high_ec"]}
    first = client.post("/v1/automation/evaluate", json=payload).json()
    assert client.post("/v1/automation/evaluate", json=payload).json() == first
