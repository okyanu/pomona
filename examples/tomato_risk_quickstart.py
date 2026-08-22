#!/usr/bin/env python3
"""Send a real greenhouse sensor scenario to Pomona's tomato risk reasoner.

Requires the platform running locally (see README quickstart):

    ./scripts/up.sh
    python3 examples/tomato_risk_quickstart.py

No extra Python packages and no files under private/ are required.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCENARIO_FILE = Path(__file__).parent / "scenarios" / "arizona_tomato.json"
MODEL_ROUTER_URL = "http://localhost:8081/v1/reasoners/tomato-risk"


def build_reasoner_input(scenario: dict) -> dict:
    farm_context = scenario["farm_context"]
    sensor = {key: value for key, value in scenario["sensor"].items() if key != "timestamp"}
    return {
        "system_type": farm_context["system_type"],
        "crop": farm_context["crop"],
        "growth_stage": farm_context["growth_stage"],
        **sensor,
    }


def main() -> int:
    scenario = json.loads(SCENARIO_FILE.read_text())
    reasoner_input = build_reasoner_input(scenario)

    payload = {"mode": "hybrid_guarded", "input": reasoner_input}
    request = urllib.request.Request(
        MODEL_ROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    print(f"Scenario: {scenario['scenario_id']} — {scenario['label']}")
    print(f"Sensor input:\n{json.dumps(reasoner_input, indent=2)}\n")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        print(f"Could not reach model-router at {MODEL_ROUTER_URL}: {error}")
        print("Start the platform first with: ./scripts/up.sh")
        return 1

    print(f"Tomato risk reasoner response:\n{json.dumps(result, indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
