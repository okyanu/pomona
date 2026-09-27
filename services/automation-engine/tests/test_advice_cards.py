import sys
from pathlib import Path

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.advice_cards import suggestion_to_advice_card, suggestions_to_advice_cards
import app.main as automation_main
from app.main import app
from app.store import SuggestionStore
from fastapi.testclient import TestClient
import pytest


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


def test_suggestion_maps_to_advice_card():
    card = suggestion_to_advice_card(
        {
            "id": "abc",
            "action": "check_irrigation_system",
            "message": "Check irrigation",
            "status": "pending",
            "created_at": "2026-09-23T12:00:00+00:00",
            "expires_at": "2026-09-23T18:00:00+00:00",
            "context": {
                "zone_id": "greenhouse-a",
                "sensor_timestamp": "2026-09-23T11:40:00+00:00",
                "sensor_quality_labels": ["stuck_value"],
            },
        }
    )
    assert card["card_id"] == "abc"
    assert card["severity"] == "warn"
    assert card["human_review_required"] is True
    assert "autonomous_irrigation_change" in card["blocked_actions"]
    assert card["evidence"]["zone_id"] == "greenhouse-a"


def test_advice_cards_endpoint(client):
    client.post(
        "/v1/automation/evaluate",
        json={"risk_labels": ["high_ec"], "context": {"zone_id": "greenhouse-a"}},
    )
    response = client.get("/v1/automation/advice-cards")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] >= 1
    assert body["cards"][0]["suggestion_id"]
    assert body["cards"][0]["human_review_required"] is True
    assert "autonomous_irrigation_change" in body["cards"][0]["blocked_actions"]


def test_suggestions_to_advice_cards_filters_status():
    cards = suggestions_to_advice_cards(
        [
            {"id": "1", "action": "review", "message": "a", "status": "pending", "context": {}},
            {"id": "2", "action": "review", "message": "b", "status": "approved", "context": {}},
        ],
        status="pending",
    )
    assert len(cards) == 1
    assert cards[0]["card_id"] == "1"


def test_evidence_hash_tracks_snapshot_without_claiming_authentication():
    suggestion={"context":{"sensor_snapshot":{"ph":6.2,"calibration_id":"c1"}}}
    card=suggestion_to_advice_card(suggestion)
    assert card["evidence"]["provenance_status"] == "recorded_snapshot"
    assert card["evidence"]["sensor_snapshot"]["calibration_id"] == "c1"
    assert card["evidence"]["snapshot_sha256"] == suggestion_to_advice_card(suggestion)["evidence"]["snapshot_sha256"]
    suggestion["context"]["sensor_snapshot"]["ph"]=6.3
    assert card["evidence"]["snapshot_sha256"] != suggestion_to_advice_card(suggestion)["evidence"]["snapshot_sha256"]
    assert suggestion_to_advice_card({})["evidence"]["provenance_status"] == "legacy_missing_snapshot"


def test_persisted_snapshot_survives_retry_and_restart(tmp_path):
    path=tmp_path/"suggestions.db"
    store=SuggestionStore(db_path=path)
    context={"sensor_snapshot":{"ph":6.2},"history_snapshot":[{"ph":6.1}]}
    original=store.add("rule", "review", "Check probe", context, event_id="sample-1")
    context["sensor_snapshot"]["ph"]=9
    retry=store.add("rule", "review", "Check probe", context, event_id="sample-1")
    assert retry["context"]["sensor_snapshot"]["ph"]==6.2
    expected=suggestion_to_advice_card(original)["evidence"]["snapshot_sha256"]
    store.close()
    reopened=SuggestionStore(db_path=path)
    try:
        actual=suggestion_to_advice_card(reopened.get(original["id"]))
        assert actual["evidence"]["snapshot_sha256"]==expected
        assert actual["evidence"]["history_snapshot"]==[{"ph":6.1}]
    finally:
        reopened.close()
