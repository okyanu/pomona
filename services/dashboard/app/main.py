from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    dashboard_host: str = "0.0.0.0"
    dashboard_port: int = 3000
    core_url: str = "http://localhost:8080"
    model_router_url: str = "http://localhost:8081"
    safety_checker_url: str = "http://localhost:8082"
    digital_twin_url: str = "http://localhost:8084"


settings = Settings()


class HealthResponse(BaseModel):
    status: str
    service: str
    core_url: str


class OverviewResponse(BaseModel):
    core_available: bool
    latest_event: Optional[Dict[str, Any]] = None
    recent_events: List[Dict[str, Any]] = []
    error: Optional[str] = None


class RiskResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PipelineResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AuditResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class SafetyResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ServiceStatusResponse(BaseModel):
    services: Dict[str, Dict[str, Any]]


class RuntimeStatusResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class ExplanationResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DigitalTwinResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class DigitalTwinScenarioRequest(BaseModel):
    temperature_delta_c: float = Field(default=2.0, ge=-30.0, le=30.0)
    humidity_delta_pct: float = Field(default=5.0, ge=-100.0, le=100.0)
    moisture_delta_pct: float = Field(default=0.0, ge=-100.0, le=100.0)
    irrigation_duration_min: float = Field(default=0.0, ge=0.0, le=240.0)
    ventilation_pct: float = Field(default=0.0, ge=0.0, le=100.0)
    horizon_steps: int = Field(default=4, ge=1, le=48)
    step_minutes: int = Field(default=15, ge=1, le=1440)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="Pomona Dashboard",
    version="0.1.0",
    description="Read-only local dashboard for Pomona sensor state.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="pomona-dashboard", core_url=settings.core_url)


@app.get("/api/overview", response_model=OverviewResponse)
async def overview() -> OverviewResponse:
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
            response = await client.get("/v1/sensors/events", params={"limit": 20})
            response.raise_for_status()
            payload = response.json()
        events = payload.get("events") or []
        return OverviewResponse(
            core_available=True,
            latest_event=events[-1] if events else None,
            recent_events=list(reversed(events)),
        )
    except Exception as exc:
        return OverviewResponse(core_available=False, error=f"Core unavailable: {exc}")


@app.get("/api/risk", response_model=RiskResponse)
async def risk() -> RiskResponse:
    overview_data = await overview()
    if not overview_data.core_available or not overview_data.latest_event:
        return RiskResponse(available=False, error="No persisted sensor event is available.")

    event = overview_data.latest_event
    sensor = dict(event)
    sensor.pop("source", None)
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=5.0) as client:
            response = await client.post(
                "/v1/reasoners/shared-chain",
                json={
                    "farm_context": {
                        "crop": event.get("crop", "tomato"),
                        "system_type": event.get("system_type", "greenhouse_substrate"),
                        "zone_id": event.get("zone_id", "unknown"),
                    },
                    "sensor": sensor,
                    "expected_fields": [
                        "air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "soil_moisture_pct"
                    ],
                    "proposed_command": {"action_type": "continue_monitoring"},
                    "actor": "dashboard",
                    "mode": "hybrid_guarded",
                },
            )
            response.raise_for_status()
        return RiskResponse(available=True, result=response.json())
    except Exception as exc:
        return RiskResponse(available=False, error=f"Reasoner chain unavailable: {exc}")


@app.get("/api/pipeline", response_model=PipelineResponse)
async def pipeline() -> PipelineResponse:
    """Return the unified guarded pipeline for the latest persisted event."""
    overview_data = await overview()
    if not overview_data.core_available or not overview_data.latest_event:
        return PipelineResponse(available=False, error="No persisted sensor event is available.")

    event = dict(overview_data.latest_event)
    event.pop("source", None)
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=10.0) as client:
            response = await client.post(
                "/v1/pipeline/evaluate",
                json={
                    "scenario_id": "dashboard-latest-event",
                    "farm_context": {
                        "crop": event.get("crop", "tomato"),
                        "system_type": event.get("system_type", "greenhouse_substrate"),
                        "zone_id": event.get("zone_id", "unknown"),
                    },
                    "sensor": event,
                    "expected_fields": [
                        "air_temperature_c", "humidity_pct", "ph", "ec_ms_cm", "soil_moisture_pct"
                    ],
                    "proposed_command": {"action_type": "continue_monitoring"},
                    "actor": "dashboard",
                    "mode": "hybrid_guarded",
                },
            )
            response.raise_for_status()
        return PipelineResponse(available=True, result=response.json())
    except Exception as exc:
        return PipelineResponse(available=False, error=f"Integrated pipeline unavailable: {exc}")


