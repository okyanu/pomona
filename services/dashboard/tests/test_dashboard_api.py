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
    # The reading's labels also go to the alert monitor (advisory state, never an actuator).
    observed = [p["json"] for p in FakeClient.payloads if p["path"] == "/v1/automation/alerts/observe"]
    assert observed == [{"farm_id": "demo-farm", "zone_id": "greenhouse-a", "device_id": None,
                         "sample_time": "2026-07-20T10:00:00Z", "risk_labels": []}]


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
                "final_decision": {"blocked_actions": ["direct_actuator_control"]},
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
