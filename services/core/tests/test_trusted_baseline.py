import ast
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.outcome_feed as feed_module
from app import trusted_baseline as tb
from app.config import settings
from app.main import app
from app.outcome_feed import outcome_feed
from app.store import event_store, SensorEventStore

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def series(values, vetoed=(), step_s=30):
    """One field's readings at 30 s steps; `vetoed` are the indexes the pipeline vetoed."""
    return [{"timestamp": T0 + timedelta(seconds=step_s * i), "value": v, "vetoed": i in vetoed}
            for i, v in enumerate(values)]


def test_module_is_stdlib_only_so_the_scorer_can_load_it_by_path():
    tree = ast.parse(Path(tb.__file__).read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert imported <= {"__future__", "math", "statistics", "datetime", "typing"}


def test_median_ignores_vetoed_readings_and_needs_min_n():
    readings = series([6.0, 6.1, 6.0, 9.0, 9.0, 6.1, 6.0, 6.1, 6.0], vetoed={3, 4})
    now = T0 + timedelta(seconds=300)
    stats = tb.trusted_stats(readings, "ph", now, window_s=7200, min_n=6)
    assert stats["median"] == pytest.approx(6.0) and stats["n"] == 7 and stats["window_s"] == 7200
    assert tb.trusted_stats(readings, "ph", now, 7200, min_n=8) is None  # only 7 trusted
    assert tb.trusted_stats([], "ph", now, 7200, 6) is None
    assert tb.trusted_stats(series([1.0, 2.0]), "ph", now, 7200, 6) is None


def test_window_runs_back_from_the_newest_trusted_reading_so_a_long_fault_keeps_its_reference():
    # 20 trusted readings, then 4 hours of vetoed ones: the reference is still the trusted level.
    trusted = series([2.0 + 0.01 * (i % 3) for i in range(20)])
    faulty = [{"timestamp": T0 + timedelta(seconds=30 * (20 + i)), "value": 5.0, "vetoed": True} for i in range(480)]
    stats = tb.trusted_stats(trusted + faulty, "ec_ms_cm", T0 + timedelta(hours=4), window_s=7200, min_n=6)
    assert stats["median"] == pytest.approx(2.01) and stats["n"] == 20
    # Only trusted readings within the window of the newest one count.
    old = series([9.0] * 10, step_s=60)
    recent = [{"timestamp": T0 + timedelta(hours=3, seconds=30 * i), "value": 2.0, "vetoed": False} for i in range(8)]
    stats = tb.trusted_stats(old + recent, "ec_ms_cm", T0 + timedelta(hours=4), window_s=7200, min_n=6)
    assert stats["median"] == 2.0 and stats["n"] == 8


def test_last_change_is_the_start_of_the_identical_run_over_all_readings():
    readings = series([5.0, 5.1, 5.2, 5.3, 5.3, 5.3, 5.3, 5.3], vetoed={5, 6, 7})  # the frozen ones were vetoed
    stats = tb.trusted_stats(readings, "air_temperature_c", T0 + timedelta(hours=1), 7200, 3)
    assert stats["last_change_at"] == (T0 + timedelta(seconds=90)).isoformat()  # reading 3 starts the run of 5.3
    assert tb.trusted_stats(series([4.0] * 8), "air_temperature_c", T0 + timedelta(hours=1), 7200, 3)[
        "last_change_at"] == T0.isoformat()  # never changed since the first reading


def test_calibration_resets_the_reference_and_the_run():
    readings = series([6.0] * 10 + [7.5] * 10, vetoed=set(range(10, 20)))
    after = T0 + timedelta(seconds=30 * 12)
    assert tb.trusted_stats(readings, "ph", T0 + timedelta(hours=1), 7200, 6)["median"] == 6.0
    assert tb.trusted_stats(readings, "ph", T0 + timedelta(hours=1), 7200, 6, calibrated_after=after) is None
    confirmed = series([6.0] * 10 + [7.5] * 10, vetoed=set(range(10, 12)))  # trusted again after the calibration
    stats = tb.trusted_stats(confirmed, "ph", T0 + timedelta(hours=1), 7200, 6, calibrated_after=after)
    assert stats["median"] == 7.5 and stats["n"] == 8
    assert stats["last_change_at"] == after.isoformat()  # a frozen run does not count from before the calibration


def test_readings_after_now_and_bad_values_are_ignored():
    readings = series([6.0, 6.0, 6.0, 6.0, 6.0, 6.0, None, "x", True, 99.0])
    stats = tb.trusted_stats(readings, "ph", T0 + timedelta(seconds=150), 7200, 6)
    assert stats["median"] == 6.0 and stats["n"] == 6


def test_stream_baseline_per_field_with_vetoes_aliases_and_calibrations():
    prior = []
    for i in range(10):
        prior.append({"timestamp": (T0 + timedelta(seconds=30 * i)).isoformat().replace("+00:00", "Z"),
                      "ph": 6.0 + 0.01 * i, "ec_ms_cm": 2.5, "soil_moisture_pct": 55.0, "substrate_moisture_pct": 55.0,
                      "humidity_pct": None, "vetoed_fields": ["substrate_moisture_pct"] if i < 5 else []})
    now = T0 + timedelta(minutes=10)
    out = tb.stream_baseline(prior, [], now, 7200, 5)
    assert set(out) == {"ph", "ec_ms_cm", "soil_moisture_pct", "substrate_moisture_pct"}  # humidity has no readings
    assert out["ph"]["n"] == 10 and out["soil_moisture_pct"]["n"] == 5  # a veto on either moisture name is both
    calibrated = tb.stream_baseline(prior, [{"measurement": "ec_ms_cm", "performed_at": (T0 + timedelta(seconds=120)).isoformat()}],
                                    now, 7200, 6)
    assert calibrated["ec_ms_cm"]["n"] == 6 and calibrated["ph"]["n"] == 10  # only that probe was reset
    moisture = tb.stream_baseline(prior, [{"measurement": "soil_moisture_pct", "performed_at": T0.isoformat()}], now, 7200, 6)
    assert "soil_moisture_pct" not in moisture and "substrate_moisture_pct" not in moisture  # 5 trusted, 6 needed


# --- Core: the outcome feed builds the reference from stored readings and the trust it recorded ----------

ROUTER = "http://router.test"
AUTOMATION = "http://automation.test"


@pytest.fixture(autouse=True)
def clear_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "test.db")
    SensorEventStore(db_path=event_store._db_path)
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def feed(monkeypatch):
    """The feed with the router faked: it vetoes `ph` for readings listed in `vetoes`."""
    monkeypatch.setattr(settings, "model_router_url", ROUTER)
    monkeypatch.setattr(settings, "automation_engine_url", AUTOMATION)
    monkeypatch.setattr(settings, "trust_baseline_min_n", 3)
    monkeypatch.setattr(outcome_feed, "dropped", 0)
    state = {"calls": [], "vetoes": set()}

    def fake_post(base_url, path, body):
        state["calls"].append((path, body))
        if path != "/v1/pipeline/evaluate":
            return {}
        vetoed = ["ph"] if tb.parse_time(body["sensor"]["timestamp"]) in state["vetoes"] else []
        return {"trust_gate": {"trust_verdict": "partial" if vetoed else "trusted", "vetoed_fields": vetoed},
                "sensor_quality": {}, "water_irrigation": {}, "nutrient_ph_ec": {}, "crop_risk": {}}

    monkeypatch.setattr(feed_module, "_post", fake_post)
    return state


