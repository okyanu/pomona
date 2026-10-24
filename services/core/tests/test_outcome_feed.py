from datetime import datetime, timedelta, timezone
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.config import settings
from app.main import app
from app.mqtt_client import MqttIngestClient
from app.schemas import SensorEvent
from app.store import event_store, SensorEventStore
import app.outcome_feed as feed_module
from app.outcome_feed import OutcomeFeed, outcome_feed

ROUTER = "http://router.test"
AUTOMATION = "http://automation.test"
RESULT = {"sensor_quality": {"data_quality_labels": ["stuck_value", "noisy_signal_possible"]},
          "water_irrigation": {"irrigation_risk_labels": ["dry_substrate"]},
          "nutrient_ph_ec": {"nutrient_risk_labels": ["ph_high", "stuck_value"]},
          "crop_risk": {"risk_labels": []}}


@pytest.fixture(autouse=True)
def clear_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "test.db")
    SensorEventStore(db_path=event_store._db_path)
    monkeypatch.setattr(outcome_feed, "dropped", 0)
    yield


@pytest.fixture
def calls(monkeypatch):
    """Enable the feed with the HTTP sender replaced by a recorder."""
    monkeypatch.setattr(settings, "model_router_url", ROUTER)
    monkeypatch.setattr(settings, "automation_engine_url", AUTOMATION)
    recorded = []

    def fake_post(base_url, path, body):
        recorded.append((base_url, path, body))
        return RESULT if path == "/v1/pipeline/evaluate" else {}

    monkeypatch.setattr(feed_module, "_post", fake_post)
    return recorded


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def settle(seconds=0.4):
    time.sleep(seconds)


def payload(offset_seconds=0, **updates):
    return {"device_id": "node", "farm_id": "farm", "zone_id": "a", "crop": "tomato", "growth_stage": "flowering",
            "air_temperature_c": 25.0, "humidity_pct": 60.0, "ec_ms_cm": 2.0, "ph": 6.0, "soil_moisture_pct": 40.0,
            "timestamp": (datetime.now(timezone.utc) - timedelta(seconds=offset_seconds)).isoformat(), **updates}


def deliver(value, retained=False):
    MqttIngestClient()._on_message(None, None, SimpleNamespace(
        topic=f"pomona/{value['farm_id']}/{value['zone_id']}/sensor/{value['device_id']}/state",
        payload=json.dumps(value).encode(), retain=retained))


def test_new_reading_feeds_one_pipeline_call_then_one_observe_call(client, calls):
    body = payload(boot_id="b", sequence=1)
    assert client.post("/v1/sensors/events", json=body).status_code == 201
    assert wait_for(lambda: len(calls) >= 2)
    settle()
    assert [(url, path) for url, path, _ in calls] == [(ROUTER, "/v1/pipeline/evaluate"),
                                                         (AUTOMATION, "/v1/automation/alerts/observe")]
    pipeline, observe = calls[0][2], calls[1][2]
    assert pipeline["mode"] == "rules_only" and pipeline["actor"] == "core_feed" and pipeline["scenario_id"] == "core_feed"
    assert pipeline["proposed_command"] == {"action_type": "continue_monitoring"}
    assert pipeline["expected_fields"] == ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "soil_moisture_pct"]
    assert pipeline["history"] == []
    assert pipeline["farm_context"] == {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a",
                                        "weather": None, "zone_area_m2": None, "crop_kc": None, "npk_target": None}
    assert pipeline["sensor"]["device_id"] == "node" and "source" not in pipeline["sensor"]
    assert observe == {"farm_id": "farm", "zone_id": "a", "device_id": "node",
                       "sample_time": pipeline["sensor"]["timestamp"],
                       "risk_labels": ["stuck_value", "noisy_signal_possible", "dry_substrate", "ph_high"],
                       "data_quality_labels": ["stuck_value", "noisy_signal_possible"]}


def test_history_is_prior_only_for_the_same_zone(client, calls):
    first, other_zone, second = payload(30), payload(20, zone_id="b"), payload(10)
    for body in (first, other_zone, second):
        assert client.post("/v1/sensors/events", json=body).status_code == 201
        assert wait_for(lambda: len(calls) >= 2 * (1 + [first, other_zone, second].index(body)))
    pipelines = [body for _, path, body in calls if path == "/v1/pipeline/evaluate"]
    assert pipelines[2]["sensor"]["timestamp"].startswith(second["timestamp"][:19])
    history = pipelines[2]["history"]
    assert len(history) == 1 and history[0]["timestamp"].startswith(first["timestamp"][:19])
    assert not {"source", "received_at", "mqtt_retained"} & set(history[0])
    assert pipelines[1]["history"] == []


def test_mqtt_reading_feeds(client, calls):
    deliver(payload(boot_id="b", sequence=1))
    assert wait_for(lambda: len(calls) >= 2)


def test_duplicates_do_not_feed(client, calls):
    for body in (payload(boot_id="b", sequence=5), payload(boot_id="b", sequence=5)):
        client.post("/v1/sensors/events", json=body)
    same = payload()
    for _ in range(2):
        client.post("/v1/sensors/events", json=same)
    assert wait_for(lambda: len(calls) >= 4)
    settle()
    assert len(calls) == 4


def test_retained_mqtt_message_does_not_feed_even_when_promoted(client, calls):
    body = payload(boot_id="b", sequence=1)
    deliver(body, retained=True)
    assert event_store.count() == 1
    deliver(body)  # same reading arriving live promotes the stored row; it was not newly inserted
    settle()
    assert calls == []


