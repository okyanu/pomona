"""Pomona automation engine -- suggestions only, never direct actuator control.

Evaluates YAML rules against a guarded reasoner's risk labels and produces
human-approvable suggestions. Approving a suggestion only records a
decision; there is no execution path to any hardware or actuator in v0.1.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
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


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def landing() -> str:
    return """<!doctype html>
<html>
<head>
<title>Pomona Automation Engine</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    max-width: 640px;
    margin: 4rem auto;
    padding: 0 1.25rem 4rem;
    line-height: 1.6;
  }
  h1 { font-size: 1.5rem; margin-bottom: 0.4rem; }
  p.lede { color: #8a8578; margin-top: 0; }
  .pill {
    display: inline-block;
    font-size: 0.78rem;
    border: 1px solid currentColor;
    border-radius: 3px;
    padding: 0.2rem 0.6rem;
    opacity: 0.7;
    margin-bottom: 1.5rem;
  }
  a {
    display: block;
    padding: 0.7rem 0.9rem;
    margin-bottom: 0.5rem;
    border: 1px solid #8a85781f;
    border-radius: 4px;
    text-decoration: none;
    color: inherit;
  }
  a:hover { border-color: currentColor; }
</style>
</head>
<body>
<h1>Pomona Automation Engine</h1>
<p class="lede">YAML-rule automation suggestions &mdash; suggestions only, never direct actuator control.</p>
<span class="pill">v0.1</span>
<a href="/docs">/docs &nbsp;&rarr;&nbsp; Swagger UI</a>
<a href="/redoc">/redoc &nbsp;&rarr;&nbsp; ReDoc reference</a>
<a href="/health">/health &nbsp;&rarr;&nbsp; Health check</a>
</body>
</html>"""


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
