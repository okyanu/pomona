import asyncio
import sys
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient


SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

# Core and Dashboard both use an ``app`` package; isolate imports when the
# full multi-service test suite runs in one Python process.
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.main as dashboard_main


client = TestClient(dashboard_main.app)


def test_scope_is_forwarded_and_does_not_leak_between_requests(monkeypatch):
    calls = []
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, path, params=None):
            calls.append((path, dict(params or {})))
            scope = params or {}
            event = {"farm_id": scope.get("farm_id", "default"), "zone_id": scope.get("zone_id", "default"), "air_temperature_c": 24}
            return dashboard_main.httpx.Response(200, json={"events": [event], "devices": [], "observations": []}, request=dashboard_main.httpx.Request("GET", "http://core" + path))
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    for zone in ("a", "b"):
        query = {"farm_id": "farm", "zone_id": zone}
        assert client.get("/api/overview", params=query).json()["latest_event"]["zone_id"] == zone
        assert calls[-1][1] == {"farm_id": "farm", "zone_id": zone, "limit": 20}
        assert client.get("/api/devices", params=query).json()["available"]
        assert calls[-1][1] == query
        assert client.get("/api/probe-health", params=query).json()["available"]
        assert calls[-1] == ("/v1/sensors/probe-health", query)
        assert client.get("/api/history", params={**query, "kind": "observations", "offset": 100}).json()["available"]
        assert calls[-1] == ("/v1/sensors/observations", {**query, "limit": 100, "offset": 100})
        assert client.get("/api/history/export.csv", params=query).status_code == 200
        assert calls[-1][1] == {**query, "kind": "events", "limit": 100, "offset": 0}
    client.get("/api/overview")
    assert calls[-1][1] == {"limit": 20}
    assert client.get("/api/overview?farm_id=only").status_code == 422
    assert client.get("/api/history?offset=-1").status_code == 422
    assert client.get("/api/history?kind=secret").status_code == 422


def test_scoped_suggestions_hide_other_zones_and_reject_cross_zone_decision(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, path):
            rows = [{"id": z, "context": {"farm_id": "farm", "zone_id": z}} for z in ("a", "b")]
            rows.append({"id": "legacy", "context": {}})
            return dashboard_main.httpx.Response(200, json={"suggestions": rows}, request=dashboard_main.httpx.Request("GET", "http://automation" + path))
        async def post(self, *args, **kwargs):
            raise AssertionError("Cross-zone request must not reach automation")
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    query = {"farm_id": "farm", "zone_id": "a"}
    result = client.get("/api/automation", params=query).json()["result"]
    assert [s["id"] for s in result["suggestions"]] == ["a"]
    assert client.post("/api/automation/suggestions/b/approve", params=query).status_code == 404
    assert client.post("/api/automation/suggestions/legacy/reject", params=query).status_code == 404
    assert not client.get("/api/audit", params=query).json()["available"]


def test_dashboard_javascript_escapes_untrusted_values():
    """Execute the served script with hostile API fixtures, without a server."""
    html = client.get("/").text
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    result = subprocess.run(
        ["node", str(Path(__file__).with_name("check_rendering.cjs"))],
        input=script, text=True, capture_output=True, timeout=15,
    )
    assert result.returncode == 0, result.stderr


def test_pipeline_proxy_is_read_only_and_uses_latest_event(monkeypatch):
    event = {
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "crop": "tomato",
        "timestamp": "2026-07-20T10:00:00Z",
        "air_temperature_c": 33.0,
        "humidity_pct": 80.0,
        "ph": 5.2,
        "ec_ms_cm": 3.8,
        "soil_moisture_pct": 27.0,
        "source": "mqtt",
    }

    async def fake_overview():
        return dashboard_main.OverviewResponse(
            core_available=True,
            latest_event=event,
            recent_events=[event],
        )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "pipeline_id": "pipeline-test",
                "final_decision": {
                    "risk_level": "high",
                    "blocked_actions": ["direct_actuator_control"],
                    "human_review_required": True,
                },
            }

    class FakeClient:
        last_payload = None
        payloads = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json):
            FakeClient.payloads.append({"path": path, "json": json})
            if path == "/v1/pipeline/evaluate":
                FakeClient.last_payload = {"path": path, "json": json}
            return FakeResponse()

    monkeypatch.setattr(dashboard_main, "overview", fake_overview)
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    response = client.get("/api/pipeline")

    assert response.status_code == 200
    assert response.json()["result"]["pipeline_id"] == "pipeline-test"
    assert FakeClient.last_payload["path"] == "/v1/pipeline/evaluate"
    assert FakeClient.last_payload["json"]["proposed_command"] == {"action_type": "continue_monitoring"}
    assert FakeClient.last_payload["json"]["actor"] == "dashboard"
    assert "source" not in FakeClient.last_payload["json"]["sensor"]
    assert "expected_fields" not in FakeClient.last_payload["json"]  # the pipeline picks them from the system type
    # The reading's labels also go to the alert monitor (advisory state, never an actuator).
    observed = [p["json"] for p in FakeClient.payloads if p["path"] == "/v1/automation/alerts/observe"]
    assert observed == [{"farm_id": "demo-farm", "zone_id": "greenhouse-a", "device_id": None,
                         "sample_time": "2026-07-20T10:00:00Z", "risk_labels": [], "data_quality_labels": []}]


def test_risk_proxy_lets_the_router_choose_expected_fields(monkeypatch):
    event = {"farm_id": "demo-farm", "zone_id": "greenhouse-a", "crop": "tomato", "system_type": "hydroponic",
             "timestamp": "2026-07-20T10:00:00Z", "air_temperature_c": 22.0, "humidity_pct": 60.0, "ph": 5.9,
             "ec_ms_cm": 1.8}

    async def fake_overview():
        return dashboard_main.OverviewResponse(core_available=True, latest_event=event, recent_events=[event])

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"mode": "hybrid_guarded"}

    class FakeClient:
        payloads = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json):
            FakeClient.payloads.append({"path": path, "json": json})
            return FakeResponse()

    monkeypatch.setattr(dashboard_main, "overview", fake_overview)
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    response = client.get("/api/risk")

    assert response.status_code == 200 and response.json()["available"] is True
    assert FakeClient.payloads[0]["path"] == "/v1/reasoners/shared-chain"
    assert "expected_fields" not in FakeClient.payloads[0]["json"]


def test_pipeline_survives_alert_monitor_outage(monkeypatch):
    event = {"farm_id": "f", "zone_id": "z", "timestamp": "2026-07-20T10:00:00Z", "air_temperature_c": 24.0,
             "humidity_pct": 60.0, "ph": 6.0, "ec_ms_cm": 2.0, "soil_moisture_pct": 40.0}

    async def fake_overview():
        return dashboard_main.OverviewResponse(core_available=True, latest_event=event, recent_events=[event])

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"pipeline_id": "p", "crop_risk": {"risk_labels": ["high_ec"]}}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path, params=None):
            return dashboard_main.httpx.Response(200, json={"events": [event]},
                                                 request=dashboard_main.httpx.Request("GET", "http://core" + path))

        async def post(self, path, json):
            if path == "/v1/automation/alerts/observe":
                raise dashboard_main.httpx.ConnectError("alert monitor down")
            return FakeResponse()

    monkeypatch.setattr(dashboard_main, "overview", fake_overview)
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    response = client.get("/api/pipeline")
    assert response.status_code == 200
    assert response.json()["available"] is True
    assert response.json()["result"]["pipeline_id"] == "p"


def test_alert_feed_sends_data_quality_labels_for_outcome_confirmation(monkeypatch):
    event = {"farm_id": "f", "zone_id": "z", "device_id": "node", "timestamp": "2026-07-20T10:00:00Z"}
    result = {"sensor_quality": {"data_quality_labels": ["stuck_value"]}, "crop_risk": {"risk_labels": ["high_ec"]}}
    sent = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json):
            sent.append((path, json))

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    asyncio.run(dashboard_main.feed_alert_monitor(event, result))
    assert sent == [("/v1/automation/alerts/observe", {
        "farm_id": "f", "zone_id": "z", "device_id": "node", "sample_time": "2026-07-20T10:00:00Z",
        "risk_labels": ["stuck_value", "high_ec"], "data_quality_labels": ["stuck_value"]})]


