"""Multi-device zones, slice 2: the two-device check (docs/design/multi-device-zones-slice2.md "Done when").

Core's store and zone snapshot run in this process (the dashboard reaches them through an ASGI transport), the real
model-router runs in a subprocess of its own venv as in test_multi_device_feed.py, and the dashboard's own view functions
(`services/dashboard/app/main.py`, loaded under another module name because its `app` package would clash with Core's)
run on top. The automation side (outcomes, `detail`) is covered by its own suite, not here.
"""
import asyncio
import importlib.util
import json
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
ROOT = SERVICE_DIR.parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]
sys.path.insert(0, str(ROOT / "examples" / "simulators"))

import inprocess_pomona as engine
import app.outcome_feed as feed_module
import app.store as store_module
from app.config import settings
from app.main import app as core_app
from app.outcome_feed import OutcomeFeed
from app.schemas import SensorEvent
from app.store import SensorEventStore, event_store

ROUTER_PYTHON = ROOT / "services" / "model-router" / ".venv" / "bin" / "python"
pytestmark = pytest.mark.skipif(not ROUTER_PYTHON.exists(), reason="needs the model-router venv")
BASE = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
TICKS = 28  # 14 minutes at 30 s
# climate-1's humidity probe freezes from this tick. The history check stops flagging once the frozen run fills the whole
# 11-packet history (the persistent check needs Core's stream baseline), so the run ends while earlier readings are in it.
STUCK_FROM = 20


