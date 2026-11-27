"""Slow-drift pair check, zone view while probes disagree (docs/design/slow-drift-pair-check.md Design 4b): the
`event_trust.pair_fields` column, the feed writing it, and the zone snapshot's `disagree` mark."""
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.outcome_feed as feed_module
import app.store as store_module
from app.config import settings
from app.main import app
from app.outcome_feed import OutcomeFeed
from app.schemas import SensorEvent
from app.store import SensorEventStore, event_store

HUMIDITY, AIR = "humidity_pct", "air_temperature_c"
SOIL, SUBSTRATE = "soil_moisture_pct", "substrate_moisture_pct"
T0 = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=20)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(store_module, "utc_now", value)
    return value


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "view.db")
    SensorEventStore(db_path=event_store._db_path)


def packet(device, at, **fields):
    return SensorEvent.model_validate({"device_id": device, "farm_id": "farm", "zone_id": "a",
                                       "timestamp": at.isoformat(), **(fields or {HUMIDITY: 60.0})})


def send(clock, device, seconds, judge=None, pair_fields=None, **fields):
    """Store a live packet `seconds` after T0 (the clock moves there). `judge` (a list of vetoed fields) records its
    trust row, with `pair_fields` when given."""
    clock.now = T0 + timedelta(seconds=seconds)
    event = packet(device, clock.now, **fields)
    assert event_store.add(event)
    if judge is not None:
        event_store.add_trust(event, "trusted", judge, ["baseline_drift_possible"], ["pair check: text"], pair_fields)
    return event


def snap(stale_after_s=600):
    return event_store.zone_snapshot("farm", "a", stale_after_s)


def two_probes(clock, a_flags=None, b_flags=None, a_judged=True, b_judged=True, a_fields=None, b_fields=None):
    """A (first seen, so first in the stable order) and B, both with humidity unless told otherwise."""
    a_fields, b_fields = a_fields or {HUMIDITY: 60.0}, b_fields or {HUMIDITY: 55.0}
    send(clock, "A", 0, judge=[] if a_judged else None, pair_fields=a_flags, **a_fields)
    send(clock, "B", 30, judge=[] if b_judged else None, pair_fields=b_flags, **b_fields)
    return snap()


# --- the column and add_trust --------------------------------------------------------------------------------------

def test_add_trust_stores_a_sorted_json_list_and_null_for_none_or_empty(clock):
    columns = lambda: {r[1] for r in sqlite3.connect(event_store._db_path).execute("PRAGMA table_info(event_trust)")}
    assert "pair_fields" in columns()
    for n, given in enumerate([None, [], [HUMIDITY, AIR]]):
        event = send(clock, "A", n * 30)
        event_store.add_trust(event, "trusted", [], None, None, given)
    stored = [r[0] for r in sqlite3.connect(event_store._db_path).execute(
        "SELECT pair_fields FROM event_trust ORDER BY sample_time")]
    assert stored == [None, None, json.dumps([AIR, HUMIDITY])]


def test_an_existing_database_without_the_column_gets_it_added(tmp_path):
    path = tmp_path / "old.db"
    SensorEventStore(db_path=path)
    with sqlite3.connect(path) as db:
        db.execute("ALTER TABLE event_trust DROP COLUMN pair_fields")
        assert "pair_fields" not in {r[1] for r in db.execute("PRAGMA table_info(event_trust)")}
    SensorEventStore(db_path=path)
    with sqlite3.connect(path) as db:
        assert "pair_fields" in {r[1] for r in db.execute("PRAGMA table_info(event_trust)")}


def test_the_trust_row_reports_pair_fields_only_when_there_are_some(clock):
    result = two_probes(clock, a_flags=[HUMIDITY])
    trust = {d["device_id"]: d["trust"] for d in result["devices"]}
    assert trust["A"]["pair_fields"] == [HUMIDITY]
    assert "pair_fields" not in trust["B"]
    assert set(trust["B"]) == {"status", "trust_verdict", "vetoed_fields", "data_quality_labels", "safe_next_checks"}


# --- the zone snapshot ---------------------------------------------------------------------------------------------