def test_alert_feed_sends_detail_only_when_given(monkeypatch):
    """Slice 2, 2.6: feed_alert_monitor takes an optional sensor check text; without it the body is what it always was
    (the single-device path never passes it)."""
    event = {"farm_id": "f", "zone_id": "z", "device_id": "node", "timestamp": "2026-07-20T10:00:00Z"}
    result = {"sensor_quality": {"data_quality_labels": ["stuck_value"]}}
    sent = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json):
            sent.append(json)

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    for detail in (None, "", "inspect humidity_pct: near-zero variance"):
        asyncio.run(dashboard_main.feed_alert_monitor(event, result, detail))
    asyncio.run(dashboard_main.feed_alert_monitor(event, result))
    assert [list(body) for body in sent] == [["farm_id", "zone_id", "device_id", "sample_time", "risk_labels",
                                              "data_quality_labels"]] * 2 + [
        ["farm_id", "zone_id", "device_id", "sample_time", "risk_labels", "data_quality_labels", "detail"]] + [
        ["farm_id", "zone_id", "device_id", "sample_time", "risk_labels", "data_quality_labels"]]
    assert sent[2]["detail"] == "inspect humidity_pct: near-zero variance"


def test_pipeline_proxy_forwards_agronomy_calc_context(monkeypatch):
    event = {
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "crop": "tomato",
        "timestamp": "2026-07-20T10:00:00Z",
        "air_temperature_c": 33.0,
        "humidity_pct": 80.0,
        "ph": 5.2,
        "ec_ms_cm": 3.8,
        "soil_moisture_pct": 27.0,
        "source": "mqtt",
        "weather": {"t_mean_c": 29.2, "t_min_c": 25.6, "t_max_c": 34.8},
        "zone_area_m2": 20,
        "crop_kc": 1.15,
        "npk_target": {"n_ppm": 150, "p_ppm": 50, "k_ppm": 200, "volume_liters": 100},
    }

    async def fake_overview():
        return dashboard_main.OverviewResponse(
            core_available=True,
            latest_event=event,
            recent_events=[event],
        )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"pipeline_id": "pipeline-test", "final_decision": {}}

    class FakeClient:
        last_payload = None

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path, params=None):
            return dashboard_main.httpx.Response(
                200,
                json={"events": [event, {**event, "air_temperature_c": 23.5}], "count": 2},
                request=dashboard_main.httpx.Request("GET", "http://core" + path),
            )

        async def post(self, path, json):
            if path == "/v1/pipeline/evaluate":
                FakeClient.last_payload = json
            return FakeResponse()

    monkeypatch.setattr(dashboard_main, "overview", fake_overview)
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    response = client.get("/api/pipeline")

    assert response.status_code == 200
    farm_context = FakeClient.last_payload["farm_context"]
    assert farm_context["weather"] == event["weather"]
    assert farm_context["zone_area_m2"] == 20
    assert farm_context["crop_kc"] == 1.15
    assert farm_context["npk_target"] == event["npk_target"]
    assert isinstance(FakeClient.last_payload.get("history"), list)
    assert len(FakeClient.last_payload["history"]) == 1


def test_automation_proxy_lists_suggestions(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"count": 1, "suggestions": [{"id": "sug-1", "status": "pending"}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path):
            assert path == "/v1/automation/suggestions"
            return FakeResponse()

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    response = client.get("/api/automation")
    assert response.status_code == 200
    assert response.json()["result"]["suggestions"][0]["id"] == "sug-1"


def test_advice_cards_proxy(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "count": 1,
                "cards": [
                    {
                        "card_id": "c1",
                        "title": "Check water",
                        "severity": "warn",
                        "status": "pending",
                        "opportunity": "irrigation",
                        "summary": "Check water",
                        "evidence": {},
                        "safe_next_checks": [],
                        "blocked_actions": ["autonomous_irrigation_change"],
                        "human_review_required": True,
                    }
                ],
            }

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path):
            assert path == "/v1/automation/advice-cards"
            return FakeResponse()

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    response = client.get("/api/advice-cards")
    assert response.status_code == 200
    assert response.json()["result"]["cards"][0]["card_id"] == "c1"


def test_automation_evaluate_derives_risk_labels_from_latest_pipeline(monkeypatch):
    async def fake_pipeline():
        return dashboard_main.PipelineResponse(
            available=True,
            sensor_snapshot={"farm_id": "farm", "zone_id": "zone", "ph": 6.3, "calibration_id": "cal-1"},
            history_sha256="history-hash",
            result={
                "pipeline_id": "pipeline-test",
                "sensor_quality": {"data_quality_labels": ["stale_reading"]},
                "water_irrigation": {"irrigation_risk_labels": ["low_moisture"]},
                "nutrient_ph_ec": {"nutrient_risk_labels": ["high_ec"]},
                "crop_risk": {"risk_labels": []},
                "final_decision": {"blocked_actions": ["direct_actuator_control"],
                                   "trust_verdict": "cannot_confirm", "vetoed_fields": ["timestamp"]},
            },
        )

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"suggestions": []}

    class FakeClient:
        last_payload = None

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json):
            assert path == "/v1/automation/evaluate"
            FakeClient.last_payload = json
            return FakeResponse()

    monkeypatch.setattr(dashboard_main, "pipeline", fake_pipeline)
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    response = client.post("/api/automation/evaluate")

    assert response.status_code == 200
    payload = FakeClient.last_payload
    assert set(payload["risk_labels"]) == {"stale_reading", "low_moisture", "high_ec"}
    assert payload["blocked_actions"] == ["direct_actuator_control"]
    assert payload["context"]["pipeline_id"] == "pipeline-test"
    assert payload["context"]["readings"] == {"ph": 6.3}
    assert payload["context"]["sensor_snapshot"]["calibration_id"] == "cal-1"
    assert payload["context"]["history_sha256"] == "history-hash"
    assert payload["context"]["sensor_quality_labels"] == ["stale_reading"]
    assert payload["context"]["blocked_actions"] == ["direct_actuator_control"]
    assert payload["context"]["trust_verdict"] == "cannot_confirm"
    assert payload["context"]["vetoed_fields"] == ["timestamp"]
    assert payload["context"]["reasoner_snapshot"]["final_decision"]["trust_verdict"] == "cannot_confirm"


def test_automation_evaluate_without_pipeline_result_is_unavailable(monkeypatch):
    async def fake_pipeline():
        return dashboard_main.PipelineResponse(available=False, error="No pipeline result.")

    monkeypatch.setattr(dashboard_main, "pipeline", fake_pipeline)
    response = client.post("/api/automation/evaluate")
    assert response.status_code == 200
    assert response.json()["available"] is False


def test_automation_approve_and_reject_proxy(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "sug-1", "status": "approved"}

    class FakeClient:
        requested_paths = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json):
            assert json == {"reviewer": "Local operator"}
            FakeClient.requested_paths.append(path)
            return FakeResponse()

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    approve = client.post("/api/automation/suggestions/sug-1/approve", json={"reviewer": "Local operator"})
    reject = client.post("/api/automation/suggestions/sug-2/reject", json={"reviewer": "Local operator"})

    assert approve.status_code == 200
    assert reject.status_code == 200
    assert FakeClient.requested_paths == [
        "/v1/automation/suggestions/sug-1/approve",
        "/v1/automation/suggestions/sug-2/reject",
    ]