@app.get("/api/audit", response_model=AuditResponse)
async def audit() -> AuditResponse:
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=3.0) as client:
            response = await client.get("/v1/pipeline/audit", params={"limit": 20})
            response.raise_for_status()
        return AuditResponse(available=True, result=response.json())
    except Exception as exc:
        return AuditResponse(available=False, error=f"Pipeline audit unavailable: {exc}")


@app.get("/api/safety", response_model=SafetyResponse)
async def safety() -> SafetyResponse:
    overview_data = await overview()
    if not overview_data.core_available or not overview_data.latest_event:
        return SafetyResponse(available=False, error="No persisted sensor event is available.")

    event = overview_data.latest_event
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=5.0) as client:
            response = await client.post(
                "/v1/reasoners/safety-triage",
                json={
                    "mode": "hybrid_guarded",
                    "input": {
                        "farm_context": {
                            "crop": event.get("crop", "tomato"),
                            "system_type": "controlled_greenhouse",
                            "zone_id": event.get("zone_id", "unknown"),
                        },
                        "sensor": event,
                        "risk_labels": [],
                        "actor": "dashboard",
                        "proposed_action": {"action_type": "continue_monitoring"},
                    },
                },
            )
            response.raise_for_status()
        return SafetyResponse(available=True, result=response.json())
    except Exception as exc:
        return SafetyResponse(available=False, error=f"Safety triage unavailable: {exc}")


@app.get("/api/services", response_model=ServiceStatusResponse)
async def service_status() -> ServiceStatusResponse:
    targets = {
        "core": settings.core_url,
        "model_router": settings.model_router_url,
        "safety_checker": settings.safety_checker_url,
    }
    statuses: Dict[str, Dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=2.0) as client:
        for name, base_url in targets.items():
            try:
                response = await client.get(f"{base_url.rstrip('/')}/health")
                response.raise_for_status()
                statuses[name] = {"available": True, "health": response.json()}
            except Exception as exc:
                statuses[name] = {"available": False, "error": str(exc)}
    return ServiceStatusResponse(services=statuses)


@app.get("/api/runtimes", response_model=RuntimeStatusResponse)
async def runtime_status() -> RuntimeStatusResponse:
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=3.0) as client:
            response = await client.get("/v1/runtimes")
            response.raise_for_status()
        return RuntimeStatusResponse(available=True, result=response.json())
    except Exception as exc:
        return RuntimeStatusResponse(available=False, error=f"Runtime status unavailable: {exc}")


async def _digital_twin_preview(request: DigitalTwinScenarioRequest) -> DigitalTwinResponse:
    """Run a bounded forecast and validate its endpoint against guarded rules."""
    overview_data = await overview()
    if not overview_data.core_available or not overview_data.latest_event:
        return DigitalTwinResponse(available=False, error="No persisted sensor event is available.")

    event = dict(overview_data.latest_event)
    event.pop("source", None)
    try:
        async with httpx.AsyncClient(base_url=settings.digital_twin_url, timeout=5.0) as client:
            response = await client.post(
                "/v1/digital-twin/scenarios/simulate",
                json={
                    "state": event,
                    "scenario": {
                        "temperature_delta_c": request.temperature_delta_c,
                        "humidity_delta_pct": request.humidity_delta_pct,
                        "moisture_delta_pct": request.moisture_delta_pct,
                        "irrigation_duration_min": request.irrigation_duration_min,
                        "ventilation_pct": request.ventilation_pct,
                    },
                    "horizon_steps": request.horizon_steps,
                    "step_minutes": request.step_minutes,
                },
            )
            response.raise_for_status()
        forecast = response.json()
        trajectory = forecast.get("trajectory") or []
        final_state = dict(trajectory[-1]) if trajectory else event
        final_state.pop("step", None)
        final_state.pop("minutes_from_now", None)
        expected_fields = [
            field for field in (
                "air_temperature_c",
                "humidity_pct",
                "ph",
                "ec_ms_cm",
                "substrate_moisture_pct",
                "soil_moisture_pct",
                "water_temperature_c",
            ) if field in final_state
        ]
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=10.0) as client:
            guarded = await client.post(
                "/v1/pipeline/evaluate",
                json={
                    "scenario_id": "dashboard-digital-twin-preview",
                    "farm_context": {
                        "crop": event.get("crop", "tomato"),
                        "system_type": event.get("system_type", "greenhouse_substrate"),
                        "zone_id": event.get("zone_id", "unknown"),
                    },
                    "sensor": final_state,
                    "expected_fields": expected_fields,
                    "proposed_command": {"action_type": "continue_monitoring"},
                    "actor": "dashboard_digital_twin_preview",
                    "mode": "hybrid_guarded",
                },
            )
            guarded.raise_for_status()
        forecast["guarded_evaluation"] = guarded.json()
        forecast["scenario"] = request.model_dump()
        return DigitalTwinResponse(available=True, result=forecast)
    except Exception as exc:
        return DigitalTwinResponse(available=False, error=f"Digital Twin unavailable: {exc}")