@pytest.mark.parametrize("flagged", ["A", "B"])
def test_a_flag_on_either_probe_marks_the_field_and_keeps_the_first_candidate(clock, flagged):
    result = two_probes(clock, **{f"{flagged.lower()}_flags": [HUMIDITY]})
    field = result["fields"][HUMIDITY]
    assert field["disagree"] is True
    assert (field["device_id"], field["value"]) == ("A", 60.0)
    assert [(o["device_id"], o["value"]) for o in field["others"]] == [("B", 55.0)]


def test_the_chosen_value_does_not_switch_even_when_the_first_probe_vetoes_the_field(clock):
    send(clock, "A", 0, judge=[HUMIDITY], pair_fields=[HUMIDITY], **{HUMIDITY: 60.0})
    send(clock, "B", 30, judge=[], **{HUMIDITY: 55.0})
    field = snap()["fields"][HUMIDITY]
    assert field["disagree"] is True and field["device_id"] == "A"
    assert field["others"][0]["vetoed"] is False


def test_the_mark_clears_when_no_probe_lists_the_field(clock):
    assert two_probes(clock, a_flags=[HUMIDITY])["fields"][HUMIDITY]["disagree"] is True
    # the next packets of both probes are judged without a flag
    send(clock, "A", 60, judge=[], **{HUMIDITY: 60.0})
    send(clock, "B", 90, judge=[], **{HUMIDITY: 55.0})
    assert "disagree" not in snap()["fields"][HUMIDITY]


def test_a_flag_on_another_field_does_not_mark_this_one(clock):
    send(clock, "A", 0, judge=[], pair_fields=[AIR], **{AIR: 20.0, HUMIDITY: 60.0})
    send(clock, "B", 30, judge=[], **{AIR: 21.0, HUMIDITY: 55.0})
    fields = snap()["fields"]
    assert fields[AIR]["disagree"] is True and "disagree" not in fields[HUMIDITY]


@pytest.mark.parametrize("flagged, name", [("A", SOIL), ("A", SUBSTRATE), ("B", SOIL), ("B", SUBSTRATE)])
def test_the_alias_case_a_flag_under_either_moisture_name_marks_both_fields(clock, flagged, name):
    # slow_drift.json: one probe publishes soil_moisture_pct, its partner substrate_moisture_pct
    result = two_probes(clock, a_fields={SOIL: 40.0}, b_fields={SUBSTRATE: 35.0}, **{f"{flagged.lower()}_flags": [name]})
    assert result["fields"][SOIL]["disagree"] is True and result["fields"][SOIL]["device_id"] == "A"
    assert result["fields"][SUBSTRATE]["disagree"] is True and result["fields"][SUBSTRATE]["device_id"] == "B"


def test_the_alias_flag_does_not_mark_a_field_no_live_probe_carries_under_that_name(clock):
    # the flagging probe carries humidity too, but the flag is on moisture: humidity stays unmarked
    send(clock, "A", 0, judge=[], pair_fields=[SOIL], **{SOIL: 40.0, HUMIDITY: 60.0})
    send(clock, "B", 30, judge=[], **{SUBSTRATE: 35.0, HUMIDITY: 55.0})
    fields = snap()["fields"]
    assert fields[SOIL]["disagree"] and fields[SUBSTRATE]["disagree"] and "disagree" not in fields[HUMIDITY]


def test_a_stale_probes_row_does_not_count(clock):
    send(clock, "A", 0, judge=[], pair_fields=[HUMIDITY], **{HUMIDITY: 60.0})
    send(clock, "B", 500, judge=[], **{HUMIDITY: 55.0})
    result = snap(stale_after_s=60)  # A's reading is 500 s old at B's time: stale
    assert [d["stale"] for d in result["devices"]] == [True, False]
    assert "disagree" not in result["fields"][HUMIDITY] and result["fields"][HUMIDITY]["device_id"] == "B"


def test_a_pending_row_does_not_count(clock):
    result = two_probes(clock, a_flags=[HUMIDITY], a_judged=False)  # the flag is on a row that is not there
    assert result["devices"][0]["trust"] == {"status": "pending"}
    assert "disagree" not in result["fields"][HUMIDITY]


def test_a_flag_on_an_older_packet_does_not_count_only_the_latest_row_does(clock):
    send(clock, "A", 0, judge=[], pair_fields=[HUMIDITY], **{HUMIDITY: 60.0})
    send(clock, "A", 30, judge=[], **{HUMIDITY: 60.0})
    send(clock, "B", 60, judge=[], **{HUMIDITY: 55.0})
    assert "disagree" not in snap()["fields"][HUMIDITY]