def reading(index, **updates):
    stamp = datetime.now(timezone.utc) - timedelta(seconds=300 - 10 * index)
    return {"device_id": "node", "farm_id": "farm", "zone_id": "a", "crop": "tomato", "growth_stage": "flowering",
            "air_temperature_c": 25.0, "humidity_pct": 60.0, "ec_ms_cm": 2.0, "ph": 6.0, "soil_moisture_pct": 40.0,
            "timestamp": stamp.isoformat(), **updates}


def send(client, feed, body):
    seen = sum(1 for path, _ in feed["calls"] if path == "/v1/pipeline/evaluate")
    assert client.post("/v1/sensors/events", json=body).status_code == 201
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if sum(1 for path, _ in feed["calls"] if path == "/v1/pipeline/evaluate") > seen and \
                sum(1 for path, _ in feed["calls"] if path == "/v1/automation/alerts/observe") > seen:
            return feed["calls"][-2][1]
        time.sleep(0.02)
    raise AssertionError("the feed did not process the reading")


def test_feed_sends_the_trusted_reference_and_records_each_verdict(client, feed):
    bodies = [reading(i, ph=6.0 + (0.5 if i in (4, 5) else 0)) for i in range(8)]
    feed["vetoes"] = {tb.parse_time(bodies[4]["timestamp"]), tb.parse_time(bodies[5]["timestamp"])}
    sent = [send(client, feed, body) for body in bodies]
    assert "stream_baseline" not in sent[0] and "stream_baseline" not in sent[2]  # fewer than min_n trusted readings
    assert sent[3]["stream_baseline"]["ph"]["median"] == 6.0 and sent[3]["stream_baseline"]["ph"]["n"] == 3
    # The vetoed readings (6.5) never reach the reference; later readings still see the old level.
    assert sent[7]["stream_baseline"]["ph"]["median"] == 6.0 and sent[7]["stream_baseline"]["ph"]["n"] == 5
    assert tb.parse_time(sent[7]["stream_baseline"]["ec_ms_cm"]["last_change_at"]) == tb.parse_time(bodies[0]["timestamp"])
    with event_store._connect() as db:
        verdicts = {r["sample_time"]: (r["trust_verdict"], r["vetoed_fields"])
                    for r in db.execute("SELECT * FROM event_trust")}
    assert len(verdicts) == 8 and sorted(v for v in verdicts.values() if v[0] == "partial") == [("partial", '["ph"]')] * 2