@app.get("/api/digital-twin", response_model=DigitalTwinResponse)
async def digital_twin() -> DigitalTwinResponse:
    return await _digital_twin_preview(DigitalTwinScenarioRequest())


@app.post("/api/digital-twin", response_model=DigitalTwinResponse)
async def digital_twin_scenario(request: DigitalTwinScenarioRequest) -> DigitalTwinResponse:
    return await _digital_twin_preview(request)


@app.get("/api/explanation", response_model=ExplanationResponse)
async def explanation() -> ExplanationResponse:
    overview_data = await overview()
    if not overview_data.core_available or not overview_data.latest_event:
        return ExplanationResponse(available=False, error="No persisted sensor event is available.")
    risk_data = await risk()
    if not risk_data.available:
        return ExplanationResponse(available=False, error=risk_data.error or "Guarded risk result unavailable.")
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=30.0) as client:
            response = await client.post(
                "/v1/advisor/explain",
                json={
                    "instruction": (
                        "Explain the guarded Pomona sensor and risk result for a grower. "
                        "Give safe next checks only. Do not issue pesticide dosage, fertigation changes, "
                        "actuator commands, or definitive disease diagnoses."
                    ),
                    "sensor": overview_data.latest_event,
                    "guarded_context": risk_data.result,
                    "backend": "stub",
                },
            )
            response.raise_for_status()
        return ExplanationResponse(available=True, result=response.json())
    except Exception as exc:
        return ExplanationResponse(available=False, error=f"Agronomist advisor unavailable: {exc}")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return DASHBOARD_HTML


DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Pomona Control Center</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; }
    body { margin: 0; background: #0d1117; color: #e6edf3; }
    main { max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }
    header { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; border-bottom: 1px solid #30363d; padding-bottom: 20px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0; }
    .status { color: #8b949e; font-size: 14px; }
    .grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }
    .metric { border: 1px solid #30363d; background: #161b22; padding: 18px; min-height: 84px; }
    .label { color: #8b949e; font-size: 13px; }
    .value { font-size: 26px; margin-top: 10px; font-variant-numeric: tabular-nums; }
    section { border-top: 1px solid #30363d; padding-top: 22px; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; padding: 12px 8px; border-bottom: 1px solid #21262d; }
    th { color: #8b949e; font-weight: 500; }
    .empty { color: #8b949e; padding: 28px 0; }
    @media (max-width: 720px) { .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } header { display: block; } .status { display: block; margin-top: 8px; } }
  </style>
</head>
<body>
<main>
  <header><h1>Pomona Control Center</h1><div class="status" id="status">Connecting to services...</div></header>
  <div class="grid">
    <div class="metric"><div class="label">Air temperature</div><div class="value" id="air">--</div></div>
    <div class="metric"><div class="label">Humidity</div><div class="value" id="humidity">--</div></div>
    <div class="metric"><div class="label">pH</div><div class="value" id="ph">--</div></div>
    <div class="metric"><div class="label">EC</div><div class="value" id="ec">--</div></div>
  </div>
  <section><h2>Integrated guarded pipeline</h2><div id="pipeline" class="empty">Loading...</div></section>
  <section><h2>Specialist results</h2><div id="specialists" class="empty">Loading...</div></section>
  <section><h2>Recent pipeline audit</h2><div id="audit" class="empty">Loading...</div></section>
  <section><h2>Guarded risk status</h2><div id="risk" class="empty">Loading...</div></section>
  <section><h2>Safety triage</h2><div id="safety" class="empty">Loading...</div></section>
  <section><h2>Service status</h2><div id="services" class="empty">Loading...</div></section>
  <section><h2>Local runtimes</h2><div id="runtimes" class="empty">Loading...</div></section>
  <section><h2>Digital Twin forecast preview</h2>
    <form id="twin-form" class="grid">
      <label class="metric"><span class="label">Temperature delta (C)</span><input id="twin-temperature" type="number" value="2" min="-30" max="30" step="0.5"></label>
      <label class="metric"><span class="label">Humidity delta (%)</span><input id="twin-humidity" type="number" value="5" min="-100" max="100" step="1"></label>
      <label class="metric"><span class="label">Irrigation duration (min)</span><input id="twin-irrigation" type="number" value="0" min="0" max="240" step="1"></label>
      <label class="metric"><span class="label">Ventilation (%)</span><input id="twin-ventilation" type="number" value="0" min="0" max="100" step="1"></label>
      <label class="metric"><span class="label">Horizon steps</span><input id="twin-horizon" type="number" value="4" min="1" max="48" step="1"></label>
      <button type="submit">Run forecast preview</button>
    </form>
    <div id="digital-twin" class="empty">Loading...</div>
  </section>
  <section><h2>Agronomist note</h2><div id="explanation" class="empty">Loading...</div></section>
  <section><h2>Recent sensor events</h2><div id="events" class="empty">Loading...</div></section>
</main>
<script>
const $ = (id) => document.getElementById(id);
const value = (x, suffix = '') => x === null || x === undefined ? '--' : `${x}${suffix}`;
let twinPreview = null;
async function refresh() {
  const response = await fetch('/api/overview');
  const data = await response.json();
  if (!data.core_available) { $('status').textContent = data.error || 'Core unavailable'; return; }
  $('status').textContent = `Core online · ${data.recent_events.length} recent events`;
  const event = data.latest_event;
  if (event) {
    $('air').textContent = value(event.air_temperature_c, ' °C');
    $('humidity').textContent = value(event.humidity_pct, ' %');
    $('ph').textContent = value(event.ph);
    $('ec').textContent = value(event.ec_ms_cm, ' mS/cm');
  }
  const pipelineResponse = await fetch('/api/pipeline');
  const pipeline = await pipelineResponse.json();
  if (!pipeline.available) {
    $('pipeline').textContent = pipeline.error || 'Integrated pipeline unavailable';
  } else {
    const result = pipeline.result;
    const decision = result.final_decision || {};
    const quality = result.sensor_quality || {};
    const water = result.water_irrigation || {};
    const nutrient = result.nutrient_ph_ec || {};
    const crop = result.crop_risk || {};
    const safety = result.safety || {};
    $('pipeline').innerHTML = `<div class="grid"><div class="metric"><div class="label">Risk level</div><div class="value">${decision.risk_level || '--'}</div></div><div class="metric"><div class="label">Sensor quality</div><div class="value">${(quality.data_quality_labels || []).join(', ') || 'normal'}</div></div><div class="metric"><div class="label">Water / nutrient</div><div class="value">${[...(water.irrigation_risk_labels || []), ...(nutrient.nutrient_risk_labels || [])].join(', ') || 'normal'}</div></div><div class="metric"><div class="label">Human review</div><div class="value">${decision.human_review_required ? 'required' : 'not required'}</div></div></div><p class="status">Pipeline: ${result.pipeline_id || '--'} · Blocked actions: ${(decision.blocked_actions || []).join(', ') || 'none'}</p><p class="status">Read-only dashboard view. No action is executed.</p>`;
    const specialistRows = [
      ['Sensor quality', quality.data_quality_labels || [], quality.source || 'deterministic_rules', quality.human_review_required],
      ['Water / irrigation', water.irrigation_risk_labels || [], water.source || 'deterministic_rules', water.human_review_required],
      ['Nutrient / pH-EC', nutrient.nutrient_risk_labels || [], nutrient.source || 'deterministic_rules', nutrient.human_review_required],
      ['Crop risk', crop.risk_labels || [], crop.source || 'deterministic_rules', crop.human_review_required],
      ['Actuator safety', safety.safety_labels || [], safety.source || 'deterministic_safety_rules', safety.human_approval_required],
    ];
    $('specialists').innerHTML = `<table><thead><tr><th>Specialist</th><th>Labels</th><th>Source</th><th>Review</th></tr></thead><tbody>${specialistRows.map(row => `<tr><td>${row[0]}</td><td>${row[1].join(', ') || 'normal'}</td><td>${row[2]}</td><td>${row[3] ? 'required' : 'not required'}</td></tr>`).join('')}</tbody></table><p class="status">Specialists advise independently; deterministic safety remains final authority. Dashboard view is read-only.</p>`;
  }
  const audit = await (await fetch('/api/audit')).json();
  if (!audit.available) {
    $('audit').textContent = audit.error || 'Pipeline audit unavailable';
  } else if (!(audit.result.events || []).length) {
    $('audit').textContent = 'No pipeline evaluations recorded yet.';
  } else {
    $('audit').innerHTML = `<table><thead><tr><th>Time</th><th>Scenario</th><th>Risk</th><th>Review</th><th>Blocked actions</th></tr></thead><tbody>${audit.result.events.map(e => `<tr><td>${e.evaluated_at || '--'}</td><td>${e.scenario_id || '--'}</td><td>${e.risk_level || '--'}</td><td>${e.human_review_required ? 'required' : 'not required'}</td><td>${(e.blocked_actions || []).join(', ') || 'none'}</td></tr>`).join('')}</tbody></table><p class="status">Audit view contains summaries only; sensor payloads are excluded.</p>`;
  }
  const riskResponse = await fetch('/api/risk');
  const risk = await riskResponse.json();
  if (!risk.available) {
    $('risk').textContent = risk.error || 'Risk chain unavailable';
  } else {
    const result = risk.result;
    const quality = result.sensor_quality || {};
    const water = result.water_irrigation || {};
    const safety = result.actuator_safety || {};
    $('risk').innerHTML = `<div class="grid"><div class="metric"><div class="label">Sensor quality</div><div class="value">${(quality.data_quality_labels || []).join(', ') || 'normal'}</div></div><div class="metric"><div class="label">Water risk</div><div class="value">${(water.irrigation_risk_labels || []).join(', ') || 'normal'}</div></div><div class="metric"><div class="label">Safety decision</div><div class="value">${safety.decision || '--'}</div></div><div class="metric"><div class="label">Human review</div><div class="value">${result.human_review_required ? 'required' : 'not required'}</div></div></div><p class="status">Blocked actions: ${(result.blocked_actions || []).join(', ') || 'none'}</p>`;
  }
  const safetyResponse = await fetch('/api/safety');
  const safetyData = await safetyResponse.json();
  if (!safetyData.available) {
    $('safety').textContent = safetyData.error || 'Safety triage unavailable';
  } else {
    const result = safetyData.result;
    $('safety').innerHTML = `<div class="grid"><div class="metric"><div class="label">Decision</div><div class="value">${result.safety_labels?.includes('human_review_required') ? 'review' : 'allowed'}</div></div><div class="metric"><div class="label">Safety labels</div><div class="value">${(result.safety_labels || []).join(', ') || 'none'}</div></div><div class="metric"><div class="label">Blocked actions</div><div class="value">${(result.blocked_actions || []).join(', ') || 'none'}</div></div><div class="metric"><div class="label">Human review</div><div class="value">${result.human_review_required ? 'required' : 'not required'}</div></div></div><p>${result.safe_alternative || 'Continue routine monitoring.'}</p><p class="status">Dashboard view is read-only. No action is executed.</p>`;
  }
  if (!data.recent_events.length) { $('events').textContent = 'No sensor events recorded yet.'; return; }
  $('events').innerHTML = `<table><thead><tr><th>Time</th><th>Farm</th><th>Zone</th><th>Crop</th><th>Temperature</th><th>Humidity</th></tr></thead><tbody>${data.recent_events.map(e => `<tr><td>${e.timestamp}</td><td>${e.farm_id}</td><td>${e.zone_id}</td><td>${e.crop}</td><td>${value(e.air_temperature_c, ' °C')}</td><td>${value(e.humidity_pct, ' %')}</td></tr>`).join('')}</tbody></table>`;
  const services = await (await fetch('/api/services')).json();
  $('services').innerHTML = `<table><thead><tr><th>Service</th><th>Status</th><th>Detail</th></tr></thead><tbody>${Object.entries(services.services).map(([name, item]) => `<tr><td>${name}</td><td>${item.available ? 'online' : 'offline'}</td><td>${item.available ? (item.health.service || '') : (item.error || '')}</td></tr>`).join('')}</tbody></table>`;
  const runtimes = await (await fetch('/api/runtimes')).json();
  if (!runtimes.available) {
    $('runtimes').textContent = runtimes.error || 'Runtime status unavailable';
  } else {
    $('runtimes').innerHTML = `<table><thead><tr><th>Runtime</th><th>Status</th><th>Configured model</th><th>Models seen</th></tr></thead><tbody>${Object.entries(runtimes.result).map(([name, item]) => `<tr><td>${name}</td><td>${item.available ? 'available' : 'offline'}</td><td>${item.model || 'rules'}</td><td>${(item.models_seen || []).map(model => typeof model === 'string' ? model : (model.id || model.name || '')).filter(Boolean).join(', ') || (item.error || 'none')}</td></tr>`).join('')}</tbody></table>`;
  }
  const twin = twinPreview || await (await fetch('/api/digital-twin')).json();
  twinPreview = null;
  if (!twin.available) {
    $('digital-twin').textContent = twin.error || 'Digital Twin unavailable';
  } else {
    const result = twin.result;
    const trajectory = result.trajectory || [];
    const first = trajectory[0] || {};
    const last = trajectory[trajectory.length - 1] || {};
    const guarded = result.guarded_evaluation || {};
    const decision = guarded.final_decision || {};
    $('digital-twin').innerHTML = `<div class="grid"><div class="metric"><div class="label">Mode</div><div class="value">${result.mode || 'forecast_only'}</div></div><div class="metric"><div class="label">Horizon</div><div class="value">${last.minutes_from_now || 0} min</div></div><div class="metric"><div class="label">Temperature</div><div class="value">${value(first.air_temperature_c)} to ${value(last.air_temperature_c)} °C</div></div><div class="metric"><div class="label">Humidity</div><div class="value">${value(first.humidity_pct)} to ${value(last.humidity_pct)} %</div></div></div><p>Guarded result: ${decision.risk_level || '--'} · Review: ${decision.human_review_required ? 'required' : 'not required'} · Blocked: ${(decision.blocked_actions || []).join(', ') || 'none'}</p><p>${result.safety_note || 'Forecast only. Validate against live sensors.'}</p><p class="status">This preview is illustrative and does not execute or authorize any action.</p>`;
  }
  const explanation = await (await fetch('/api/explanation')).json();
  if (!explanation.available) {
    $('explanation').textContent = explanation.error || 'Advisor unavailable';
  } else {
    const result = explanation.result;
    $('explanation').innerHTML = `<p>${result.explanation || 'No explanation returned.'}</p><p class="status">Advisory only. Human review is required before operational action.</p>`;
  }
}
document.getElementById('twin-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  $('digital-twin').textContent = 'Running guarded forecast preview...';
  const scenario = {
    temperature_delta_c: Number($('twin-temperature').value),
    humidity_delta_pct: Number($('twin-humidity').value),
    irrigation_duration_min: Number($('twin-irrigation').value),
    ventilation_pct: Number($('twin-ventilation').value),
    horizon_steps: Number($('twin-horizon').value),
  };
  const response = await fetch('/api/digital-twin', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(scenario)});
  const result = await response.json();
  if (!result.available) $('digital-twin').textContent = result.error || 'Digital Twin unavailable';
  else { twinPreview = result; refresh(); }
});
  refresh().catch(() => $('status').textContent = 'Dashboard API unavailable');
setInterval(() => refresh().catch(() => {}), 10000);
</script>
</body>
</html>"""
