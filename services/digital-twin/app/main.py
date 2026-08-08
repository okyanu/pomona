from __future__ import annotations

from typing import Any, Dict, List

from fastapi import FastAPI
from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    service: str


class ScenarioRequest(BaseModel):
    state: Dict[str, Any] = Field(..., description="Current normalized sensor state.")
    scenario: Dict[str, Any] = Field(
        default_factory=dict,
        description="Forecast-only changes such as temperature_delta_c or irrigation_duration_min.",
    )
    horizon_steps: int = Field(default=6, ge=1, le=48)
    step_minutes: int = Field(default=15, ge=1, le=1440)


class ScenarioResponse(BaseModel):
    mode: str
    safety_note: str
    assumptions: List[str]
    trajectory: List[Dict[str, Any]]


app = FastAPI(
    title="Pomona Digital Twin",
    version="0.1.0",
    description="Forecast-only greenhouse scenario simulation; never controls actuators.",
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="pomona-digital-twin")


def number(value: Any, fallback: float) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else fallback


@app.post("/v1/digital-twin/scenarios/simulate", response_model=ScenarioResponse)
def simulate(request: ScenarioRequest) -> ScenarioResponse:
    state = dict(request.state)
    scenario = request.scenario
    temperature_delta = number(scenario.get("temperature_delta_c"), 0.0)
    humidity_delta = number(scenario.get("humidity_delta_pct"), 0.0)
    moisture_delta = number(scenario.get("moisture_delta_pct"), 0.0)
    irrigation_duration = number(scenario.get("irrigation_duration_min"), 0.0)
    ventilation = number(scenario.get("ventilation_pct"), 0.0)
    trajectory: List[Dict[str, Any]] = []
    assumptions = [
        "This is a bounded forecast, not a measurement or actuator command.",
        "Temperature, humidity, and moisture changes are linear approximations.",
        "Real sensor feedback must be checked before any operational decision.",
    ]
    if irrigation_duration:
        assumptions.append("Irrigation effect is represented as a moisture trend only.")
    if ventilation:
        assumptions.append("Ventilation effect is represented as a humidity trend only.")

    for step in range(1, request.horizon_steps + 1):
        fraction = step / request.horizon_steps
        predicted = dict(state)
        if "air_temperature_c" in state:
            predicted["air_temperature_c"] = round(number(state.get("air_temperature_c"), 0.0) + temperature_delta * fraction, 2)
        if "humidity_pct" in state:
            predicted["humidity_pct"] = round(max(0.0, min(100.0, number(state.get("humidity_pct"), 0.0) + (humidity_delta - ventilation * 0.05) * fraction)), 2)
        moisture_key = next((key for key in ("substrate_moisture_pct", "soil_moisture_pct", "root_zone_moisture_pct") if key in state), None)
        if moisture_key:
            predicted[moisture_key] = round(max(0.0, min(100.0, number(state.get(moisture_key), 0.0) + (moisture_delta + irrigation_duration * 0.2) * fraction)), 2)
        predicted["step"] = step
        predicted["minutes_from_now"] = step * request.step_minutes
        trajectory.append(predicted)

    return ScenarioResponse(
        mode="forecast_only",
        safety_note="Never execute this trajectory directly. Validate with live sensors and the safety checker; human approval is required for operational changes.",
        assumptions=assumptions,
        trajectory=trajectory,
    )
