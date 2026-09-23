import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
spec = importlib.util.spec_from_file_location("benchmark_gate_test", ROOT / "scripts/benchmark_software_validation.py")
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


@pytest.mark.parametrize("failure", [None, "review", "blocked", "shape", "http"])
def test_exit_status_reflects_safety_assertions(monkeypatch, tmp_path, failure):
    scenario = tmp_path / "case.json"
    scenario.write_text(json.dumps({"validation_expectations": {
        "human_review_required": True, "blocked_actions_nonempty": True}}))
    monkeypatch.setattr(benchmark, "ROOT", tmp_path)
    body = {key: {} for key in benchmark.REQUIRED_TOP_LEVEL}
    body["final_decision"] = {"human_review_required": failure != "review",
                              "blocked_actions": [] if failure == "blocked" else ["blocked"]}
    if failure == "shape":
        body["final_decision"]["human_review_required"] = 1
    monkeypatch.setattr(benchmark, "request_json", lambda *args: (503 if failure == "http" else 200, body, 1))
    monkeypatch.setattr(sys, "argv", ["benchmark", "--scenarios", "case.json", "--output", "report.json"])
    assert benchmark.main() == (0 if failure is None else 1)
