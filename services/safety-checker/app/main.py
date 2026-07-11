import logging

from fastapi import FastAPI

from app.actuator_gate_rules import derive_actuator_gate
from app.schemas import (
    ActuatorGateCheckRequest,
    ActuatorGateCheckResponse,
    HealthResponse,
    TomatoRiskCheckRequest,
    TomatoRiskCheckResponse,
)
from app.tomato_rules import derive_tomato_risk

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


app = FastAPI(
    title="Pomona Safety Checker",
    version="0.1.0",
    description="Deterministic safety checks for Pomona greenhouse risk outputs.",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="pomona-safety-checker",
        ruleset="tomato-greenhouse-v0.1",
    )


@app.post("/v1/tomato-risk/check", response_model=TomatoRiskCheckResponse)
def check_tomato_risk(request: TomatoRiskCheckRequest) -> TomatoRiskCheckResponse:
    result = derive_tomato_risk(request.input)
    logger.info(
        "tomato risk check crop=%s risks=%s review=%s",
        request.input.get("crop"),
        ",".join(result["risk_labels"]) or "none",
        result["human_review_required"],
    )
    return TomatoRiskCheckResponse(**result)


@app.post("/v1/actuator-command-gate/check", response_model=ActuatorGateCheckResponse)
def check_actuator_command_gate(request: ActuatorGateCheckRequest) -> ActuatorGateCheckResponse:
    result = derive_actuator_gate(request.input)
    logger.info(
        "actuator gate decision=%s labels=%s",
        result["decision"],
        ",".join(result["gate_labels"]) or "none",
    )
    return ActuatorGateCheckResponse(**result)