def test_a_calibration_resets_the_reference_for_that_probe(client, feed):
    first = [reading(i, ph=6.0) for i in range(4)]
    feed["vetoes"] = set()
    for body in first:
        send(client, feed, body)
    shifted = [reading(4 + i, ph=7.5) for i in range(5)]
    feed["vetoes"] = {tb.parse_time(b["timestamp"]) for b in shifted}
    for body in shifted:
        sent = send(client, feed, body)
    assert sent["stream_baseline"]["ph"]["median"] == 6.0  # still the trusted level
    calibration = {"device_id": "node", "farm_id": "farm", "zone_id": "a", "sensor_id": "ph", "measurement": "ph",
                   "method": "test", "points": [{"reference": 7.5, "raw": 7.5}], "performed_at": shifted[3]["timestamp"]}
    assert client.post("/v1/sensors/calibrations", json=calibration).status_code == 201
    feed["vetoes"] = set()
    sent = send(client, feed, reading(9, ph=7.5))
    assert "ph" not in sent.get("stream_baseline", {})  # nothing trusted since the calibration yet
    assert sent["stream_baseline"]["ec_ms_cm"]["n"] >= 3  # other probes keep their reference
    for i in range(10, 13):
        sent = send(client, feed, reading(i, ph=7.5))
    assert sent["stream_baseline"]["ph"]["median"] == 7.5


def test_readings_without_a_trust_record_count_as_not_vetoed(client, feed):
    for i in range(4):
        send(client, feed, reading(i))
    with event_store._connect() as db:
        db.execute("DELETE FROM event_trust")  # as if stored before trust was recorded
    sent = send(client, feed, reading(4))
    assert sent["stream_baseline"]["ph"]["n"] == 4


