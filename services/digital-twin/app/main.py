from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict, Field, model_validator


class HealthResponse(BaseModel):
    status: str
    service: str


class GreenhouseState(BaseModel):
    """Validated sensor state while preserving contextual event metadata."""

    model_config = ConfigDict(extra="allow")

    air_temperature_c: Optional[float] = Field(default=None, ge=-40.0, le=80.0)
    humidity_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    soil_moisture_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    substrate_moisture_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    root_zone_moisture_pct: Optional[float] = Field(default=None, ge=0.0, le=100.0)

    @model_validator(mode="after")
    def require_supported_measurement(self) -> "GreenhouseState":
        supported = (
            self.air_temperature_c,
            self.humidity_pct,
            self.soil_moisture_pct,
            self.substrate_moisture_pct,
            self.root_zone_moisture_pct,
        )
        if all(value is None for value in supported):
            raise ValueError("state must include at least one supported greenhouse measurement")
        return self


class ScenarioParameters(BaseModel):
    """Allowlisted, bounded forecast parameters; never actuator commands."""

    model_config = ConfigDict(extra="forbid")

    temperature_delta_c: float = Field(default=0.0, ge=-30.0, le=30.0)
    humidity_delta_pct: float = Field(default=0.0, ge=-100.0, le=100.0)
    moisture_delta_pct: float = Field(default=0.0, ge=-100.0, le=100.0)
    irrigation_duration_min: float = Field(default=0.0, ge=0.0, le=240.0)
    ventilation_pct: float = Field(default=0.0, ge=0.0, le=100.0)


class ScenarioRequest(BaseModel):
    state: GreenhouseState = Field(..., description="Current normalized sensor state.")
    scenario: ScenarioParameters = Field(
        default_factory=ScenarioParameters,
        description="Allowlisted forecast-only changes; these are not actuator commands.",
    )
    horizon_steps: int = Field(default=6, ge=1, le=48)
    step_minutes: int = Field(default=15, ge=1, le=1440)


class ScenarioResponse(BaseModel):
    mode: str
    model_id: str
    generated_at: datetime
    baseline: Dict[str, Any]
    scenario: Dict[str, float]
    horizon_minutes: int
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
    state = request.state.model_dump(exclude_none=True)
    scenario = request.scenario
    temperature_delta = scenario.temperature_delta_c
    humidity_delta = scenario.humidity_delta_pct
    moisture_delta = scenario.moisture_delta_pct
    irrigation_duration = scenario.irrigation_duration_min
    ventilation = scenario.ventilation_pct
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
        model_id="pomona-digital-twin-linear-v0",
        generated_at=datetime.now(timezone.utc),
        baseline=state,
        scenario=scenario.model_dump(),
        horizon_minutes=request.horizon_steps * request.step_minutes,
        safety_note="Never execute this trajectory directly. Validate with live sensors and the safety checker; human approval is required for operational changes.",
        assumptions=assumptions,
        trajectory=trajectory,
    )
