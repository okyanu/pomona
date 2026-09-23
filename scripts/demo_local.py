"""Offline tomato walkthrough using real pipeline/rule code, no server or approvals.

Run with services/model-router/.venv/bin/python scripts/demo_local.py.
"""
import asyncio
import importlib.util
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/model-router"))


async def demo():
    from app.config import settings
    from app.pipeline import evaluate_pipeline

    # Force offline operation even if the owner's .env selects a live model.
    settings.pomona_llm_backend = "stub"
    settings.reasoner_backend = "rules"
    spec = importlib.util.spec_from_file_location("demo_rules", ROOT / "services/automation-engine/app/rules.py")
    rules_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rules_module)
    rules = rules_module.load_rules(ROOT / "services/automation-engine/app/rules.yaml")
    base = {"air_temperature_c": 24, "humidity_pct": 60, "ph": 6,
            "ec_ms_cm": 2, "substrate_moisture_pct": 50, "substrate_temperature_c": 23,
            "timestamp": datetime.now(timezone.utc).isoformat()}
    scenarios = {
        "routine": base,
        "high_ec_and_humidity": {**base, "ec_ms_cm": 4.5, "humidity_pct": 92},
        "missing_ph": {k: v for k, v in base.items() if k != "ph"},
    }
    with tempfile.TemporaryDirectory(prefix="pomona-demo-") as directory:
        settings.audit_log_path = Path(directory) / "audit.jsonl"
        for name, sensor in scenarios.items():
            result = await evaluate_pipeline(
                farm_context={"crop": "tomato", "growth_stage": "fruiting",
                              "system_type": "greenhouse_substrate", "zone_id": "demo-a"},
                sensor=sensor, expected_fields=["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "substrate_moisture_pct"],
                proposed_command={"action_type": "continue_monitoring"}, actor="offline_demo",
                mode="rules_only", scenario_id=name,
            )
            labels = []
            for section, key in [("sensor_quality", "data_quality_labels"), ("water_irrigation", "irrigation_risk_labels"),
                                 ("nutrient_ph_ec", "nutrient_risk_labels"), ("crop_risk", "risk_labels")]:
                labels.extend(result.get(section, {}).get(key, []))
            suggestions = rules_module.evaluate_rules(rules, labels)
            if name == "routine":
                assert result["final_decision"]["risk_level"] == "routine"
                assert not suggestions
            elif name == "missing_ph":
                assert result["final_decision"]["human_review_required"]
            else:
                assert suggestions
            print(json.dumps({"scenario": name, "sensor": sensor, "labels": labels,
                              "safety_decision": result["final_decision"],
                              "suggestions": [{"action": s["action"], "message": s["message"]} for s in suggestions],
                              "demo_only": True, "approval_available": False}, indent=2))
    print("Demo complete. No network requests, saved suggestions, approvals, or actuator commands.")


if __name__ == "__main__":
    asyncio.run(demo())