def test_no_pair_fields_anywhere_leaves_the_snapshot_byte_identical(clock):
    result = two_probes(clock)
    assert "disagree" not in result["fields"][HUMIDITY]
    assert all("pair_fields" not in d["trust"] for d in result["devices"])
    # the same rows written without the new argument give the same JSON
    first = json.dumps(result, sort_keys=True)
    event_store._db_path.unlink()
    SensorEventStore(db_path=event_store._db_path)
    send(clock, "A", 0, judge=[], **{HUMIDITY: 60.0})
    send(clock, "B", 30, judge=[], **{HUMIDITY: 55.0})
    assert json.dumps(snap(), sort_keys=True) == first


# --- the HTTP endpoint (the dashboard reads this answer, not the store) --------------------------------------------

def get_snapshot(stale_after_s=600):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/v1/sensors/zone-snapshot",
                              params={"farm_id": "farm", "zone_id": "a", "stale_after_s": stale_after_s})
    assert response.status_code == 200
    return response.json()


def test_the_endpoint_answers_disagree_and_the_device_pair_fields_when_probes_disagree(clock):
    two_probes(clock, a_flags=[HUMIDITY])
    body = get_snapshot()
    assert body["fields"][HUMIDITY]["disagree"] is True
    assert body["fields"][HUMIDITY]["device_id"] == "A"
    trust = {d["device_id"]: d["trust"] for d in body["devices"]}
    assert trust["A"]["pair_fields"] == [HUMIDITY]
    assert "pair_fields" not in trust["B"]


def test_the_endpoint_leaves_disagree_and_pair_fields_out_when_nothing_is_flagged(clock):
    two_probes(clock)
    body = get_snapshot()
    assert set(body["fields"][HUMIDITY]) == {"value", "device_id", "sample_time", "age_s", "others"}
    assert all("pair_fields" not in d["trust"] for d in body["devices"])


# --- the feed ------------------------------------------------------------------------------------------------------

@pytest.fixture
def feed(monkeypatch):
    monkeypatch.setattr(settings, "model_router_url", "http://router.test")
    monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
    harness = SimpleNamespace(quality={}, feed=OutcomeFeed(event_store, queue_size=5))

    def post(base_url, path, body):
        if path != "/v1/pipeline/evaluate":
            return {}
        return {"trust_gate": {"trust_verdict": "trusted", "vetoed_fields": []}, "sensor_quality": harness.quality}

    monkeypatch.setattr(feed_module, "_post", post)
    return harness


def stored_pair_fields(event):
    with sqlite3.connect(event_store._db_path) as db:
        return db.execute("SELECT pair_fields FROM event_trust WHERE device_id=? AND sample_time=?",
                          (event.device_id, event.timestamp.isoformat())).fetchone()[0]


def test_the_feed_writes_pair_fields_from_the_routers_result_and_null_when_the_key_is_absent(feed, clock):
    feed.quality = {"data_quality_labels": ["baseline_drift_possible"], "safe_next_checks": ["pair check: text"],
                    "pair_disagreement_fields": [HUMIDITY, AIR]}
    flagged = send(clock, "A", 0, **{HUMIDITY: 60.0})
    feed.feed._process(flagged)
    assert stored_pair_fields(flagged) == json.dumps([AIR, HUMIDITY])
    feed.quality = {"data_quality_labels": [], "safe_next_checks": []}
    clean = send(clock, "A", 30, **{HUMIDITY: 60.0})
    feed.feed._process(clean)
    assert stored_pair_fields(clean) is None


def test_the_flag_the_feed_wrote_reaches_the_zone_snapshot(feed, clock):
    feed.quality = {"pair_disagreement_fields": [HUMIDITY]}
    a = send(clock, "A", 0, **{HUMIDITY: 60.0})
    feed.feed._process(a)
    feed.quality = {}
    b = send(clock, "B", 30, **{HUMIDITY: 55.0})
    feed.feed._process(b)
    field = snap()["fields"][HUMIDITY]
    assert field["disagree"] is True and field["device_id"] == "A"
