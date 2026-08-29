"""YAML automation rules -> suggestions only.

Defense in depth: even if a rule's YAML were edited to name a forbidden
actuator/chemical action, load_rules rejects it at startup. This mirrors the
blocked-action vocabulary used across Pomona's deterministic reasoners
(see services/safety-checker/app/tomato_rules.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

FORBIDDEN_ACTIONS = {
    "direct_pesticide_dosage",
    "autonomous_fertigation_change",
    "direct_actuator_control",
    "definitive_disease_diagnosis",
    "unsafe_chemical_recommendation",
}


class InvalidRuleError(ValueError):
    pass


def load_rules(path: Path) -> List[Dict[str, Any]]:
    raw = yaml.safe_load(path.read_text()) or {}
    rules = raw.get("rules") or []
    if not isinstance(rules, list):
        raise InvalidRuleError("rules.yaml must contain a top-level 'rules' list")

    validated: List[Dict[str, Any]] = []
    seen_ids = set()
    for rule in rules:
        rule_id = rule.get("id")
        action = rule.get("action")
        match_any_labels = rule.get("match_any_labels")
        message = rule.get("message")

        if not rule_id or not isinstance(rule_id, str):
            raise InvalidRuleError(f"rule missing a string 'id': {rule}")
        if rule_id in seen_ids:
            raise InvalidRuleError(f"duplicate rule id: {rule_id}")
        if not action or not isinstance(action, str):
            raise InvalidRuleError(f"rule '{rule_id}' missing a string 'action'")
        if action in FORBIDDEN_ACTIONS:
            raise InvalidRuleError(
                f"rule '{rule_id}' suggests a forbidden action: {action}"
            )
        if not match_any_labels or not isinstance(match_any_labels, list):
            raise InvalidRuleError(f"rule '{rule_id}' missing 'match_any_labels' list")
        if not message or not isinstance(message, str):
            raise InvalidRuleError(f"rule '{rule_id}' missing a string 'message'")

        seen_ids.add(rule_id)
        validated.append(
            {
                "id": rule_id,
                "match_any_labels": list(match_any_labels),
                "action": action,
                "message": message.strip(),
            }
        )
    return validated


def evaluate_rules(rules: List[Dict[str, Any]], risk_labels: List[str]) -> List[Dict[str, Any]]:
    labels = set(risk_labels or [])
    matches = []
    for rule in rules:
        if labels & set(rule["match_any_labels"]):
            matches.append(rule)
    return matches
