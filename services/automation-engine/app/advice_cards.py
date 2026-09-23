"""Map automation suggestions to HITL advice cards (CottonBot-style)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


SEVERITY_BY_ACTION = {
    "check_water_system": "warn",
    "review_nutrient_dosing": "warn",
    "consider_ventilation": "info",
    "inspect_canopy": "info",
    "check_irrigation_system": "warn",
}


def suggestion_to_advice_card(suggestion: Dict[str, Any]) -> Dict[str, Any]:
    context = suggestion.get("context") or {}
    action = suggestion.get("action") or "review"
    status = suggestion.get("status") or "pending"
    blocked = list(context.get("blocked_actions") or [])
    if "autonomous_irrigation_change" not in blocked:
        blocked.append("autonomous_irrigation_change")
    if "irrigation_schedule_change" not in blocked:
        blocked.append("irrigation_schedule_change")
    return {
        "card_id": suggestion.get("id"),
        "created_at": suggestion.get("created_at"),
        "expires_at": suggestion.get("expires_at"),
        "opportunity": context.get("opportunity") or "operations",
        "title": suggestion.get("message") or action,
        "summary": suggestion.get("message") or action,
        "severity": SEVERITY_BY_ACTION.get(action, "warn"),
        "evidence": {
            "sample_time": context.get("sensor_timestamp"),
            "zone_id": context.get("zone_id"),
            "farm_id": context.get("farm_id"),
            "readings": context.get("readings") or {},
            "reasoner_ids": context.get("reasoner_ids") or [],
            "sensor_quality_labels": context.get("sensor_quality_labels") or [],
            "risk_labels": context.get("risk_labels") or [],
        },
        "safe_next_checks": context.get("safe_next_checks")
        or ["confirm sensors are not stuck or flatlined", "review suggestion before acting"],
        "blocked_actions": blocked,
        "suggestion_id": suggestion.get("id"),
        "human_review_required": True,
        "status": status,
    }


def suggestions_to_advice_cards(
    suggestions: List[Dict[str, Any]],
    *,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    cards = [suggestion_to_advice_card(item) for item in suggestions]
    if status is None:
        return cards
    return [card for card in cards if card.get("status") == status]