def test_audit_proxy_returns_summary_only(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"count": 1, "events": [{"pipeline_id": "pipeline-test", "risk_level": "high"}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, path, params=None):
            assert path == "/v1/pipeline/audit"
            assert params == {"limit": 20}
            return FakeResponse()

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    response = client.get("/api/audit")
    assert response.status_code == 200
    assert response.json()["result"]["events"][0]["pipeline_id"] == "pipeline-test"


def test_dashboard_html_exposes_specialist_results_and_read_only_warning():
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert 'id="specialists"' in html
    assert "Sensor quality" in html
    assert "Water / irrigation" in html
    assert "Nutrient / pH-EC" in html
    assert "deterministic safety remains final authority" in html


def test_dashboard_html_table_headers_use_scope_col():
    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    expected_headers = [
        '<th scope="col">Specialist</th>',
        '<th scope="col">Time</th>',
        '<th scope="col">Rule</th>',
        '<th scope="col">Farm</th>',
        '<th scope="col">Service</th>',
        '<th scope="col">Runtime</th>',
    ]
    for header in expected_headers:
        assert header in html
    assert "<th>" not in html


def test_service_status_includes_digital_twin(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok"}

    class FakeClient:
        requested_urls = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def get(self, url):
            self.requested_urls.append(url)
            return FakeResponse()

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    response = client.get("/api/services")

    assert response.status_code == 200
    assert response.json()["services"]["digital_twin"]["available"] is True
    assert f"{dashboard_main.settings.digital_twin_url}/health" in FakeClient.requested_urls


def test_digital_twin_proxy_is_forecast_only(monkeypatch):
    event = {
        "farm_id": "demo-farm",
        "zone_id": "greenhouse-a",
        "crop": "tomato",
        "air_temperature_c": 24.0,
        "humidity_pct": 65.0,
        "source": "mqtt",
    }

    async def fake_overview():
        return dashboard_main.OverviewResponse(
            core_available=True,
            latest_event=event,
            recent_events=[event],
        )

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        last_payload = None
        payloads = []

        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, path, json):
            FakeClient.last_payload = {"path": path, "json": json}
            FakeClient.payloads.append(FakeClient.last_payload)
            if path == "/v1/digital-twin/scenarios/simulate":
                return FakeResponse({
                    "mode": "forecast_only",
                    "safety_note": "Never execute this trajectory directly.",
                    "trajectory": [{"step": 1, "minutes_from_now": 15}],
                })
            return FakeResponse({
                "pipeline_id": "pipeline-preview",
                "final_decision": {"risk_level": "routine", "blocked_actions": [], "human_review_required": False},
            })

    monkeypatch.setattr(dashboard_main, "overview", fake_overview)
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    response = client.get("/api/digital-twin")

    assert response.status_code == 200
    assert response.json()["result"]["mode"] == "forecast_only"
    assert response.json()["result"]["guarded_evaluation"]["pipeline_id"] == "pipeline-preview"
    assert FakeClient.payloads[0]["path"] == "/v1/digital-twin/scenarios/simulate"
    assert FakeClient.payloads[0]["json"]["scenario"] == {
        "temperature_delta_c": 2.0,
        "humidity_delta_pct": 5.0,
        "moisture_delta_pct": 0.0,
        "irrigation_duration_min": 0.0,
        "ventilation_pct": 0.0,
    }
    assert "source" not in FakeClient.payloads[0]["json"]["state"]


def test_digital_twin_scenario_bounds_are_enforced():
    response = client.post("/api/digital-twin", json={"irrigation_duration_min": 241})

    assert response.status_code == 422


def test_farm_time_comes_from_core_health_and_falls_back_to_utc(monkeypatch):
    health = {"status": "ok", "time": {"farm_timezone": "Europe/Berlin", "utc_offset_now": "+01:00",
              "next_offset_change": "2027-03-28T01:00:00+00:00", "offset_after_change": "+02:00", "tzdata_version": None}}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, path):
            assert path == "/health"
            if health is None:
                raise dashboard_main.httpx.ConnectError("Core is down")
            return dashboard_main.httpx.Response(200, json=health, request=dashboard_main.httpx.Request("GET", "http://core" + path))
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    body = client.get("/api/farm-time").json()
    assert body["available"] and body["farm_timezone"] == "Europe/Berlin" and body["utc_offset_now"] == "+01:00"
    assert body["next_offset_change"] == "2027-03-28T01:00:00+00:00" and body["offset_after_change"] == "+02:00"
    unreported = {"available": False, "farm_timezone": "UTC", "utc_offset_now": "+00:00", "next_offset_change": None,
                  "offset_after_change": None, "tzdata_version": None}
    health = {"status": "ok"}  # an older Core without the field
    assert client.get("/api/farm-time").json() == unreported
    health = {"status": "ok", "time": {"farm_timezone": 7}}
    assert client.get("/api/farm-time").json() == unreported
    health = None  # Core unreachable
    assert client.get("/api/farm-time").json() == unreported


class _CoreEvents:
    """A fake Core that returns one stored reading sampled at `stamp`."""
    stamp = "2026-11-07T08:00:00Z"

    def __init__(self, *args, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def get(self, path, params=None):
        event = {"farm_id": "farm", "zone_id": "a", "air_temperature_c": 24, "ec_ms_cm": None, "timestamp": self.stamp}
        return dashboard_main.httpx.Response(200, json={"events": [event], "latest_event": event},
                                             request=dashboard_main.httpx.Request("GET", "http://core" + path))


def _overview_at(monkeypatch, now, stamp="2026-11-07T08:00:00Z", stale_after=600):
    from datetime import datetime, timezone
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", _CoreEvents)
    monkeypatch.setattr(_CoreEvents, "stamp", stamp)
    monkeypatch.setattr(dashboard_main, "utc_now", lambda: datetime.fromisoformat(now).astimezone(timezone.utc))
    monkeypatch.setattr(dashboard_main.settings, "zone_stale_after_s", stale_after)
    return client.get("/api/overview", params={"farm_id": "farm", "zone_id": "a"}).json()


def test_overview_sends_the_age_of_the_latest_reading_from_the_server_clock(monkeypatch):
    body = _overview_at(monkeypatch, "2026-11-07T08:12:00+00:00")
    assert body["latest_age_s"] == 720.0 and body["stale_after_s"] == 600
    assert body["latest_event"]["ec_ms_cm"] is None  # a probe that did not report is passed on as null


def test_a_sample_time_ahead_of_the_server_clock_is_age_zero_not_negative(monkeypatch):
    body = _overview_at(monkeypatch, "2026-11-07T07:59:30+00:00")  # Core allows a sample time up to MAX_FUTURE_SAMPLE_S ahead
    assert body["latest_age_s"] == 0.0


def test_stale_threshold_zero_is_passed_on_as_off_and_a_missing_or_bad_time_has_no_age(monkeypatch):
    assert _overview_at(monkeypatch, "2026-11-07T20:00:00+00:00", stale_after=0)["stale_after_s"] == 0
    assert _overview_at(monkeypatch, "2026-11-07T20:00:00+00:00", stamp="not a time")["latest_age_s"] is None
    assert _overview_at(monkeypatch, "2026-11-07T20:00:00+00:00", stamp="2026-11-07T08:00:00")["latest_age_s"] is None  # no UTC offset
    assert _overview_at(monkeypatch, "2026-11-07T20:00:00+00:00", stale_after=-5)["stale_after_s"] == 0


def test_stale_after_setting_defaults_to_ten_minutes_and_reads_the_environment(monkeypatch):
    assert dashboard_main.Settings(_env_file=None).zone_stale_after_s == 600
    monkeypatch.setenv("ZONE_STALE_AFTER_S", "0")
    assert dashboard_main.Settings(_env_file=None).zone_stale_after_s == 0


def test_evaluate_context_carries_missing_fields(monkeypatch):
    sent = {}

    async def fake_pipeline():
        return dashboard_main.PipelineResponse(
            available=True, sensor_snapshot={"farm_id": "farm", "zone_id": "a", "ec_ms_cm": None},
            result={"pipeline_id": "p", "sensor_quality": {"data_quality_labels": ["missing_ec"], "missing_fields": ["ec_ms_cm"]},
                    "final_decision": {"trust_verdict": "partial", "vetoed_fields": ["ec_ms_cm"], "blocked_actions": []}})

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, path, json):
            sent.update(json)
            return dashboard_main.httpx.Response(200, json={"suggestions": []}, request=dashboard_main.httpx.Request("POST", "http://a" + path))

    monkeypatch.setattr(dashboard_main, "pipeline", fake_pipeline)
    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    assert client.post("/api/automation/evaluate").json()["available"]
    assert sent["context"]["missing_fields"] == ["ec_ms_cm"] and sent["context"]["vetoed_fields"] == ["ec_ms_cm"]
    assert sent["context"]["readings"] == {"ec_ms_cm": None}


# --- Multi-device zones: slice 1 (docs/design/multi-device-zones.md 1.6) and slice 2 (multi-device-zones-slice2.md) ---
#
# A path-aware fake of every service the dashboard talks to: each outgoing request is recorded with the service it went
# to, and Core answers the zone listing, a device's own listing and the zone snapshot differently.

import hashlib
import json as jsonlib
from datetime import datetime, timezone

import pytest

STAMP = "2026-07-20T10:00:00Z"
NOW = datetime(2026, 7, 20, 10, 0, 30, tzinfo=timezone.utc)
CLEAN = {"pipeline_id": "p", "sensor_quality": {"data_quality_labels": [], "safe_next_checks": ["continue routine monitoring"]},
         "trust_gate": {"trust_verdict": "trusted", "vetoed_fields": []}, "final_decision": {"blocked_actions": []}}


class Clock:
    now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture(autouse=True)
def zone_caches(monkeypatch):
    """Every test starts with empty zone caches and the dashboard's own clock under test control."""
    dashboard_main.reset_zone_caches()
    value = Clock()
    monkeypatch.setattr(dashboard_main, "_clock", value)
    monkeypatch.setattr(dashboard_main, "utc_now", lambda: NOW)
    yield value
    dashboard_main.reset_zone_caches()