def test_old_database_gets_the_trust_table(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE sensor_events (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL,
            payload TEXT NOT NULL, farm_id TEXT, zone_id TEXT, device_id TEXT, received_at TEXT)""")
    store = SensorEventStore(db_path=path)
    with store._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM event_trust").fetchone()[0] == 0


def test_a_calibration_after_the_reading_does_not_apply_to_it():
    prior = [{"timestamp": T0 + timedelta(seconds=30 * i), "ph": 6.0, "vetoed_fields": []} for i in range(10)]
    later = [{"measurement": "ph", "performed_at": T0 + timedelta(minutes=30)}]
    assert tb.stream_baseline(prior, later, T0 + timedelta(minutes=6), 7200, 6)["ph"]["n"] == 10
    assert "ph" not in tb.stream_baseline(prior, later, T0 + timedelta(minutes=31), 7200, 6)


def test_reference_lapses_after_max_age_unless_it_is_zero():
    trusted = series([2.0 + 0.01 * (i % 3) for i in range(20)])
    faulty = [{"timestamp": T0 + timedelta(seconds=30 * (20 + i)), "value": 5.0, "vetoed": True} for i in range(600)]
    readings = trusted + faulty
    # The newest trusted reading is at 9.5 min; the reference lasts 2 h from there.
    assert tb.trusted_stats(readings, "ec_ms_cm", T0 + timedelta(minutes=100), 7200, 6, max_age_s=7200)["median"] == 2.01
    assert tb.trusted_stats(readings, "ec_ms_cm", T0 + timedelta(minutes=135), 7200, 6, max_age_s=7200) is None
    assert tb.trusted_stats(readings, "ec_ms_cm", T0 + timedelta(minutes=135), 7200, 6)["median"] == 2.01
    prior = [{"timestamp": r["timestamp"], "ec_ms_cm": r["value"], "vetoed_fields": ["ec_ms_cm"] if r["vetoed"] else []}
             for r in readings]
    assert "ec_ms_cm" not in tb.stream_baseline(prior, [], T0 + timedelta(minutes=135), 7200, 6, 7200)
    assert "ec_ms_cm" in tb.stream_baseline(prior, [], T0 + timedelta(minutes=135), 7200, 6, None)


def test_stats_carry_the_spread_of_the_trusted_window():
    stats = tb.trusted_stats(series([6.0, 6.1, 6.2, 6.0, 6.1, 6.3, 6.0, 6.1, 6.2, 6.1, 9.0]), "ph", T0 + timedelta(hours=1), 7200, 6)
    assert stats["spread"] == pytest.approx(0.2, abs=0.11)  # 10th to 90th percentile: the outlier does not widen it much
    assert tb.trusted_stats(series([5.0] * 8), "ph", T0 + timedelta(hours=1), 7200, 6)["spread"] == 0.0


def test_default_never_lapses_a_probe_broken_for_six_hours_keeps_its_pre_fault_reference():
    assert tb.DEFAULT_MAX_AGE_S == 0 and settings.trust_baseline_max_age_s == 0  # "until calibration" is the default
    trusted = series([6.0 + 0.01 * (i % 3) for i in range(30)])  # 15 minutes of good readings
    faulty = [{"timestamp": T0 + timedelta(seconds=30 * (30 + i)), "value": 7.6, "vetoed": True} for i in range(2 * 6 * 60)]
    readings = trusted + faulty  # then six hours (every reading vetoed, including the last two hours)
    now = T0 + timedelta(hours=6, minutes=20)
    stats = tb.trusted_stats(readings, "ph", now, tb.DEFAULT_WINDOW_S, tb.DEFAULT_MIN_N)
    assert stats["median"] == pytest.approx(6.01) and stats["n"] == 30  # anchored at the newest trusted reading, not "now"
    prior = [{"timestamp": r["timestamp"], "ph": r["value"], "vetoed_fields": ["ph"] if r["vetoed"] else []} for r in readings]
    assert tb.stream_baseline(prior, [], now, tb.DEFAULT_WINDOW_S, tb.DEFAULT_MIN_N)["ph"]["median"] == pytest.approx(6.01)
    # The opt-in lapse is the only thing that lets go of it.
    assert "ph" not in tb.stream_baseline(prior, [], now, tb.DEFAULT_WINDOW_S, tb.DEFAULT_MIN_N, 2 * 3600)


def test_calibration_re_anchors_after_min_n_trusted_readings_at_the_new_level():
    old = [{"timestamp": T0 + timedelta(seconds=30 * i), "value": 6.0, "vetoed": False} for i in range(20)]
    broken = [{"timestamp": T0 + timedelta(seconds=30 * (20 + i)), "value": 7.6, "vetoed": True} for i in range(100)]
    calibrated = T0 + timedelta(seconds=30 * 120)
    def after(count):
        new = [{"timestamp": calibrated + timedelta(seconds=30 * i), "value": 7.6, "vetoed": False} for i in range(count)]
        return tb.trusted_stats(old + broken + new, "ph", calibrated + timedelta(seconds=30 * count), 7200, 6,
                                calibrated_after=calibrated)
    assert after(5) is None  # not enough readings since the calibration: the check is off, not stuck on the old level
    assert after(6)["median"] == 7.6 and after(6)["n"] == 6  # the reference is now the confirmed level


def test_feed_keeps_the_pre_fault_reference_through_a_six_hour_fault(client, feed, monkeypatch):
    """Ten-minute readings: 6 good, then 36 vetoed ones (six hours); the reference is still the good level."""
    now = datetime.now(timezone.utc)

    def at(minutes_ago, **updates):
        return {**reading(0), "timestamp": (now - timedelta(minutes=minutes_ago)).isoformat(), **updates}

    good = [at(450 - 10 * i, ph=6.0) for i in range(6)]
    faulty = [at(390 - 10 * i, ph=7.6) for i in range(36)]
    feed["vetoes"] = {tb.parse_time(b["timestamp"]) for b in faulty}
    for body in good + faulty:
        sent = send(client, feed, body)
    assert settings.trust_baseline_max_age_s == 0 and settings.trust_baseline_min_n == 3
    assert sent["stream_baseline"]["ph"]["median"] == 6.0 and sent["stream_baseline"]["ph"]["n"] == 6
    # A calibration at the new level and min_n readings after it end the flag.
    calibration = {"device_id": "node", "farm_id": "farm", "zone_id": "a", "sensor_id": "ph", "measurement": "ph",
                   "method": "test", "points": [{"reference": 7.6, "raw": 7.6}], "performed_at": (now - timedelta(minutes=30)).isoformat()}
    assert client.post("/v1/sensors/calibrations", json=calibration).status_code == 201
    feed["vetoes"] = set()
    for i in range(3):
        send(client, feed, at(20 - 5 * i, ph=7.6))
    sent = send(client, feed, at(1, ph=7.6))
    assert sent["stream_baseline"]["ph"]["median"] == 7.6 and sent["stream_baseline"]["ph"]["n"] == 3


# --- The stream's own habits: newest trusted reading, and how a pH/EC probe normally changes -----------------

def test_stats_carry_the_newest_trusted_reading():
    readings = series([6.0, 6.1, 6.0, 6.2, 6.1, 6.0, 6.1, 9.0, 9.0], vetoed={7, 8})
    stats = tb.trusted_stats(readings, "ph", T0 + timedelta(minutes=10), 7200, 6)
    assert stats["last_value"] == 6.1  # the vetoed 9.0 never becomes the reference
    assert tb.parse_time(stats["last_at"]) == T0 + timedelta(seconds=30 * 6)


def test_norm_describes_how_the_probe_changed_before_the_current_run():
    # 40 readings that change almost every step, then a frozen run: the norm covers only what came before it.
    moving = [6.0 + 0.01 * ((i * 7) % 5) for i in range(40)]
    readings = series(moving + [6.5] * 60)
    stats = tb.trusted_stats(readings, "ph", T0 + timedelta(hours=1), 7200, 6, norm_steps=tb.NORM_STEPS)
    assert stats["change_steps"] == 39 and stats["change_share"] > 0.9
    assert stats["longest_run_s"] <= 60  # at most a repeat or two
    assert tb.parse_time(stats["last_change_at"]) == T0 + timedelta(seconds=30 * 40)
    # Not asked for (the default): the keys are absent, nothing else changes.
    plain = tb.trusted_stats(readings, "ph", T0 + timedelta(hours=1), 7200, 6)
    assert "change_share" not in plain and plain["median"] == stats["median"]


def test_a_drain_probe_that_sits_still_has_a_low_change_share_and_a_long_hold():
    # Real drain pH: a handful of changes in many hours, each value held for ages.
    plateaus = [6.0] * 50 + [6.2] * 80 + [6.1] * 70 + [6.3] * 60
    stats = tb.trusted_stats(series(plateaus, step_s=300), "ph", T0 + timedelta(hours=40), 7200, 6, norm_steps=tb.NORM_STEPS)
    assert stats["change_share"] < 0.05
    assert stats["longest_run_s"] >= 300 * 70


def test_norm_skips_vetoed_readings_and_stops_at_a_calibration():
    moving = [6.0 + 0.01 * ((i * 7) % 5) for i in range(60)]
    readings = series(moving + [6.5] * 20, vetoed=set(range(30, 60)))  # half of what came before was vetoed
    stats = tb.trusted_stats(readings, "ph", T0 + timedelta(hours=1), 7200, 6, norm_steps=tb.NORM_STEPS)
    assert stats["change_steps"] == 29  # 30 trusted rows before the run -> 29 steps
    after = T0 + timedelta(seconds=30 * 50)  # a calibration inside the vetoed stretch
    cut = tb.trusted_stats(readings, "ph", T0 + timedelta(hours=1), 7200, 6, calibrated_after=after, norm_steps=tb.NORM_STEPS)
    assert cut["median"] == 6.5 and "change_share" not in cut  # only the frozen run counts after it: no norm yet


def test_norm_walk_is_bounded_by_norm_steps():
    readings = series([6.0 + 0.01 * (i % 2) for i in range(1000)])
    stats = tb.trusted_stats(readings, "ph", T0 + timedelta(hours=9), 7200, 6, norm_steps=50)
    assert stats["change_steps"] == 50 and stats["change_share"] == 1.0


def test_stream_baseline_adds_the_norm_to_ph_and_ec_only():
    prior = [{"timestamp": T0 + timedelta(seconds=30 * i), "ph": 6.0 + 0.01 * (i % 3), "ec_ms_cm": 2.5 + 0.01 * (i % 2),
              "air_temperature_c": 24.0 + 0.1 * (i % 4), "vetoed_fields": []} for i in range(40)]
    out = tb.stream_baseline(prior, [], T0 + timedelta(seconds=30 * 40))
    assert {"change_share", "change_steps", "longest_run_s", "last_value", "last_at"} <= set(out["ph"])
    assert {"change_share", "change_steps", "longest_run_s"} <= set(out["ec_ms_cm"])
    assert "last_value" in out["air_temperature_c"] and "change_share" not in out["air_temperature_c"]
