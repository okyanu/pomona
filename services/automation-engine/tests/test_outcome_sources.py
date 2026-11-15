"""Outcome tracking with `sources` (docs/design/multi-device-zones-slice2.md 2.7): which devices' readings count."""
import json
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
from app.outcome_fields import counting_devices, watched_fields
from app.store import SuggestionStore

T0 = datetime(2026, 10, 4, 6, 0, tzinfo=timezone.utc)
RULES = [
    {"id": "ec", "match_any_labels": ["high_ec"], "action": "review_nutrient_dosing", "message": "High EC."},
    {"id": "heat", "match_any_labels": ["heat_stress"], "action": "check_ventilation_and_shading", "message": "Heat."},
    {"id": "fungal", "match_any_labels": ["fungal_pressure"], "action": "increase_ventilation", "message": "Humid."},
    {"id": "sensor", "match_any_labels": ["stuck_value", "missing_ec"], "action": "check_sensor", "message": "Check."},
]
SOURCES = {"air_temperature_c": ["climate-1"], "humidity_pct": ["climate-1"], "ph": ["substrate-1"],
           "ec_ms_cm": ["substrate-1"], "substrate_temperature_c": ["substrate-1"]}


def context(**extra):
    return {"farm_id": "farm", "zone_id": "zone", "sensor_snapshot": {"farm_id": "farm", "zone_id": "zone"},
            "sources": dict(SOURCES), **extra}


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


def approved(store, rule_id="ec", ctx=None):
    item = store.add(rule_id, "review", "check", dict(ctx if ctx is not None else context()))
    return store.decide(item["id"], "approved", rules=RULES)


def observe(store, minutes, device, labels=(), quality=(), seconds=0):
    sample = T0 + timedelta(minutes=minutes, seconds=seconds)
    store_module.utc_now_iso.now = max(store_module.utc_now_iso.now, sample)
    store.observe_outcomes("farm", "zone", device, sample, labels, quality)


def outcome(store, item):
    got = store.get(item["id"])
    return got["outcome_status"], got["outcome_evidence"]


def test_field_map_matches_the_router_labels():
    assert watched_fields(["high_ec", "low_ec"], {}) == {"ec_ms_cm"}
    assert watched_fields(["high_ph"], {}) == {"ph"}
    assert watched_fields(["heat_stress"], {}) == {"air_temperature_c", "substrate_temperature_c"}
    assert watched_fields(["cold_stress"], {}) == {"air_temperature_c", "substrate_temperature_c"}
    assert watched_fields(["fungal_pressure"], {}) == {"air_temperature_c", "humidity_pct"}
    assert watched_fields(["water_level_risk"], {}) == {"substrate_moisture_pct", "root_zone_moisture_pct", "soil_moisture_pct"}
    # a sensor-check label stands for the suggestion's own vetoed and missing fields
    assert watched_fields(["stuck_value"], {"vetoed_fields": ["humidity_pct"], "missing_fields": ["ec_ms_cm", 7]}) == {
        "humidity_pct", "ec_ms_cm"}
    assert watched_fields(["stuck_value"], {}) == set()
    assert counting_devices({"ec_ms_cm": ["b", "a"], "ph": ["c"]}, {"ec_ms_cm", "humidity_pct"}) == ["a", "b"]
    assert counting_devices({"ec_ms_cm": ["a"]}, set()) == []


def test_an_ec_suggestion_counts_only_the_substrate_node(store):
    item = approved(store)
    for minute in (5, 10, 15, 20):
        observe(store, minute, "climate-1")  # clean climate readings never confirm an EC suggestion
    status, evidence = outcome(store, item)
    assert status == "awaiting" and evidence["readings_seen"] == 0
    observe(store, 21, "substrate-1")
    observe(store, 22, "substrate-1")
    assert outcome(store, item)[0] == "awaiting"
    observe(store, 23, "substrate-1")
    status, evidence = outcome(store, item)
    assert status == "confirmed" and evidence["clean_streak"] == 3
    assert evidence["last_sample_by_device"] == {"substrate-1": (T0 + timedelta(minutes=23)).isoformat()}