def judged(vetoed=(), labels=(), checks=None, verdict="trusted"):
    """A Core event_trust row; `labels=None` is a row written before the labels were kept."""
    return {"status": "judged", "trust_verdict": verdict, "vetoed_fields": list(vetoed),
            "data_quality_labels": None if labels is None else list(labels),
            "safe_next_checks": None if labels is None else (["continue routine monitoring"] if checks is None else list(checks))}


PENDING = {"status": "pending"}
READINGS = ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph", "soil_moisture_pct", "substrate_temperature_c",
            "substrate_moisture_pct")


def device(device_id, values, trust=None, stale=False, stamp=STAMP, retained=False, **extra):
    event = {"device_id": device_id, "farm_id": "f", "zone_id": "z", "crop": "tomato", "growth_stage": "flowering",
             "system_type": "greenhouse_substrate", "timestamp": stamp, "received_at": stamp, "mqtt_retained": retained,
             **values}
    return {"device_id": device_id, "event": event, "sample_time": stamp, "received_at": stamp, "age_s": 30.0,
            "interval_s": 30.0, "stale_limit_s": 600, "stale": stale, "device_fields": sorted(values), "supplied": [],
            "trust": judged() if trust is None else trust, **extra}


def snapshot_of(*devices):
    """Core's zone snapshot for these devices: each field from the first live device that has it and does not veto it."""
    fields, sources = {}, {}
    live = [d for d in devices if not d["stale"]]
    for name in READINGS:
        candidates = [d for d in live if d["event"].get(name) is not None]
        vetoes = lambda d: d["trust"]["status"] == "judged" and name in d["trust"]["vetoed_fields"]
        if candidates:
            chosen = next((d for d in candidates if not vetoes(d)), candidates[0])
            fields[name] = {"value": chosen["event"][name], "device_id": chosen["device_id"], "sample_time": chosen["sample_time"],
                            "age_s": 30.0, "others": [{"device_id": d["device_id"], "value": d["event"][name],
                                                       "sample_time": d["sample_time"], "vetoed": vetoes(d)}
                                                      for d in candidates if d is not chosen]}
            sources[name] = [chosen["device_id"]]
        elif any(name in d["device_fields"] for d in devices):
            sources[name] = [d["device_id"] for d in devices if name in d["device_fields"]]
    for d in devices:
        d["supplied"] = [n for n, f in fields.items() if f["device_id"] == d["device_id"]]
    sensor = None
    if fields:
        sensor = {"farm_id": "f", "zone_id": "z", "crop": "tomato", "growth_stage": "flowering",
                  "system_type": "greenhouse_substrate", **{n: f["value"] for n, f in fields.items()}, "timestamp": STAMP}
    return {"multi_device": True, "farm_id": "f", "zone_id": "z", "stale_after_s": 600, "devices": list(devices),
            "fields": fields, "sensor": sensor, "sources": sources,
            "zone_device_fields": sorted({f for d in devices for f in d["device_fields"]}),
            "context": {}, "context_source": {}, "context_conflicts": [],
            "newest_age_s": min((d["age_s"] for d in devices), default=None)}


CLIMATE = {"air_temperature_c": 24.0, "humidity_pct": 60.0}
SUBSTRATE = {"ph": 6.0, "ec_ms_cm": 2.0, "substrate_moisture_pct": 40.0}


def two_devices(climate_trust=None, substrate_trust=None, **kw):
    return snapshot_of(device("climate-1", dict(CLIMATE), climate_trust, **kw), device("substrate-1", dict(SUBSTRATE), substrate_trust))


def packet(stamp, ph=6.0, device_id="substrate-1", **extra):
    return {"farm_id": "f", "zone_id": "z", "device_id": device_id, "timestamp": stamp, "ph": ph,
            "source": "mqtt", "received_at": "2026-07-20T11:00:00Z", "mqtt_retained": False, **extra}


class Stack:
    """The fake services. `snapshot` is a dict, None (the zone is single-device: Core says so), or an exception to raise.
    `zone_events` is what Core's zone listing returns, oldest first; `device_events` maps a device to its own listing.
    `router_results[device_id]` is what the router answers a device check with."""
    URLS = {"core_url": "core", "model_router_url": "router", "automation_engine_url": "automation",
            "digital_twin_url": "twin", "safety_checker_url": "safety"}

    def __init__(self, monkeypatch, snapshot=None, zone_events=None, device_events=None, multi=True, latest_fields=None):
        self.requests = []
        self.snapshot = snapshot
        self.zone_events = zone_events
        self.device_events = device_events or {}
        self.multi = multi
        self.latest_fields = latest_fields
        self.router_results = {}
        self.failing = set()  # services whose every call raises
        self.fail_device_checks = False
        stack = self
        names = {getattr(dashboard_main.settings, attr): name for attr, name in self.URLS.items()}

        class FakeClient:
            def __init__(self, base_url="", **kwargs):
                self.service = names.get(base_url, base_url)

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

            async def get(self, path, params=None):
                return stack.answer(self.service, "GET", path, dict(params or {}), None)

            async def post(self, path, json=None):
                return stack.answer(self.service, "POST", path, {}, json)

        monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)

    def answer(self, service, method, path, params, body):
        self.requests.append({"service": service, "method": method, "path": path, "params": params, "json": body})
        if service in self.failing:
            raise dashboard_main.httpx.ConnectError(f"{service} is down")
        reply = self.respond(service, method, path, params, body)
        return dashboard_main.httpx.Response(200, json=reply, request=dashboard_main.httpx.Request(method, f"http://{service}{path}"))

    def respond(self, service, method, path, params, body):
        if service == "core" and path == "/v1/sensors/events":
            if params.get("device_id"):
                return {"events": self.device_events.get(params["device_id"], [])[-params.get("limit", 50):]}
            events = self.zone_events or []
            return {"events": events, "latest_event": events[-1] if events else None, "zone_multi_device": self.multi,
                    "latest_device_fields": self.latest_fields}
        if service == "core" and path == "/v1/sensors/zone-snapshot":
            if isinstance(self.snapshot, Exception):
                raise self.snapshot
            return self.snapshot if self.snapshot is not None else {"multi_device": False}
        if service == "router" and path == "/v1/pipeline/evaluate":
            if body["actor"] == "dashboard" and body.get("scenario_id") == "dashboard-device-check":
                if self.fail_device_checks:
                    raise dashboard_main.httpx.ConnectError("router is down")
                return self.router_results.get(body["sensor"]["device_id"], CLEAN)
            return CLEAN
        if service == "router" and path == "/v1/reasoners/shared-chain":
            return {"final_decision": {}, "quality": {}}
        if service == "router" and path == "/v1/advisor/explain":
            return {"text": "ok"}
        if service == "router":
            return {}
        if service == "twin":
            return {"mode": "forecast_only", "trajectory": [{"step": 1, "minutes_from_now": 15, **body["state"]}]}
        if service == "safety" or service == "automation":
            return {"suggestions": [], "events": [], "alerts": []}
        raise AssertionError(f"unexpected request {service} {method} {path}")

    def to(self, service, path=None):
        return [r for r in self.requests if r["service"] == service and (path is None or r["path"] == path)]

    def bodies(self, service, path):
        return [r["json"] for r in self.to(service, path)]


def zone_stack(monkeypatch, snap=None, **kw):
    snap = snap if snap is not None else two_devices()
    events = [packet(STAMP, device_id="substrate-1", **{k: v for k, v in SUBSTRATE.items()})]
    return Stack(monkeypatch, snapshot=snap, zone_events=events, latest_fields=["ec_ms_cm", "ph", "substrate_moisture_pct"], **kw)


