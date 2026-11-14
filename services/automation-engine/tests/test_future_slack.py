"""A sample time up to MAX_FUTURE_SAMPLE_S ahead (Core accepts it, default 300 s) counts as current here too.

With the setting 0 the old 60 s limit holds. Same setting, same meaning as Core's `future_slack_s`.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.store as store_module
from app.config import Settings
from app.store import SuggestionStore

RULES = [{"id": "ec", "match_any_labels": ["high_ec"], "action": "review", "message": "High EC."}]
CONTEXT = {"farm_id": "farm", "zone_id": "zone", "sensor_snapshot": {"device_id": "node"}}


@pytest.fixture
def store():
    s = SuggestionStore()
    yield s
    s.close()


def ahead(seconds):
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def test_future_slack_is_the_setting_or_60_when_it_is_off():
    assert Settings(max_future_sample_s=300).future_slack_s == 300
    assert Settings(max_future_sample_s=0).future_slack_s == 60


def test_suggestion_for_a_sample_two_minutes_ahead_is_pending(store):
    context = {**CONTEXT, "sensor_timestamp": ahead(120).isoformat()}
    assert store.add("ec", "review", "check", context)["status"] == "pending"
    beyond = {**CONTEXT, "sensor_timestamp": ahead(600).isoformat()}
    assert store.add("ec", "review", "check", beyond)["status"] == "expired"


def test_suggestion_for_a_sample_two_minutes_ahead_expires_with_the_setting_off(store, monkeypatch):
    monkeypatch.setattr(store_module.settings, "max_future_sample_s", 0)
    context = {**CONTEXT, "sensor_timestamp": ahead(120).isoformat()}
    assert store.add("ec", "review", "check", context)["status"] == "expired"


def test_outcome_reading_two_minutes_ahead_counts(store):
    item = store.add("ec", "review", "check", dict(CONTEXT))
    store.decide(item["id"], "approved", rules=RULES)
    store.observe_outcomes("farm", "zone", "node", ahead(120), [])
    assert store.get(item["id"])["outcome_evidence"]["readings_seen"] == 1


def test_outcome_reading_two_minutes_ahead_is_ignored_with_the_setting_off(store, monkeypatch):
    monkeypatch.setattr(store_module.settings, "max_future_sample_s", 0)
    item = store.add("ec", "review", "check", dict(CONTEXT))
    store.decide(item["id"], "approved", rules=RULES)
    store.observe_outcomes("farm", "zone", "node", ahead(120), [])
    assert store.get(item["id"])["outcome_evidence"]["readings_seen"] == 0
