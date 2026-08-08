"""Deterministic shared reasoner chain for the first platform integration slice."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any, Dict, List

from app.sensor_quality import derive_sensor_quality
from app.water_irrigation import derive_water_irrigation_risk


_MODULE_PATH = Path(__file__).resolve()
ROOT = _MODULE_PATH.parents[3] if len(_MODULE_PATH.parents) > 3 else Path("/app")
_REPO_SAFETY_RULES = ROOT / "services" / "safety-checker" / "app" / "actuator_gate_rules.py"
_CONTAINER_SAFETY_RULES = Path("/app/safety_checker_rules/actuator_gate_rules.py")
SAFETY_RULES = _REPO_SAFETY_RULES if _REPO_SAFETY_RULES.exists() else _CONTAINER_SAFETY_RULES


def _load_actuator_rules():
    spec = importlib.util.spec_from_file_location("pomona_actuator_gate_rules", SAFETY_RULES)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load actuator safety rules from {SAFETY_RULES}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.derive_actuator_gate


derive_actuator_gate = _load_actuator_rules()


def run_shared_reasoner_chain(
    farm_context: Dict[str, Any],
    sensor: Dict[str, Any],
    expected_fields: List[str],
    proposed_command: Dict[str, Any] | None,
    actor: str,
    mode: str,
) -> Dict[str, Any]:
    """Run quality, water-risk, and actuator safety in dependency order."""
    selected = mode.strip().lower()
    if selected not in {"rules_only", "hybrid_guarded"}:
        raise NotImplementedError("shared chain model_only mode is not wired yet")

    quality_input = {
        "farm_context": farm_context,
        "sensor": sensor,
        "expected_fields": expected_fields,
    }
    quality = derive_sensor_quality(
        farm_context,
        sensor,
        expected_fields,
    )

    water = derive_water_irrigation_risk(quality_input)
    safety_input = {
        "farm_context": farm_context,
        "sensor": sensor,
        "sensor_quality": quality,
        "risk_labels": water["irrigation_risk_labels"],
        "actor": actor,
        "proposed_command": proposed_command or {"action_type": "continue_monitoring"},
    }
    safety = derive_actuator_gate(safety_input)
    blocked_actions = list(dict.fromkeys([*water["blocked_actions"], *safety["blocked_actions"]]))
    review_required = bool(
        quality["human_review_required"]
        or water["human_review_required"]
        or safety["human_approval_required"]
    )

    return {
        "mode": selected,
        "source": "deterministic_shared_chain",
        "sensor_quality": quality,
        "water_irrigation": water,
        "actuator_safety": safety,
        "blocked_actions": blocked_actions,
        "human_review_required": review_required,
        "fallback_reason": (
            "Shared specialist runtimes are not configured; deterministic rules were used."
            if selected == "hybrid_guarded"
            else None
        ),
    }
