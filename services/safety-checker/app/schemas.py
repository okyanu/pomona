from typing import Any, Dict, List

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str
    ruleset: str


class TomatoRiskCheckRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Normalized Pomona tomato greenhouse input.")


class TomatoRiskCheckResponse(BaseModel):
    risk_labels: List[str]
    missing_data: List[str]
    safe_next_checks: List[str]
    blocked_actions: List[str]
    human_review_required: bool


class ActuatorGateCheckRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Pomona proposed command with farm, risk, and sensor-quality context.")


class ActuatorGateCheckResponse(BaseModel):
    decision: str
    gate_labels: List[str]
    blocked_actions: List[str]
    human_approval_required: bool
    safe_alternatives: List[str]
    rationale: str