def test_a_flagged_climate_reading_does_not_reset_an_ec_suggestion(store):
    item = approved(store)
    observe(store, 5, "substrate-1")
    observe(store, 6, "climate-1", labels=["high_ec"])  # not a counting device: ignored
    observe(store, 10, "substrate-1")
    observe(store, 15, "substrate-1")
    assert outcome(store, item)[0] == "confirmed"


def test_a_heat_suggestion_counts_the_air_and_the_substrate_temperature_devices(store):
    item = approved(store, "heat")
    observe(store, 5, "climate-1")
    observe(store, 6, "substrate-1")
    observe(store, 7, "other-node")  # carries neither field
    status, evidence = outcome(store, item)
    assert status == "awaiting" and evidence["readings_seen"] == 2
    observe(store, 10, "climate-1")
    assert outcome(store, item)[0] == "confirmed"  # streak 3, both devices clean inside it


def test_a_sensor_suggestion_uses_its_own_fields(store):
    ctx = context(vetoed_fields=["humidity_pct"], missing_fields=["ec_ms_cm"])
    item = approved(store, "sensor", ctx)
    observe(store, 5, "climate-1")
    observe(store, 6, "substrate-1")  # EC is missing: its expected carrier counts too
    observe(store, 7, "other-node")
    status, evidence = outcome(store, item)
    assert evidence["readings_seen"] == 2 and status == "awaiting"
    observe(store, 8, "climate-1", quality=["stuck_value"], labels=["stuck_value"])  # still stuck: resets
    status, evidence = outcome(store, item)
    assert evidence["clean_streak"] == 0 and evidence["clean_streak_devices"] == []


def test_an_empty_counting_set_confirms_nothing(store, clock):
    # nobody is expected to carry a field the suggestion watches; nothing counts and it ends unconfirmed
    item = approved(store, "ec", context(sources={"air_temperature_c": ["climate-1"]}))
    for minute in range(5, 60, 5):
        observe(store, minute, "climate-1")
        observe(store, minute, "substrate-1")
    status, evidence = outcome(store, item)
    assert status == "awaiting" and evidence["readings_seen"] == 0
    clock.now = T0 + timedelta(hours=3)
    assert [s["outcome_status"] for s in store.list("approved")] == ["unconfirmed"]
    nothing_to_watch = approved(store, "sensor")  # a sensor suggestion that names no field
    for minute in range(70, 100, 5):
        observe(store, minute, "climate-1")
    assert outcome(store, nothing_to_watch)[1]["readings_seen"] == 0


def test_a_reading_without_a_device_is_skipped(store):
    item = approved(store)
    for minute in (5, 10, 15):
        observe(store, minute, None)
    assert outcome(store, item)[1]["readings_seen"] == 0


def test_two_devices_at_30_s_and_5_min_interleaved_drop_nothing_and_the_fast_one_alone_cannot_confirm(store):
    ctx = context(sources={"air_temperature_c": ["fast"], "humidity_pct": ["slow"]})
    item = approved(store, "fungal", ctx)
    for seconds in (0, 30, 60):  # three clean packets from the fast node alone
        observe(store, 1, "fast", seconds=seconds)
    status, evidence = outcome(store, item)
    assert status == "awaiting" and evidence["clean_streak"] == 3 and evidence["clean_streak_devices"] == ["fast"]
    # The slow node's reading was sampled at 0:01:10, before the fast node's last packet (0:02:00) but it arrives after
    # it: its own last sample time is None, so it is not dropped, and it completes the streak.
    observe(store, 1, "slow", seconds=10)
    status, evidence = outcome(store, item)
    assert status == "confirmed" and evidence["readings_seen"] == 4 and evidence["clean_streak_devices"] == ["fast", "slow"]
    assert evidence["last_sample_by_device"]["slow"] == (T0 + timedelta(minutes=1, seconds=10)).isoformat()
    assert evidence["last_sample_by_device"]["fast"] == (T0 + timedelta(minutes=2)).isoformat()
    assert evidence["last_sample_time"] == (T0 + timedelta(minutes=2)).isoformat()  # the newest of all