def test_future_clock_and_stale_sequence_do_not_feed(client, calls):
    assert client.post("/v1/sensors/events", json=payload(-86400)).status_code == 201
    assert client.post("/v1/sensors/events", json=payload(boot_id="b", sequence=10)).status_code == 201
    assert wait_for(lambda: len(calls) >= 2)
    assert client.post("/v1/sensors/events", json=payload(-5, boot_id="b", sequence=9)).status_code == 201
    settle()
    assert len(calls) == 2
    assert calls[0][2]["sensor"]["sequence"] == 10


def test_observations_and_other_records_do_not_feed(client, calls):
    body = {"device_id": "node", "farm_id": "farm", "zone_id": "a", "sensor_id": "t", "measurement": "air_temperature_c",
            "unit": "C", "value": 24, "timestamp": datetime.now(timezone.utc).isoformat()}
    assert client.post("/v1/sensors/observations", json=body).status_code == 201
    settle()
    assert calls == []


def test_feed_is_disabled_when_urls_are_empty(client, monkeypatch):
    sent = []
    monkeypatch.setattr(feed_module, "_post", lambda *args: sent.append(args))
    for urls in (("", ""), (ROUTER, ""), ("", AUTOMATION)):
        monkeypatch.setattr(settings, "model_router_url", urls[0])
        monkeypatch.setattr(settings, "automation_engine_url", urls[1])
        assert outcome_feed.enabled is False
        assert client.post("/v1/sensors/events", json=payload()).status_code == 201
    settle()
    assert sent == [] and outcome_feed._queue.qsize() == 0


@pytest.mark.parametrize("failing", ["/v1/pipeline/evaluate", "/v1/automation/alerts/observe"])
def test_failing_downstream_never_breaks_ingest(client, monkeypatch, caplog, failing):
    monkeypatch.setattr(settings, "model_router_url", ROUTER)
    monkeypatch.setattr(settings, "automation_engine_url", AUTOMATION)
    seen = []

    def fake_post(base_url, path, body):
        seen.append(path)
        if path == failing:
            raise OSError("connection refused")
        return RESULT

    monkeypatch.setattr(feed_module, "_post", fake_post)
    with caplog.at_level("WARNING"):
        assert client.post("/v1/sensors/events", json=payload(10)).status_code == 201
        assert client.post("/v1/sensors/events", json=payload(5)).status_code == 201
        assert wait_for(lambda: len([p for p in seen if p == failing]) >= 2)  # the worker survives a failure
    assert wait_for(lambda: "outcome feed failed" in caplog.text)
    assert event_store.count() == 2


def test_full_queue_drops_without_blocking(monkeypatch):
    monkeypatch.setattr(settings, "model_router_url", ROUTER)
    monkeypatch.setattr(settings, "automation_engine_url", AUTOMATION)
    feed = OutcomeFeed(event_store, queue_size=2)  # no worker started: nothing drains the queue
    event = SensorEvent.model_validate(payload())
    started = time.monotonic()
    for _ in range(5):
        feed.submit(event)
    assert time.monotonic() - started < 1.0
    assert feed._queue.qsize() == 2 and feed.dropped == 3


def test_health_reports_dropped_readings(client, monkeypatch):
    monkeypatch.setattr(outcome_feed, "dropped", 7)
    assert client.get("/health").json()["outcome_feed_dropped"] == 7


def test_post_sends_json_over_http_and_rejects_other_schemes():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.headers["Content-Type"], json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            body = b'{"ok": true}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert feed_module._post(f"http://127.0.0.1:{server.server_port}/", "/x", {"a": 1}) == {"ok": True}
    finally:
        server.shutdown()
    assert received == [("/x", "application/json", {"a": 1})]
    with pytest.raises(ValueError):
        feed_module._post("file:///etc", "/passwd", {})


def test_history_is_relative_to_the_fed_reading_when_the_queue_backs_up(client, calls, monkeypatch):
    feed = OutcomeFeed(event_store, queue_size=50)  # no worker yet: readings pile up behind the first
    stamps = [payload(600 - 10 * i) for i in range(20)]  # 20 readings, oldest first
    fed = []
    for body in stamps:
        event = SensorEvent.model_validate(body)
        assert event_store.add(event)
        fed.append(event)
    other_zone = SensorEvent.model_validate(payload(595, zone_id="b"))
    event_store.add(other_zone)
    for event in (fed[3], fed[0], fed[19]):
        feed._process(event)
    pipelines = [body for _, path, body in calls if path == "/v1/pipeline/evaluate"]
    third, first, last = pipelines
    assert len(third["history"]) == 3
    assert [h["timestamp"] for h in third["history"]] == [e.model_dump(mode="json")["timestamp"] for e in fed[:3]]
    assert first["history"] == []
    assert [h["timestamp"] for h in last["history"]] == [e.model_dump(mode="json")["timestamp"] for e in fed[8:19]]
    assert len(last["history"]) == 11 and not {"source", "received_at", "mqtt_retained"} & set(last["history"][0])


def test_history_same_sample_time_uses_store_order(client, calls):
    feed = OutcomeFeed(event_store, queue_size=5)
    body = payload(30)
    first = SensorEvent.model_validate({**body, "device_id": "one"})
    second = SensorEvent.model_validate({**body, "device_id": "two"})
    event_store.add(first)
    event_store.add(second)
    feed._process(first)
    feed._process(second)
    pipelines = [b for _, path, b in calls if path == "/v1/pipeline/evaluate"]
    assert pipelines[0]["history"] == []
    assert [h["device_id"] for h in pipelines[1]["history"]] == ["one"]
