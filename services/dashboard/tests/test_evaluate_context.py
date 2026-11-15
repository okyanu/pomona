"""The context automation_evaluate() sends to the automation engine, held against a file the abstention eval shares.

scripts/tests/fixtures/dashboard_evaluate_context.json holds a pipeline result, the event and history the dashboard reads from
Core, and the `context` this function must send. The eval's copy of the builder (scripts/eval_abstention.py
`dashboard_context`, a stated mirror: three `app` packages cannot share one process) is checked against the same file by
scripts/tests/test_eval_abstention.py, so a change on either side fails one of the two tests.

After an intended change to automation_evaluate(), run this test once with UPDATE_FIXTURES=1 (it rewrites `context`), then fix the
eval's mirror until scripts/tests/test_eval_abstention.py passes again.
"""

import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

SERVICE_DIR = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).resolve().parents[3] / "scripts" / "tests" / "fixtures" / "dashboard_evaluate_context.json"
sys.path.insert(0, str(SERVICE_DIR))

# Core and Dashboard both use an ``app`` package; isolate imports when the
# full multi-service test suite runs in one Python process.
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.main as dashboard_main


def test_automation_evaluate_sends_the_context_in_the_shared_fixture(monkeypatch):
    fixture = json.loads(FIXTURE.read_text())
    core_events = [*fixture["history"], fixture["event"]]  # Core serves the packets in sample-time order, newest last
    sent = []

    def response(path, body):
        return dashboard_main.httpx.Response(200, json=body, request=dashboard_main.httpx.Request("POST", "http://mock" + path))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, path, params=None):
            assert path == "/v1/sensors/events"
            return response(path, {"events": core_events})

        async def post(self, path, json=None):
            if path == "/v1/pipeline/evaluate":
                return response(path, fixture["result"])
            if path == "/v1/automation/evaluate":
                sent.append(json)
            return response(path, {"suggestions": [], "count": 0})

    monkeypatch.setattr(dashboard_main.httpx, "AsyncClient", FakeClient)
    reply = TestClient(dashboard_main.app).post("/api/automation/evaluate").json()
    assert reply["available"] and len(sent) == 1
    request = json.loads(json.dumps(sent[0]))  # as it goes over the wire
    assert request["risk_labels"] == fixture["context"]["risk_labels"]
    assert request["blocked_actions"] == fixture["result"]["final_decision"]["blocked_actions"]
    assert request["event_id"] == fixture["context"]["sensor_event_id"]

    if os.environ.get("UPDATE_FIXTURES") == "1":
        fixture["context"] = request["context"]
        FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n")
    assert request["context"] == fixture["context"]