def sha(value):
    return hashlib.sha256(jsonlib.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- the zone view: one snapshot per refresh, trends only in /api/overview ---------------------------------------

def test_overview_in_a_multi_device_zone_carries_the_snapshot_and_each_devices_trend(monkeypatch):
    snap = two_devices()
    snap["newest_age_s"] = 12.0
    stack = zone_stack(monkeypatch, snap, )
    stack.device_events = {"climate-1": [packet("2026-07-20T09:59:30Z", device_id="climate-1"), packet("2026-07-20T09:58:00Z", device_id="climate-1")],
                           "substrate-1": [packet(STAMP)]}
    body = client.get("/api/overview").json()
    assert body["zone_multi_device"] is True and body["zone_snapshot"]["sensor"] == snap["sensor"]
    assert body["zone_snapshot_error"] is None
    assert body["latest_age_s"] == 12.0  # the freshest device, so "no reading from this zone" needs every device quiet
    assert body["latest_event"]["device_id"] == "substrate-1"  # the newest packet, for old clients
    assert list(body["device_events"]) == ["climate-1", "substrate-1"]
    assert [e["timestamp"] for e in body["device_events"]["climate-1"]] == ["2026-07-20T09:58:00Z", "2026-07-20T09:59:30Z"]
    trend_calls = [r["params"] for r in stack.to("core", "/v1/sensors/events") if r["params"].get("device_id")]
    assert trend_calls == [{"farm_id": "f", "zone_id": "z", "device_id": d, "limit": 120} for d in ("climate-1", "substrate-1")]
    assert len(stack.to("core", "/v1/sensors/zone-snapshot")) == 1
    assert stack.to("core", "/v1/sensors/zone-snapshot")[0]["params"] == {"farm_id": "f", "zone_id": "z", "stale_after_s": 600}
    assert not stack.to("router")  # the overview never waits on the router, even for a pending device


def test_overview_with_a_pending_device_makes_no_router_call(monkeypatch):
    stack = zone_stack(monkeypatch, two_devices(substrate_trust=PENDING))
    assert client.get("/api/overview").json()["zone_snapshot"]["devices"][1]["trust"] == {"status": "pending"}
    assert not stack.to("router") and not stack.to("automation")


def test_trends_are_fetched_for_at_most_8_devices_in_device_id_order(monkeypatch):
    devices = [device(f"node-{n}", {"ph": 6.0 + n / 100}) for n in (9, 3, 1, 8, 2, 7, 4, 6, 5, 0)]
    stack = zone_stack(monkeypatch, snapshot_of(*devices))
    body = client.get("/api/overview").json()
    assert list(body["device_events"]) == [f"node-{n}" for n in range(8)]
    assert [r["params"]["device_id"] for r in stack.to("core", "/v1/sensors/events") if r["params"].get("device_id")] == list(body["device_events"])


def test_only_the_overview_fetches_trends_and_the_views_share_one_snapshot_call(monkeypatch, zone_caches):
    stack = zone_stack(monkeypatch)
    for path in ("/api/pipeline", "/api/risk", "/api/safety", "/api/digital-twin", "/api/explanation"):
        assert client.get(path).json()["available"], path
    assert not [r for r in stack.to("core", "/v1/sensors/events") if r["params"].get("limit") == 120]
    assert len(stack.to("core", "/v1/sensors/zone-snapshot")) == 1  # one snapshot call per (farm, zone) within 5 s
    zone_caches.now += 5.5
    client.get("/api/risk")
    assert len(stack.to("core", "/v1/sensors/zone-snapshot")) == 2  # the cache expired with the injected clock
    zone_caches.now += 1.0
    client.get("/api/risk")
    assert len(stack.to("core", "/v1/sensors/zone-snapshot")) == 2


def test_snapshot_cache_is_per_farm_and_zone(monkeypatch):
    stack = zone_stack(monkeypatch)
    for zone in ("z", "z", "other", "z"):
        client.get("/api/risk", params={"farm_id": "f", "zone_id": zone})
    assert [r["params"]["zone_id"] for r in stack.to("core", "/v1/sensors/zone-snapshot")] == ["z", "other"]


def test_unscoped_dashboard_takes_the_snapshot_of_the_newest_events_zone(monkeypatch):
    stack = zone_stack(monkeypatch)
    client.get("/api/risk")
    assert stack.to("core", "/v1/sensors/zone-snapshot")[0]["params"]["farm_id"] == "f"
    assert stack.to("core", "/v1/sensors/zone-snapshot")[0]["params"]["zone_id"] == "z"


# --- each view on the zone-view path ---------------------------------------------------------------------------

def vetoing_ec_snapshot():
    substrate = device("substrate-1", dict(SUBSTRATE), judged(["ec_ms_cm"], ["stuck_value"], ["inspect ec_ms_cm: near-zero variance"]))
    return snapshot_of(device("climate-1", dict(CLIMATE)), substrate)


def test_zone_view_pipeline_sends_the_snapshot_and_the_devices_checks_and_does_not_post_alerts(monkeypatch):
    snap = vetoing_ec_snapshot()
    stack = zone_stack(monkeypatch, snap)
    body = client.get("/api/pipeline").json()
    assert body["available"]
    (sent,) = stack.bodies("router", "/v1/pipeline/evaluate")
    sensor = snap["sensor"]
    assert sent["sensor"] == sensor and "device_id" not in sent["sensor"] and "source" not in sent["sensor"]
    assert sent["history"] == [] and "expected_fields" not in sent
    assert sent["device_fields"] == snap["zone_device_fields"]
    assert sent["known_vetoed_fields"] == ["ec_ms_cm"] and sent["known_data_quality_labels"] == ["stuck_value"]
    assert sent["known_safe_next_checks"] == ["inspect ec_ms_cm: near-zero variance"]  # "continue routine monitoring" is not carried
    assert (sent["mode"], sent["actor"], sent["scenario_id"]) == ("hybrid_guarded", "dashboard", "dashboard-latest-event")
    assert sent["farm_context"]["crop"] == "tomato" and sent["farm_context"]["zone_id"] == "z"
    assert not stack.to("automation")  # alerts stay per device
    assert body["sources"] == snap["sources"] and body["dashboard_judged"] == []
    assert body["sensor_snapshot"] == sensor and body["history_snapshot"] == []
    assert body["sensor_event_id"] == sha({"sensor": sensor, "sources": snap["sources"]})
    assert body["sensor_timestamp"] == STAMP
    assert not [r for r in stack.to("core", "/v1/sensors/events") if r["params"].get("device_id")]  # no history fetch


def test_zone_view_sends_zone_device_fields_so_a_zone_without_moisture_has_none_missing(monkeypatch):
    stack = zone_stack(monkeypatch, snapshot_of(device("climate-1", dict(CLIMATE)),
                                                device("substrate-1", {"ph": 6.0, "ec_ms_cm": 2.0})))
    client.get("/api/pipeline")
    client.get("/api/risk")
    for sent in (stack.bodies("router", "/v1/pipeline/evaluate")[0], stack.bodies("router", "/v1/reasoners/shared-chain")[0]):
        assert sent["device_fields"] == ["air_temperature_c", "ec_ms_cm", "humidity_pct", "ph"]
        assert not [f for f in sent["device_fields"] if "moisture" in f]


def test_zone_view_risk_sends_the_snapshot_device_fields_and_the_three_known_keys(monkeypatch):
    snap = vetoing_ec_snapshot()
    stack = zone_stack(monkeypatch, snap)
    assert client.get("/api/risk").json()["available"]
    (sent,) = stack.bodies("router", "/v1/reasoners/shared-chain")
    assert sent["sensor"] == snap["sensor"] and sent["farm_context"] == {"farm_id": "f", "crop": "tomato",
                                                                         "system_type": "greenhouse_substrate", "zone_id": "z"}
    assert sent["device_fields"] == snap["zone_device_fields"] and "expected_fields" not in sent
    assert sent["known_vetoed_fields"] == ["ec_ms_cm"] and sent["known_data_quality_labels"] == ["stuck_value"]
    assert (sent["actor"], sent["mode"], sent["proposed_command"]) == ("dashboard", "hybrid_guarded", {"action_type": "continue_monitoring"})


def test_zone_view_safety_sends_the_unmasked_reading_without_a_device(monkeypatch):
    snap = vetoing_ec_snapshot()
    stack = zone_stack(monkeypatch, snap)
    assert client.get("/api/safety").json()["available"]
    (sent,) = stack.bodies("router", "/v1/reasoners/safety-triage")
    assert sent["input"]["sensor"] == snap["sensor"] and "device_id" not in sent["input"]["sensor"]
    assert "ec_ms_cm" in sent["input"]["sensor"]  # unmasked
    assert "sensor_quality" not in sent["input"]
    assert not stack.to("core", "/v1/sensors/events") or all(not r["params"].get("device_id") for r in stack.to("core", "/v1/sensors/events"))


def test_zone_view_twin_simulates_the_masked_reading_and_asks_the_guard_without_expected_fields(monkeypatch):
    snap = vetoing_ec_snapshot()
    stack = zone_stack(monkeypatch, snap)
    assert client.get("/api/digital-twin").json()["available"]
    (simulated,) = stack.bodies("twin", "/v1/digital-twin/scenarios/simulate")
    assert "ec_ms_cm" not in simulated["state"] and simulated["state"]["ph"] == 6.0  # masked: the vetoed EC is out
    (guard,) = [b for b in stack.bodies("router", "/v1/pipeline/evaluate") if b["scenario_id"] == "dashboard-digital-twin-preview"]
    assert "expected_fields" not in guard and guard["device_fields"] == snap["zone_device_fields"]
    assert guard["known_vetoed_fields"] == ["ec_ms_cm"] and guard["known_data_quality_labels"] == ["stuck_value"]
    assert guard["actor"] == "dashboard_digital_twin_preview"


def test_zone_view_explanation_uses_the_masked_reading_and_the_zone_risk_result(monkeypatch):
    snap = vetoing_ec_snapshot()
    stack = zone_stack(monkeypatch, snap)
    assert client.get("/api/explanation").json()["available"]
    (sent,) = stack.bodies("router", "/v1/advisor/explain")
    assert "ec_ms_cm" not in sent["sensor"] and sent["sensor"]["ph"] == 6.0 and "device_id" not in sent["sensor"]
    assert sent["guarded_context"] == {"final_decision": {}, "quality": {}}  # the shared-chain answer
    assert len(stack.bodies("router", "/v1/reasoners/shared-chain")) == 1


def test_evaluate_on_the_zone_view_carries_sources_and_the_sensor_check_labels(monkeypatch):
    snap = vetoing_ec_snapshot()
    stack = zone_stack(monkeypatch, snap)
    stack.router_results = {}
    original = stack.respond

    def respond(service, method, path, params, body):
        if service == "router" and path == "/v1/pipeline/evaluate":
            return {**CLEAN, "sensor_quality": {"data_quality_labels": ["stuck_value"], "missing_fields": [],
                                                "safe_next_checks": ["inspect ec_ms_cm"]},
                    "trust_gate": {"trust_verdict": "partial", "vetoed_fields": ["ec_ms_cm"]},
                    "final_decision": {"trust_verdict": "partial", "vetoed_fields": ["ec_ms_cm"], "blocked_actions": []}}
        return original(service, method, path, params, body)

    stack.respond = respond
    assert client.post("/api/automation/evaluate").json()["available"]
    (sent,) = stack.bodies("automation", "/v1/automation/evaluate")
    assert "stuck_value" in sent["risk_labels"]
    assert sent["context"]["sources"] == snap["sources"]
    assert sent["context"]["sensor_snapshot"] == snap["sensor"] and "device_id" not in sent["context"]["sensor_snapshot"]
    assert sent["context"]["vetoed_fields"] == ["ec_ms_cm"]
    assert sent["event_id"] == sha({"sensor": snap["sensor"], "sources": snap["sources"]})


# --- device checks ---------------------------------------------------------------------------------------------

def checks_of(snap):
    out = asyncio.run(dashboard_main.device_checks(snap))
    return out.vetoed, out.labels, out.checks, out.dashboard_judged


def test_a_judged_device_carries_only_the_vetoes_of_fields_it_supplies(monkeypatch):
    Stack(monkeypatch)
    # climate-2 also carries humidity but climate-1 supplies it; climate-2's own humidity veto is not carried.
    climate_1 = device("climate-1", {"air_temperature_c": 24.0, "humidity_pct": 60.0}, judged())
    climate_2 = device("climate-2", {"humidity_pct": 61.0}, judged(["humidity_pct"], ["stuck_value"], ["inspect humidity_pct"]))
    assert checks_of(snapshot_of(climate_1, climate_2)) == ([], [], [], [])


def test_a_flagged_probe_outside_the_zone_view_puts_no_label_on_the_zone(monkeypatch):
    Stack(monkeypatch)
    # substrate-1's EC probe is stuck and climate-2's good EC reading is used instead; substrate-1 still supplies pH.
    substrate = device("substrate-1", {"ph": 6.0, "ec_ms_cm": 2.0}, judged(["ec_ms_cm"], ["stuck_value"], ["inspect ec_ms_cm"]))
    other = device("climate-2", {"ec_ms_cm": 2.1})
    vetoed, labels, checks, _ = checks_of(snapshot_of(substrate, other))
    assert vetoed == [] and labels == [] and checks == []


def test_a_device_that_vetoed_nothing_carries_its_labels(monkeypatch):
    Stack(monkeypatch)
    node = device("substrate-1", {"ph": 6.0}, judged([], ["flatline_possible"], ["watch ph"]))
    assert checks_of(snapshot_of(node)) == ([], ["flatline_possible"], ["watch ph"], [])


def test_a_global_veto_label_vetoes_everything_the_device_supplies(monkeypatch):
    Stack(monkeypatch)
    node = device("climate-1", dict(CLIMATE), judged(["humidity_pct"], ["stale_reading"], ["check the clock"]))
    snap = snapshot_of(node, device("substrate-1", dict(SUBSTRATE)))
    vetoed, labels, checks, _ = checks_of(snap)
    assert vetoed == ["air_temperature_c", "humidity_pct"] and labels == ["stale_reading"] and checks == ["check the clock"]


def test_a_row_from_before_the_labels_were_kept_carries_its_vetoes_only(monkeypatch):
    Stack(monkeypatch)
    node = device("climate-1", dict(CLIMATE), judged(["humidity_pct"], labels=None))
    assert checks_of(snapshot_of(node)) == (["humidity_pct"], [], [], [])


def test_a_stale_device_supplies_nothing_and_counts_for_nothing(monkeypatch):
    stack = Stack(monkeypatch)
    quiet = device("climate-1", dict(CLIMATE), PENDING, stale=True)
    live = device("substrate-1", dict(SUBSTRATE))
    assert checks_of(snapshot_of(quiet, live)) == ([], [], [], [])
    assert not stack.requests  # a stale pending device is not judged


def test_checks_of_several_devices_are_merged_without_repeats(monkeypatch):
    Stack(monkeypatch)
    a = device("a", {"ph": 6.0}, judged(["ph"], ["stuck_value"], ["inspect ph"]))
    b = device("b", {"ec_ms_cm": 2.0}, judged(["ec_ms_cm"], ["stuck_value"], ["inspect ec", "inspect ph"]))
    assert checks_of(snapshot_of(a, b)) == (["ph", "ec_ms_cm"], ["stuck_value"], ["inspect ph", "inspect ec"], [])


# --- the dashboard judges a pending device itself --------------------------------------------------------------

def stuck_result(vetoed, label="stuck_value", check="inspect humidity_pct: near-zero variance may indicate a stuck or clipped probe"):
    return {**CLEAN, "sensor_quality": {"data_quality_labels": [label], "safe_next_checks": [check, "continue routine monitoring"]},
            "trust_gate": {"trust_verdict": "partial", "vetoed_fields": vetoed}}


def pending_stack(monkeypatch, **kw):
    snap = two_devices(climate_trust=PENDING)
    history = [packet("2026-07-20T09:58:30Z", device_id="climate-1", air_temperature_c=23.5),
               packet("2026-07-20T09:59:00Z", device_id="climate-1", air_temperature_c=23.8),
               packet("2026-07-20T10:00:30Z", device_id="climate-1", air_temperature_c=24.3),  # sampled after the packet
               packet(STAMP, device_id="climate-1", air_temperature_c=24.0)]
    stack = zone_stack(monkeypatch, snap, **kw)
    stack.device_events["climate-1"] = history
    stack.router_results["climate-1"] = stuck_result(["humidity_pct"])
    return stack, snap


def test_a_pending_device_is_judged_by_the_dashboard_rules_only_with_its_own_history(monkeypatch):
    stack, snap = pending_stack(monkeypatch)
    body = client.get("/api/pipeline").json()
    (check,) = [b for b in stack.bodies("router", "/v1/pipeline/evaluate") if b["scenario_id"] == "dashboard-device-check"]
    assert check["mode"] == "rules_only" and check["actor"] == "dashboard"
    assert check["sensor"]["device_id"] == "climate-1" and "source" not in check["sensor"]
    assert check["device_fields"] == ["air_temperature_c", "humidity_pct"]
    assert [h["air_temperature_c"] for h in check["history"]] == [23.5, 23.8]  # strictly earlier samples, oldest first
    assert not {"source", "received_at", "mqtt_retained"} & set(check["history"][0])
    (history_call,) = [r for r in stack.to("core", "/v1/sensors/events") if r["params"].get("device_id")]
    assert history_call["params"] == {"limit": 24, "farm_id": "f", "zone_id": "z", "device_id": "climate-1"}
    # its result is carried into the zone view
    (zone,) = [b for b in stack.bodies("router", "/v1/pipeline/evaluate") if b["scenario_id"] == "dashboard-latest-event"]
    assert zone["known_vetoed_fields"] == ["humidity_pct"] and zone["known_data_quality_labels"] == ["stuck_value"]
    assert zone["known_safe_next_checks"] == ["inspect humidity_pct: near-zero variance may indicate a stuck or clipped probe"]
    assert body["dashboard_judged"] == ["climate-1"]


def test_the_pending_device_check_is_posted_to_alerts_once_per_packet_with_its_detail(monkeypatch):
    stack, snap = pending_stack(monkeypatch)
    for path in ("/api/pipeline", "/api/risk", "/api/pipeline", "/api/digital-twin", "/api/explanation"):
        client.get(path)
    checks = [b for b in stack.bodies("router", "/v1/pipeline/evaluate") if b["scenario_id"] == "dashboard-device-check"]
    assert len(checks) == 1  # the result is cached by (farm, zone, device, sample time)
    (posted,) = stack.bodies("automation", "/v1/automation/alerts/observe")
    assert posted["device_id"] == "climate-1" and posted["sample_time"] == STAMP
    assert posted["data_quality_labels"] == ["stuck_value"]
    assert posted["detail"] == "inspect humidity_pct: near-zero variance may indicate a stuck or clipped probe"
    # a new packet is judged again
    stack.snapshot = snapshot_of(device("climate-1", dict(CLIMATE), PENDING, stamp="2026-07-20T10:00:30Z"),
                                 device("substrate-1", dict(SUBSTRATE)))
    dashboard_main._snapshot_cache.clear()
    client.get("/api/pipeline")
    assert len(stack.bodies("automation", "/v1/automation/alerts/observe")) == 2


def test_a_retained_packet_is_judged_for_the_view_but_not_posted(monkeypatch):
    snap = two_devices(climate_trust=PENDING)
    snap["devices"][0]["event"]["mqtt_retained"] = True
    stack = zone_stack(monkeypatch, snap)
    stack.router_results["climate-1"] = stuck_result(["humidity_pct"])
    body = client.get("/api/pipeline").json()
    assert [b for b in stack.bodies("router", "/v1/pipeline/evaluate") if b["scenario_id"] == "dashboard-device-check"]
    assert body["dashboard_judged"] == ["climate-1"]
    assert not stack.to("automation")


def test_a_clean_pending_device_posts_no_detail_and_carries_nothing(monkeypatch):
    stack = zone_stack(monkeypatch, two_devices(climate_trust=PENDING))
    body = client.get("/api/pipeline").json()
    (posted,) = stack.bodies("automation", "/v1/automation/alerts/observe")
    assert "detail" not in posted  # only "continue routine monitoring": nothing to say
    (zone,) = [b for b in stack.bodies("router", "/v1/pipeline/evaluate") if b["scenario_id"] == "dashboard-latest-event"]
    assert (zone["known_vetoed_fields"], zone["known_data_quality_labels"], zone["known_safe_next_checks"]) == ([], [], [])
    assert body["dashboard_judged"] == ["climate-1"]


def test_a_failed_device_check_vetoes_everything_it_supplies_and_is_retried_after_5_s(monkeypatch, zone_caches):
    stack = zone_stack(monkeypatch, two_devices(climate_trust=PENDING))
    stack.fail_device_checks = True
    body = client.get("/api/pipeline").json()
    (zone,) = [b for b in stack.bodies("router", "/v1/pipeline/evaluate") if b["scenario_id"] == "dashboard-latest-event"]
    assert zone["known_vetoed_fields"] == ["air_temperature_c", "humidity_pct"]
    assert zone["known_safe_next_checks"] == ["sensor check for climate-1 could not run; verify its readings"]
    assert body["dashboard_judged"] == []
    assert not stack.to("automation")
    attempts = lambda: len([r for r in stack.to("router", "/v1/pipeline/evaluate")
                            if r["json"]["scenario_id"] == "dashboard-device-check"])
    assert attempts() == 1
    client.get("/api/risk")
    assert attempts() == 1  # kept for 5 s: no retry in the same refresh
    zone_caches.now += 6
    stack.fail_device_checks = False
    body = client.get("/api/risk").json()
    assert attempts() == 2  # retried after 5 s ...
    zone_caches.now += 600
    client.get("/api/risk")
    assert attempts() == 2  # ... and a success is kept
    assert len(stack.bodies("automation", "/v1/automation/alerts/observe")) == 1


def test_the_result_cache_holds_at_most_256_packets(monkeypatch):
    stack = zone_stack(monkeypatch, two_devices())
    for n in range(300):
        node = device("climate-1", dict(CLIMATE), PENDING, stamp=f"2026-07-20T10:{n // 60:02d}:{n % 60:02d}Z")
        asyncio.run(dashboard_main._device_judgment("f", "z", node))
    assert len(dashboard_main._judged_cache) == 256
    assert ("f", "z", "climate-1", "2026-07-20T10:00:00Z") not in dashboard_main._judged_cache
    assert ("f", "z", "climate-1", "2026-07-20T10:04:59Z") in dashboard_main._judged_cache


def test_concurrent_views_share_one_device_check(monkeypatch):
    stack = zone_stack(monkeypatch, two_devices(climate_trust=PENDING))

    async def refresh():
        return await asyncio.gather(dashboard_main.pipeline(), dashboard_main.risk(), dashboard_main.explanation())

    assert all(r.available for r in asyncio.run(refresh()))
    assert len([r for r in stack.to("router", "/v1/pipeline/evaluate") if r["json"]["scenario_id"] == "dashboard-device-check"]) == 1


# --- the other paths of the table in 2.4 -----------------------------------------------------------------------

def stale_snapshot():
    snap = two_devices()
    for d in snap["devices"]:
        d["stale"], d["supplied"] = True, []
    snap.update(fields={}, sensor=None, sources={"air_temperature_c": ["climate-1"]}, newest_age_s=1200.0)
    return snap


def newest_packet_path(stack, history_calls):
    """What slice 1's multi-device path did: the newest packet, that device's own history, its device_fields."""
    body = client.get("/api/pipeline").json()
    assert body["available"] and body["sources"] is None and body["dashboard_judged"] is None
    (sent,) = stack.bodies("router", "/v1/pipeline/evaluate")
    assert sent["sensor"]["device_id"] == "substrate-1" and sent["device_fields"] == ["ec_ms_cm", "ph", "substrate_moisture_pct"]
    assert "known_vetoed_fields" not in sent
    assert [r["params"] for r in history_calls(stack)] == [{"limit": 24, "farm_id": "f", "zone_id": "z", "device_id": "substrate-1"}]
    assert not stack.to("router", "/v1/reasoners/shared-chain")
    return body


def own_history(stack):
    return [r for r in stack.to("core", "/v1/sensors/events") if r["params"].get("device_id")]


def test_when_every_device_is_stale_the_newest_packet_path_runs(monkeypatch):
    stack = zone_stack(monkeypatch, stale_snapshot())
    body = client.get("/api/overview").json()
    assert body["zone_snapshot"]["sensor"] is None and body["latest_age_s"] == 1200.0 and body["zone_snapshot_error"] is None
    stack.requests.clear()
    newest_packet_path(stack, own_history)
    assert not stack.to("automation") or stack.bodies("automation", "/v1/automation/alerts/observe")[0]["device_id"] == "substrate-1"


def test_when_the_snapshot_call_fails_the_newest_packet_path_runs_and_the_error_is_named(monkeypatch, caplog):
    stack = zone_stack(monkeypatch, RuntimeError("boom"))
    with caplog.at_level("WARNING"):
        body = client.get("/api/overview").json()
    assert body["zone_snapshot"] is None and body["device_events"] is None
    assert body["zone_snapshot_error"].startswith("Zone snapshot unavailable") and "boom" not in body["zone_snapshot_error"]
    assert "boom" in caplog.text  # the detail stays in the log
    assert body["zone_multi_device"] is True and body["latest_event"]["device_id"] == "substrate-1"
    stack.requests.clear()
    newest_packet_path(stack, own_history)


def test_a_failed_snapshot_is_not_cached(monkeypatch):
    stack = zone_stack(monkeypatch, RuntimeError("boom"))
    client.get("/api/risk")
    stack.snapshot = two_devices()
    client.get("/api/risk")
    assert len(stack.to("core", "/v1/sensors/zone-snapshot")) == 2
    assert len(stack.to("router", "/v1/reasoners/shared-chain")) == 2
    assert "known_vetoed_fields" not in stack.bodies("router", "/v1/reasoners/shared-chain")[0]
    assert "known_vetoed_fields" in stack.bodies("router", "/v1/reasoners/shared-chain")[1]


def test_a_zone_that_just_turned_single_device_takes_todays_path(monkeypatch):
    events = [packet("2026-07-20T09:59:00Z", 6.1), packet(STAMP, 6.0)]
    stack = Stack(monkeypatch, snapshot=None, zone_events=events, latest_fields=["ph"])  # Core: multi_device false
    body = client.get("/api/overview").json()
    assert body["zone_multi_device"] is False and body["latest_device_fields"] is None and body["zone_snapshot"] is None
    stack.requests.clear()
    assert client.get("/api/pipeline").json()["available"]
    assert [r["params"] for r in stack.to("core", "/v1/sensors/events")] == [{"limit": 20}, {"limit": 12}]  # no device filter
    (sent,) = stack.bodies("router", "/v1/pipeline/evaluate")
    assert "device_fields" not in sent and [h["ph"] for h in sent["history"]] == [6.1]


# --- slice 1's newest-packet path (rewritten on the path-aware fake) ---------------------------------------------

def newest_packet_stack(monkeypatch, events, latest_fields):
    """The slice-1 situation: a multi-device zone whose zone view is not available, so the newest packet is judged."""
    return Stack(monkeypatch, snapshot=RuntimeError("no zone view"), zone_events=[events[-1]] if events else [],
                 device_events={"substrate-1": events}, latest_fields=latest_fields)


def test_multi_device_pipeline_uses_the_devices_own_history_and_its_fields(monkeypatch):
    # Core answers oldest first. The evaluated packet (10:00:00) is among them, a late packet (10:00:30, sampled after it)
    # arrived before it, and an older packet (09:58:30) arrived after it.
    events = [packet("2026-07-20T09:59:00Z", 6.1), packet("2026-07-20T10:00:30Z", 6.9),
              packet("2026-07-20T10:00:00Z", 6.0), packet("2026-07-20T09:58:30Z", 6.2),
              packet("2026-07-20T09:59:00Z", 6.15)]
    stack = Stack(monkeypatch, snapshot=RuntimeError("no zone view"), zone_events=[events[2]],
                  device_events={"substrate-1": events}, latest_fields=["ec_ms_cm", "ph"])
    assert client.get("/api/pipeline").json()["available"]  # unscoped request: no farm_id or zone_id in the query
    history_params = [r["params"] for r in stack.to("core", "/v1/sensors/events") if r["params"].get("device_id")]
    assert history_params == [{"limit": 24, "farm_id": "f", "zone_id": "z", "device_id": "substrate-1"}]
    (body,) = stack.bodies("router", "/v1/pipeline/evaluate")
    assert body["device_fields"] == ["ec_ms_cm", "ph"]
    # strictly earlier than the evaluated sample, in sample-time order, API order breaking the tie at 09:59:00
    assert [(h["timestamp"], h["ph"]) for h in body["history"]] == [
        ("2026-07-20T09:58:30Z", 6.2), ("2026-07-20T09:59:00Z", 6.1), ("2026-07-20T09:59:00Z", 6.15)]
    assert not {"source", "received_at", "mqtt_retained"} & set(body["history"][0])
    assert [b["device_id"] for b in stack.bodies("automation", "/v1/automation/alerts/observe")] == ["substrate-1"]


def test_multi_device_history_keeps_the_newest_11(monkeypatch):
    events = [packet(f"2026-07-20T09:{minute:02d}:00Z", 6.0 + minute / 100) for minute in range(20, 60)]
    events.append(packet(STAMP, 6.0))
    stack = Stack(monkeypatch, snapshot=RuntimeError("no zone view"), zone_events=[events[-1]],
                  device_events={"substrate-1": events}, latest_fields=["ph"])
    client.get("/api/pipeline")
    (body,) = stack.bodies("router", "/v1/pipeline/evaluate")
    stamps = [h["timestamp"] for h in body["history"]]
    assert len(stamps) == 11 and stamps[0] == "2026-07-20T09:49:00Z" and stamps[-1] == "2026-07-20T09:59:00Z"


def test_overview_passes_the_two_core_keys_on(monkeypatch):
    stack = Stack(monkeypatch, snapshot=RuntimeError("no zone view"), zone_events=[packet(STAMP)], latest_fields=["ph"])
    body = client.get("/api/overview").json()
    assert body["zone_multi_device"] is True and body["latest_device_fields"] == ["ph"]


# --- Rule 0: a single-device zone ------------------------------------------------------------------------------

def single_stack(monkeypatch):
    events = [packet("2026-07-20T09:59:00Z", 6.1, air_temperature_c=24.0), packet(STAMP, 6.0, air_temperature_c=24.5)]
    return Stack(monkeypatch, snapshot=None, zone_events=events, multi=False)


def test_single_device_pipeline_request_is_unchanged(monkeypatch):
    stack = single_stack(monkeypatch)
    body = client.get("/api/pipeline").json()
    assert [r["params"] for r in stack.to("core", "/v1/sensors/events")] == [{"limit": 20}, {"limit": 12}]
    assert not stack.to("core", "/v1/sensors/zone-snapshot")  # no extra request in a single-device zone
    (sent,) = stack.bodies("router", "/v1/pipeline/evaluate")
    event = {k: v for k, v in packet(STAMP, 6.0, air_temperature_c=24.5).items() if k != "source"}
    assert sent == {
        "scenario_id": "dashboard-latest-event",
        "farm_context": {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "z", "weather": None,
                         "zone_area_m2": None, "crop_kc": None, "npk_target": None},
        "sensor": event, "history": [{k: v for k, v in packet("2026-07-20T09:59:00Z", 6.1, air_temperature_c=24.0).items()
                                      if k not in ("source", "received_at", "mqtt_retained")}],
        "proposed_command": {"action_type": "continue_monitoring"}, "actor": "dashboard", "mode": "hybrid_guarded"}
    assert body["sources"] is None and body["dashboard_judged"] is None
    (posted,) = stack.bodies("automation", "/v1/automation/alerts/observe")
    assert list(posted) == ["farm_id", "zone_id", "device_id", "sample_time", "risk_labels", "data_quality_labels"]


def test_single_device_views_send_what_they_always_sent(monkeypatch):
    stack = single_stack(monkeypatch)
    for path in ("/api/risk", "/api/safety", "/api/digital-twin", "/api/explanation"):
        assert client.get(path).json()["available"], path
    assert not stack.to("core", "/v1/sensors/zone-snapshot")
    event = {k: v for k, v in packet(STAMP, 6.0, air_temperature_c=24.5).items() if k != "source"}
    chain = stack.bodies("router", "/v1/reasoners/shared-chain")
    assert chain[0] == {"farm_context": {"farm_id": "f", "crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "z"},
                        "sensor": event, "proposed_command": {"action_type": "continue_monitoring"}, "actor": "dashboard",
                        "mode": "hybrid_guarded"}
    (triage,) = stack.bodies("router", "/v1/reasoners/safety-triage")
    assert triage["input"]["sensor"] == {**event, "source": "mqtt"}  # the safety view has always sent the packet as stored
    (guard,) = [b for b in stack.bodies("router", "/v1/pipeline/evaluate")]
    assert guard["expected_fields"] == ["air_temperature_c", "ph"] and not {"device_fields", "known_vetoed_fields"} & set(guard)
    (explained,) = stack.bodies("router", "/v1/advisor/explain")
    assert explained["sensor"] == {**event, "source": "mqtt"}


def test_single_device_evaluate_context_has_no_sources(monkeypatch):
    stack = single_stack(monkeypatch)
    assert client.post("/api/automation/evaluate").json()["available"]
    (sent,) = stack.bodies("automation", "/v1/automation/evaluate")
    assert "sources" not in sent["context"]
    assert client.get("/api/overview").json()["zone_snapshot"] is None


def test_failed_service_calls_do_not_leak_internal_text_to_the_browser(monkeypatch, caplog):
    secret = "http://core.internal.example:8080/v1/sensors/devices"

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, path, params=None):
            raise dashboard_main.httpx.ConnectError(f"connection refused: {secret}")
        async def post(self, path, json=None):
            raise dashboard_main.httpx.ConnectError(f"connection refused: {secret}")

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    expected = {"/api/devices": "Device status", "/api/probe-health": "Probe health", "/api/history": "History",
                "/api/overview": "Core", "/api/runtimes": "Runtime status", "/api/alerts": "Alert monitor",
                "/api/automation": "Automation engine", "/api/audit": "Pipeline audit"}
    with caplog.at_level("WARNING"):
        for path, label in expected.items():
            response = client.get(path)
            assert response.status_code == 200, path
            assert secret not in response.text and "refused" not in response.text and "internal" not in response.text, path
            assert f"{label} unavailable" in response.text, path
        services = client.get("/api/services")
    assert secret not in services.text and "refused" not in services.text
    statuses = services.json()["services"]
    assert set(statuses) == {"core", "model_router", "safety_checker", "digital_twin", "automation_engine"}
    assert all(item["available"] is False and "unavailable" in item["error"] for item in statuses.values())
    assert statuses["model_router"]["error"].startswith("model router unavailable")
    assert secret in caplog.text  # the detail stays in the log
