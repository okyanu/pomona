"""Multi-device zones, slice 1: Core's outcome feed with the real model-router and the real alert monitor
(docs/design/multi-device-zones.md 1.11, two-device feed test). The in-process engine runs the same scenarios in
scripts/tests/test_multi_device_engine.py.

The router runs in a subprocess of the model-router venv (its `app` package cannot share this process); the test is
skipped when that venv is not there. Simulated time: readings are stored and judged on a virtual clock.
"""
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
ROOT = SERVICE_DIR.parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]
sys.path.insert(0, str(ROOT / "examples" / "simulators"))

import fake_greenhouse as fg
import inprocess_pomona as engine
import app.outcome_feed as feed_module
import app.store as store_module
from app.config import settings
from app.outcome_feed import OutcomeFeed
from app.schemas import SensorEvent
from app.store import SensorEventStore, event_store

ROUTER_PYTHON = ROOT / "services" / "model-router" / ".venv" / "bin" / "python"
pytestmark = pytest.mark.skipif(not ROUTER_PYTHON.exists(), reason="needs the model-router venv")
BASE = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
TICKS = 240  # 2 hours at 30 s
SEED = 2  # a normal run of this seed raises nothing in zone A over the first 2 hours


@pytest.fixture(scope="module")
def router_url(tmp_path_factory):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    errors = tmp_path_factory.mktemp("router") / "stderr.log"
    with open(errors, "w") as stderr:
        process = subprocess.Popen([str(ROUTER_PYTHON), str(Path(__file__).with_name("router_vclock.py")), str(port)],
                                   stdout=subprocess.DEVNULL, stderr=stderr)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 120  # a loaded machine can take a while to import the router
        while True:
            try:
                urllib.request.urlopen(url + "/health", timeout=1).read()
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    reason = f"exited with {process.returncode}" if process.poll() is not None else "did not answer in 120 s"
                    pytest.fail(f"the model-router {reason}; stderr tail:\n" + errors.read_text()[-2000:])
                time.sleep(0.2)
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


@pytest.fixture(scope="module")
def readings():
    state = {"n": 0}

    def clock():
        value = BASE + timedelta(seconds=30 * state["n"])
        state["n"] += 1
        return value

    sim = fg.Simulation(seed=SEED, clock=clock)
    return [r.event for _ in range(TICKS) for r in sim.step() if r.truth["zone_id"] == "greenhouse-a" and r.event]


def split(event, offset=None, drop=()):
    common = {k: event[k] for k in ("farm_id", "zone_id", "crop", "growth_stage", "system_type", "timestamp", "schema_version")}
    climate = {**common, "device_id": "climate-1", "air_temperature_c": event["air_temperature_c"],
               "humidity_pct": event["humidity_pct"]}
    substrate = {**common, "device_id": "substrate-1", "ph": event["ph"], "ec_ms_cm": event["ec_ms_cm"],
                 "soil_moisture_pct": event["soil_moisture_pct"], "substrate_moisture_pct": event["substrate_moisture_pct"]}
    if offset is not None:
        substrate["air_temperature_c"] = round(event["air_temperature_c"] + offset, 2)
    for name in drop:
        substrate.pop(name, None)
    return [climate, substrate]


def run_feed(router_url, tmp_path, monkeypatch, packets):
    """Store each packet on a virtual clock and run Core's feed on it, with the real router and the real alert monitor.
    Returns (per-packet [(device_id, labels, trust, requested device_fields)], the monitor)."""
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "multi.db")
    SensorEventStore(db_path=event_store._db_path)
    clock = {"now": BASE}
    monkeypatch.setattr(store_module, "utc_now", lambda: clock["now"])
    monkeypatch.setattr(settings, "model_router_url", router_url)
    monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
    rules = engine.load_rules()
    defaults = engine.alert_defaults()
    alerts = engine.load_module("pomona_alerts", engine.AUTOMATION_APP / "alerts.py")
    monitor = alerts.AlertMonitor(rules, defaults[0], defaults[1], db_path=None)
    real_post = feed_module._post
    seen = []

    def post(base_url, path, body):
        if path == "/v1/pipeline/evaluate":
            result = real_post(router_url, path, body)
            seen.append((body["sensor"]["device_id"], engine.pipeline_risk_labels(result), result["trust_gate"]["trust_verdict"],
                         body.get("device_fields")))
            return result
        monitor.observe(body["farm_id"], body["zone_id"], body["device_id"], engine.parse_ts(body["sample_time"]),
                        body["risk_labels"])
        return {}

    monkeypatch.setattr(feed_module, "_post", post)
    feed = OutcomeFeed(event_store, queue_size=5)
    for packet in packets:
        clock["now"] = engine.parse_ts(packet["timestamp"]) + timedelta(seconds=1)
        event = SensorEvent.model_validate(packet)
        assert event_store.add(event)
        feed._process(event)
    return seen, monitor


def test_two_devices_give_no_missing_labels_alerts_or_flags(router_url, readings, tmp_path, monkeypatch):
    seen, monitor = run_feed(router_url, tmp_path, monkeypatch, [p for e in readings for p in split(e)])
    assert len(seen) == 2 * TICKS
    assert seen[0][3] is None  # the zone's very first packet is judged before it has a second device
    judged = seen[1:]
    assert all(fields for *_, fields in judged)  # device_fields sent from the second packet on
    assert [labels for _, labels, _, _ in judged if labels] == []
    assert all(trust == "trusted" for _, _, trust, _ in judged)
    assert monitor.states() == []


def test_the_same_with_a_constant_offset_between_two_air_probes(router_url, readings, tmp_path, monkeypatch):
    seen, monitor = run_feed(router_url, tmp_path, monkeypatch, [p for e in readings for p in split(e, offset=1.5)])
    assert [labels for _, labels, _, _ in seen[1:] if labels] == []  # no noise flag: each device has its own history
    assert monitor.states() == []


def test_ec_disappearing_from_the_substrate_device_alerts_that_device_only(router_url, readings, tmp_path, monkeypatch):
    packets = []
    for tick, event in enumerate(readings):
        packets += split(event, drop=("ec_ms_cm",) if tick >= 180 else ())
    seen, monitor = run_feed(router_url, tmp_path, monkeypatch, packets)
    assert [labels for _, labels, _, _ in seen[1:2 * 180] if labels] == []
    after = seen[2 * 180:]
    assert all("missing_ec" in labels for device, labels, _, _ in after if device == "substrate-1")
    assert not [labels for device, labels, _, _ in after if device == "climate-1" and labels]
    assert {(s["rule_id"], s["device_id"]) for s in monitor.states()} == {("sensor_check", "substrate-1")}
