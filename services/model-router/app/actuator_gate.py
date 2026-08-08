"""Advisory actuator-gate route backed by Pomona's deterministic safety rules."""

from __future__ import annotations

from typing import Any, Dict

from app.shared_chain import derive_actuator_gate


def route_actuator_gate_reasoner(
    input_data: Dict[str, Any],
    mode: str,
    model_id: str,
) -> Dict[str, Any]:
    selected_mode = mode.strip().lower()
    if selected_mode == "model_only":
        raise NotImplementedError(
            "Actuator-gate LoRA inference is not wired yet; use rules_only or hybrid_guarded."
        )
    if selected_mode not in {"rules_only", "hybrid_guarded"}:
        raise ValueError(f"unsupported actuator-gate mode: {mode}")

    result = derive_actuator_gate(input_data)
    return {
        "model_id": model_id,
        "mode": selected_mode,
        "source": "deterministic_safety_rules",
        **result,
        "fallback_reason": (
            "The advisory gate model is not configured; deterministic safety rules were used."
            if selected_mode == "hybrid_guarded"
            else None
        ),
    }
