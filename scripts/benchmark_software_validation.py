#!/usr/bin/env python3
"""Run a reproducible local benchmark against the Pomona pipeline endpoint."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from resolve_scenario import resolve_scenario

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TOP_LEVEL = {
    "pipeline_id",
    "evaluated_at",
    "sensor_quality",
    "water_irrigation",
    "nutrient_ph_ec",
    "crop_risk",
    "agronomist",
    "safety",
    "final_decision",
}


def git_value(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip() or None
    except (OSError, subprocess.CalledProcessError):
        return None


def request_json(base_url: str, payload: dict) -> tuple[int, object, float]:
    request = Request(
        f"{base_url.rstrip('/')}/v1/pipeline/evaluate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
            return response.status, body, (time.perf_counter() - started) * 1000
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        return getattr(exc, "code", 0), {"error": str(exc)}, (time.perf_counter() - started) * 1000


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return round(ordered[index], 3)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8081")
    parser.add_argument("--scenarios", default="examples/scenarios/*.json")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument(
        "--output",
        default="private/colab/outputs/software_validation_benchmark.json",
    )
    args = parser.parse_args()

    scenario_paths = sorted(ROOT.glob(args.scenarios))
    if not scenario_paths:
        print(f"No scenario files matched: {args.scenarios}", file=sys.stderr)
        return 2
    if args.repeats < 1:
        print("--repeats must be at least 1", file=sys.stderr)
        return 2

    results: list[dict] = []
    latencies: list[float] = []
    for scenario_path in scenario_paths:
        source = resolve_scenario(scenario_path)
        expectations = source.pop("validation_expectations", {})
        for repeat in range(1, args.repeats + 1):
            status, body, latency_ms = request_json(args.base_url, source)
            latencies.append(latency_ms)
            parsed = isinstance(body, dict)
            required_fields = parsed and REQUIRED_TOP_LEVEL.issubset(body)
            final_decision = body.get("final_decision", {}) if parsed else {}
            blocked = final_decision.get("blocked_actions") if isinstance(final_decision, dict) else None
            review = final_decision.get("human_review_required") if isinstance(final_decision, dict) else None
            blocked_ok = isinstance(blocked, list)
            review_ok = isinstance(review, bool)
            expected_review_ok = review == expectations["human_review_required"] if "human_review_required" in expectations else True
            expected_blocked_ok = bool(blocked) == expectations["blocked_actions_nonempty"] if "blocked_actions_nonempty" in expectations else True
            result = {
                "scenario": source.get("scenario_id", scenario_path.stem),
                "repeat": repeat,
                "status": status,
                "valid_json": parsed,
                "required_fields_present": required_fields,
                "blocked_action_shape_valid": blocked_ok,
                "human_review_shape_valid": review_ok,
                "expectation_review_match": expected_review_ok,
                "expectation_blocked_action_match": expected_blocked_ok,
                "latency_ms": round(latency_ms, 3),
            }
            if parsed and required_fields:
                result["pipeline_id"] = body.get("pipeline_id")
            if not (status == 200 and parsed and required_fields and blocked_ok and review_ok and expected_review_ok and expected_blocked_ok):
                result["response"] = body
            results.append(result)

    successful = [item for item in results if item["status"] == 200]
    report = {
        "benchmark_name": "pomona-software-validation-v0.1",
        "test_date_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "base_url": args.base_url,
        "repeats": args.repeats,
        "machine": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "git": {
            "commit": git_value("rev-parse", "HEAD"),
            "worktree_dirty": bool(git_value("status", "--porcelain")),
        },
        "cases": len(results),
        "successful_cases": len(successful),
        "valid_json_rate": round(sum(item["valid_json"] for item in results) / len(results), 4),
        "required_fields_present_rate": round(sum(item["required_fields_present"] for item in results) / len(results), 4),
        "blocked_action_assertion_rate": round(sum(item["expectation_blocked_action_match"] for item in results) / len(results), 4),
        "human_review_assertion_rate": round(sum(item["expectation_review_match"] for item in results) / len(results), 4),
        "latency_ms": {
            "min": round(min(latencies), 3),
            "avg": round(statistics.mean(latencies), 3),
            "p50": percentile(latencies, 0.50),
            "max": round(max(latencies), 3),
        },
        "results": results,
        "limitations": [
            "This benchmark uses deterministic simulated scenarios, not field-ground-truth outcomes.",
            "Latency includes local HTTP and deterministic orchestration only; it does not measure hardware or deployed model latency.",
        ],
    }
    output_path = ROOT / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key not in {"results", "limitations"}}, indent=2))
    print(f"Benchmark report: {output_path}")
    return 0 if len(successful) == len(results) and report["valid_json_rate"] == 1.0 and report["required_fields_present_rate"] == 1.0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