def load_dashboard():
    spec = importlib.util.spec_from_file_location("dashboard_main_under_test", ROOT / "services" / "dashboard" / "app" / "main.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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
        deadline = time.monotonic() + 120
        while True:
            try:
                urllib.request.urlopen(url + "/health", timeout=1).read()
                break
            except OSError:
                if process.poll() is not None or time.monotonic() > deadline:
                    pytest.fail("the model-router did not start; stderr tail:\n" + errors.read_text()[-2000:])
                time.sleep(0.2)
        yield url
    finally:
        process.terminate()
        process.wait(timeout=10)


def packets(moisture=True, stuck=False, last_substrate_pending=False):
    """Two devices every 30 s: climate-1 (air, humidity) and substrate-1 (pH, EC and optionally moisture)."""
    out = []
    for tick in range(TICKS):
        at = (BASE + timedelta(seconds=30 * tick)).isoformat()
        humidity = 55.0 if stuck and tick >= STUCK_FROM else 58.0 + (tick * 7 % 11) / 5
        out.append({"device_id": "climate-1", "farm_id": "farm", "zone_id": "a", "timestamp": at,
                    "air_temperature_c": 24.0 + (tick * 5 % 9) / 10, "humidity_pct": humidity})
        substrate = {"device_id": "substrate-1", "farm_id": "farm", "zone_id": "a", "timestamp": at,
                     "ph": 6.0 + (tick * 3 % 7) / 50, "ec_ms_cm": 2.0 + (tick * 5 % 7) / 50}
        if moisture:
            substrate["substrate_moisture_pct"] = 40.0 + (tick * 7 % 11) / 10
        out.append(substrate)
    return out


class World:
    """Core (in process), the real router, a stub automation engine, and the dashboard on top of them."""

    def __init__(self, router_url, tmp_path, monkeypatch):
        self.dash = load_dashboard()
        self.router_url = router_url
        self.automation = []
        self.clock = {"now": BASE}
        monkeypatch.setattr(event_store, "_db_path", tmp_path / "zone.db")
        SensorEventStore(db_path=event_store._db_path)
        monkeypatch.setattr(store_module, "utc_now", lambda: self.clock["now"])
        monkeypatch.setattr(settings, "model_router_url", router_url)
        monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
        real_post = feed_module._post
        monkeypatch.setattr(feed_module, "_post", lambda base, path, body: real_post(router_url, path, body)
                            if path == "/v1/pipeline/evaluate" else {})
        real_client = httpx.AsyncClient
        dash, world = self.dash, self

        def automation_handler(request):
            world.automation.append((request.url.path, request.read().decode()))
            return httpx.Response(200, json={"suggestions": [], "events": [], "alerts": [], "ignored": False})

        def make_client(base_url="", timeout=None, **kwargs):
            if base_url == dash.settings.core_url:
                return real_client(transport=httpx.ASGITransport(app=core_app), base_url="http://core.test", timeout=timeout)
            if base_url == dash.settings.model_router_url:
                return real_client(base_url=base_url, timeout=timeout)
            return real_client(transport=httpx.MockTransport(automation_handler), base_url=base_url, timeout=timeout)

        monkeypatch.setattr(httpx, "AsyncClient", make_client)
        monkeypatch.setattr(dash.settings, "core_url", "http://core.test")
        monkeypatch.setattr(dash.settings, "model_router_url", router_url)
        monkeypatch.setattr(dash.settings, "automation_engine_url", "http://automation.test")
        monkeypatch.setattr(dash.settings, "zone_stale_after_s", 600)
        monkeypatch.setattr(dash, "utc_now", lambda: self.clock["now"])
        self.feed = OutcomeFeed(event_store, queue_size=5)

    def store(self, packet_list, judge=lambda packet: True):
        """Store each packet on the virtual clock; Core's feed (the real router) judges those `judge` says so."""
        for packet in packet_list:
            self.clock["now"] = engine.parse_ts(packet["timestamp"]) + timedelta(seconds=1)
            event = SensorEvent.model_validate(packet)
            assert event_store.add(event)
            if judge(packet):
                self.feed._process(event)

    def run(self, coroutine):
        self.dash.reset_zone_caches()
        return asyncio.run(coroutine)


@pytest.fixture
def world(router_url, tmp_path, monkeypatch):
    return World(router_url, tmp_path, monkeypatch)


def test_a_stuck_humidity_probe_shows_in_the_zone_view_pipeline_and_the_evaluate_labels(world):
    world.store(packets(stuck=True))
    dash = world.dash
    # Core's own check of climate-1 (its history) wrote the labels with the verdict
    snapshot = world.run(dash._zone_snapshot("farm", "a"))
    climate = next(d for d in snapshot["devices"] if d["device_id"] == "climate-1")
    assert climate["trust"]["status"] == "judged" and "humidity_pct" in climate["trust"]["vetoed_fields"]
    assert "stuck_value" in climate["trust"]["data_quality_labels"]
    # the zone view: humidity from the stuck probe (the only humidity device), vetoed
    assert snapshot["sources"]["humidity_pct"] == ["climate-1"] and snapshot["sensor"]["ph"] is not None

    pipeline = world.run(dash.pipeline())
    assert pipeline.available and pipeline.dashboard_judged == []  # every device was judged by Core's feed
    result = pipeline.result
    assert "stuck_value" in result["sensor_quality"]["data_quality_labels"]
    assert "humidity_pct" in result["trust_gate"]["vetoed_fields"]
    assert result["trust_gate"]["trust_verdict"] != "trusted"
    assert result["sensor_quality"]["from_device_checks"]["vetoed_fields"] == ["humidity_pct"]
    assert "device_id" not in pipeline.sensor_snapshot
    assert pipeline.sources == snapshot["sources"]

    world.automation.clear()
    evaluated = world.run(dash.automation_evaluate())
    assert evaluated.available
    (path, raw), = [item for item in world.automation if item[0] == "/v1/automation/evaluate"]
    body = json.loads(raw)
    assert "stuck_value" in body["risk_labels"] and body["context"]["sources"] == snapshot["sources"]
    assert "humidity_pct" in body["context"]["vetoed_fields"]
    rules = engine.load_rules()
    assert any(rule["id"] == "sensor_check" and set(rule["match_any_labels"]) & set(body["risk_labels"]) for rule in rules)

    risk = world.run(dash.risk())
    assert risk.available and "stuck_value" in str(risk.result)  # the risk panel agrees with the trust line


def test_a_zone_without_a_moisture_probe_is_trusted_and_nothing_is_missing(world):
    world.store(packets(moisture=False))
    dash = world.dash
    pipeline = world.run(dash.pipeline())
    result = pipeline.result
    assert result["trust_gate"]["trust_verdict"] == "trusted"
    assert result["sensor_quality"]["missing_fields"] == [] and result["sensor_quality"]["data_quality_labels"] == []
    risk = world.run(dash.risk())
    assert risk.available and "missing_moisture" not in str(risk.result)


def test_a_device_core_has_not_judged_is_judged_by_the_dashboard_with_the_real_router(world):
    # Core's feed skips substrate-1's last packet: the device stays pending and the dashboard checks it itself.
    last = packets()[-1]
    assert last["device_id"] == "substrate-1"
    world.store(packets(), judge=lambda packet: not (packet["device_id"] == "substrate-1" and packet["timestamp"] == last["timestamp"]))
    dash = world.dash
    snapshot = world.run(dash._zone_snapshot("farm", "a"))
    assert next(d for d in snapshot["devices"] if d["device_id"] == "substrate-1")["trust"] == {"status": "pending"}
    pipeline = world.run(dash.pipeline())
    assert pipeline.available and pipeline.dashboard_judged == ["substrate-1"]
    assert pipeline.result["trust_gate"]["trust_verdict"] == "trusted"
    posted = [item for item in world.automation if item[0] == "/v1/automation/alerts/observe"]
    assert len(posted) == 1 and '"device_id":"substrate-1"' in posted[0][1].replace(" ", "")
