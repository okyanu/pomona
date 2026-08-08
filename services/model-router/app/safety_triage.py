"""Advisory safety-triage route using the deterministic safety policy."""

from __future__ import annotations

from typing import Any, Dict

from app.shared_chain import derive_actuator_gate


GATE_TO_TRIAGE_LABEL = {
    "safe_observation_only": "safe_observation_only",
    "safe_manual_check": "safe_manual_check",
    "human_approval_required": "human_review_required",
    "direct_actuator_control_request": "direct_actuator_control_request",
    "autonomous_fertigation_change": "autonomous_fertigation_change",
    "irrigation_control_request": "direct_actuator_control_request",
    "climate_control_request": "direct_actuator_control_request",
    "chemical_application_request": "pesticide_dosage_request",
    "unsafe_chemical_recommendation": "unsafe_chemical_recommendation",
    "definitive_disease_diagnosis": "definitive_disease_diagnosis",
    "missing_or_bad_sensor_data": "ignores_missing_data",
    "actuator_conflict": "human_review_required",
}


def route_safety_triage_reasoner(
    input_data: Dict[str, Any],
    mode: str,
    model_id: str,
) -> Dict[str, Any]:
    selected_mode = mode.strip().lower()
    if selected_mode == "model_only":
        raise NotImplementedError(
            "Safety-triage LoRA inference is not wired yet; use rules_only or hybrid_guarded."
        )
    if selected_mode not in {"rules_only", "hybrid_guarded"}:
        raise ValueError(f"unsupported safety-triage mode: {mode}")

    gate = derive_actuator_gate(input_data)
    labels = list(dict.fromkeys(GATE_TO_TRIAGE_LABEL[label] for label in gate["gate_labels"]))
    safe_alternative = " ".join(gate["safe_alternatives"])
    return {
        "model_id": model_id,
        "mode": selected_mode,
        "source": "deterministic_safety_rules",
        "safety_labels": labels,
        "blocked_actions": gate["blocked_actions"],
        "safe_alternative": safe_alternative,
        "human_review_required": gate["human_approval_required"],
        "rationale": gate["rationale"],
        "fallback_reason": (
            "The advisory triage model is not configured; deterministic safety rules were used."
            if selected_mode == "hybrid_guarded"
            else None
        ),
    }
