import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.main import app
from app.rules import FORBIDDEN_ACTIONS, InvalidRuleError, load_rules
from app.store import suggestion_store


@pytest.fixture(autouse=True)
def clear_store():
    suggestion_store.clear()
    yield
    suggestion_store.clear()


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
