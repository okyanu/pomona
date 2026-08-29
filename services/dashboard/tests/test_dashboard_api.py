import sys
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
            self.last_payload = json
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