def test_a_repeated_or_older_sample_of_the_same_device_is_ignored(store):
    ctx = context(sources={"air_temperature_c": ["fast"], "humidity_pct": ["slow"]})
    item = approved(store, "fungal", ctx)
    observe(store, 5, "fast", seconds=30)
    observe(store, 5, "fast", seconds=30)  # repeat
    observe(store, 5, "fast", seconds=10)  # older than this device's last sample
    observe(store, 5, "slow", seconds=5)  # older than the fast node's last sample, but it is the slow node's first
    assert outcome(store, item)[1]["readings_seen"] == 2


def test_confirmation_needs_a_clean_reading_from_every_counting_device(store):
    ctx = context(sources={"air_temperature_c": ["fast"], "humidity_pct": ["slow"]})
    item = approved(store, "fungal", ctx)
    for minute in (5, 6, 7, 8, 9):
        observe(store, minute, "fast")  # five clean readings from the fast device alone
    status, evidence = outcome(store, item)
    assert status == "awaiting" and evidence["clean_streak"] == 5 and evidence["clean_streak_devices"] == ["fast"]
    observe(store, 10, "slow", labels=["fungal_pressure"])  # a flagged reading from a counting device resets the streak
    assert outcome(store, item)[1]["clean_streak"] == 0
    observe(store, 11, "fast")
    observe(store, 12, "fast")
    observe(store, 13, "fast")
    assert outcome(store, item)[0] == "awaiting"
    observe(store, 14, "slow")
    status, evidence = outcome(store, item)
    assert status == "confirmed" and evidence["clean_streak"] == 4
    assert evidence["resolved_sample_time"] == (T0 + timedelta(minutes=14)).isoformat()


def test_without_sources_the_single_device_rule_is_unchanged(store):
    ctx = {"farm_id": "farm", "zone_id": "zone", "sensor_snapshot": {"device_id": "node"}}
    item = approved(store, "ec", ctx)
    assert item["outcome_evidence"] == {
        "required_clean_readings": 3, "watched_labels": ["high_ec"], "readings_seen": 0, "clean_streak": 0,
        "untrusted_readings": 0, "last_sample_time": None, "resolved_sample_time": None}
    observe(store, 5, "other")
    observe(store, 6, None)
    for minute in (7, 8, 9):
        observe(store, minute, "node")
    status, evidence = outcome(store, item)
    assert status == "confirmed"
    assert "last_sample_by_device" not in evidence and "clean_streak_devices" not in evidence
    assert evidence["last_sample_time"] == (T0 + timedelta(minutes=9)).isoformat()


def test_empty_sources_are_the_same_as_none(store):
    item = approved(store, "ec", context(sources={}))
    observe(store, 5, "climate-1")
    assert outcome(store, item)[1]["readings_seen"] == 1  # farm and zone only, like any suggestion without a device


def test_the_card_carries_sources_only_when_the_context_has_them():
    with_sources = suggestion_to_advice_card({"id": "1", "action": "review", "message": "m", "status": "pending",
                                              "context": context()})
    assert with_sources["evidence"]["sources"] == SOURCES
    without = suggestion_to_advice_card({"id": "2", "action": "review", "message": "m", "status": "pending",
                                         "context": {"farm_id": "farm", "zone_id": "zone"}})
    assert "sources" not in without["evidence"]
    empty = suggestion_to_advice_card({"id": "3", "action": "review", "message": "m", "status": "pending",
                                       "context": {"sources": {}}})
    assert "sources" not in empty["evidence"]


def test_sources_travel_through_the_evaluate_route_into_the_card():
    client = TestClient(automation_main.app)
    automation_main.suggestion_store.clear()
    response = client.post("/v1/automation/evaluate", json={"risk_labels": ["high_ec"], "context": context()})
    assert response.status_code == 200
    cards = client.get("/v1/automation/advice-cards").json()["cards"]
    assert cards and cards[0]["evidence"]["sources"] == SOURCES
    assert json.loads(json.dumps(cards[0]))["evidence"]["farm_id"] == "farm"
    automation_main.suggestion_store.clear()
