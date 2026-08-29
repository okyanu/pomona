"""Pomona automation engine -- suggestions only, never direct actuator control.

Evaluates YAML rules against a guarded reasoner's risk labels and produces
human-approvable suggestions. Approving a suggestion only records a
decision; there is no execution path to any hardware or actuator in v0.1.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.rules import InvalidRuleError, evaluate_rules, load_rules
from app.store import suggestion_store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)

try:
    RULES = load_rules(settings.rules_path)
except InvalidRuleError as exc:
    logger.error("Refusing to start: invalid automation rules: %s", exc)
    raise


class HealthResponse(BaseModel):
    status: str
    service: str
    rules_loaded: int


class EvaluateRequest(BaseModel):
    risk_labels: List[str] = Field(default_factory=list)
    blocked_actions: List[str] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)


class Suggestion(BaseModel):
    id: str
    rule_id: str
    action: str
    message: str
    context: Dict[str, Any]
    requires_approval: bool
    status: str
    created_at: str
    decided_at: Optional[str] = None


class EvaluateResponse(BaseModel):
    suggestions: List[Suggestion]


class SuggestionListResponse(BaseModel):
    count: int
    suggestions: List[Suggestion]


app = FastAPI(
    title="Pomona Automation Engine",
    version="0.1.0",
    description="YAML-rule automation suggestions. Suggestions only -- never direct actuator control.",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="pomona-automation-engine", rules_loaded=len(RULES))


@app.post("/v1/automation/evaluate", response_model=EvaluateResponse)
def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    matched_rules = evaluate_rules(RULES, request.risk_labels)
    created: List[Dict[str, Any]] = []
    for rule in matched_rules:
        suggestion = suggestion_store.add(
            rule_id=rule["id"],
            action=rule["action"],
            message=rule["message"],
            context=request.context,
        )
        created.append(suggestion)

    logger.info(
        "automation evaluate risk_labels=%s matched_rules=%s",
        ",".join(request.risk_labels) or "none",
        ",".join(rule["id"] for rule in matched_rules) or "none",
    )
    return EvaluateResponse(suggestions=created)


@app.get("/v1/automation/suggestions", response_model=SuggestionListResponse)
def list_suggestions(status: Optional[str] = Query(default=None)) -> SuggestionListResponse:
    if status is not None and status not in {"pending", "approved", "rejected"}:
        raise HTTPException(status_code=422, detail="status must be pending, approved, or rejected")
    suggestions = suggestion_store.list(status=status)
    return SuggestionListResponse(count=len(suggestions), suggestions=suggestions)


@app.post("/v1/automation/suggestions/{suggestion_id}/approve", response_model=Suggestion)
def approve_suggestion(suggestion_id: str) -> Suggestion:
    suggestion = suggestion_store.decide(suggestion_id, "approved")
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    logger.info("suggestion approved id=%s action=%s", suggestion_id, suggestion["action"])
    return Suggestion(**suggestion)


@app.post("/v1/automation/suggestions/{suggestion_id}/reject", response_model=Suggestion)
def reject_suggestion(suggestion_id: str) -> Suggestion:
    suggestion = suggestion_store.decide(suggestion_id, "rejected")
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    logger.info("suggestion rejected id=%s action=%s", suggestion_id, suggestion["action"])
    return Suggestion(**suggestion)
