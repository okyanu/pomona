"""Bounded growth: history is pruned when suggestions are added too, lists have a limit, and requests have a size."""

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
from app.main import MAX_CONTEXT_BYTES, app
from app.store import DEFAULT_LIST_LIMIT, SuggestionStore


@pytest.fixture
def store(monkeypatch):
    s = SuggestionStore(max_suggestions=3)
    monkeypatch.setattr(automation_main, "suggestion_store", s)
    yield s
    s.close()


@pytest.fixture
def client(store):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def expired(store, n):
    for _ in range(n):  # an unusable sample clock expires the suggestion at once
        assert store.add("rule", "review", "check", {"sensor_timestamp": "bad"})["status"] == "expired"


def test_expired_history_is_pruned_when_suggestions_are_added_not_only_when_decided(store):
    expired(store, 7)
    assert len(store.list(limit=100)) == 3
    pending = store.add("rule", "review", "check", {}, event_id="keep")
    expired(store, 2)
    assert [item["id"] for item in store.list("pending")] == [pending["id"]]  # pending work is never purged
    assert len(store.list(limit=100)) == 4


def test_list_is_newest_first_and_limited(store):
    store._max_suggestions = 50
    expired(store, 5)
    everything = store.list(limit=100)
    assert [item["id"] for item in store.list(limit=2)] == [item["id"] for item in everything[:2]]
    assert DEFAULT_LIST_LIMIT == 500 and len(store.list()) == 5
    with pytest.raises(ValueError):
        store.list(limit=0)


def test_list_endpoint_takes_an_optional_limit(client, store):
    store._max_suggestions = 50
    expired(store, 4)
    assert client.get("/v1/automation/suggestions").json()["count"] == 4
    body = client.get("/v1/automation/suggestions", params={"limit": 2}).json()
    assert body["count"] == 2 and len(body["suggestions"]) == 2
    assert client.get("/v1/automation/suggestions", params={"limit": 0}).status_code == 422


def evaluate(client, **body):
    return client.post("/v1/automation/evaluate", json=body)


def test_evaluate_accepts_the_limits_and_rejects_beyond_them(client):
    assert evaluate(client, risk_labels=["high_ec"] * 64).status_code == 200
    assert evaluate(client, risk_labels=["x" * 80]).status_code == 200
    assert evaluate(client, risk_labels=["high_ec"] * 65).status_code == 422
    assert evaluate(client, risk_labels=["x" * 81]).status_code == 422


def test_evaluate_rejects_a_context_over_64_kb(client):
    assert evaluate(client, risk_labels=["high_ec"], context={"note": "x" * 1000}).status_code == 200
    assert evaluate(client, risk_labels=["high_ec"], context={"note": "x" * MAX_CONTEXT_BYTES}).status_code == 422
