import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.advisor import explain
from app.actuator_gate import route_actuator_gate_reasoner
from app.audit import read_pipeline_audit, write_pipeline_audit
from app.config import settings
from app.registry import discover_models, get_model
from app.sensor_quality import route_sensor_quality_reasoner
from app.safety_triage import route_safety_triage_reasoner
from app.nutrient_ph_ec import route_nutrient_ph_ec_reasoner
from app.pipeline import evaluate_pipeline
from app.shared_chain import run_shared_reasoner_chain
from app.tomato_reasoner import route_tomato_reasoner
from app.water_irrigation import route_water_irrigation_reasoner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    models_dir = settings.models_dir
    logger.info(
        "model-router started backend=%s models_dir=%s hf=%s",
        settings.backend,
        models_dir,
        settings.hf_model_id,
    )
    if not models_dir.exists():
        logger.warning("models_dir does not exist: %s", models_dir)
    yield


app = FastAPI(
    title="Pomona Model Router",
    version="0.1.0",
    description="Routes agricultural tasks to registered Pomona models.",
    lifespan=lifespan,
)


class HealthResponse(BaseModel):
    status: str
    service: str
    backend: str
    models_registered: int
    huggingface_repo: str


class ModelSummary(BaseModel):
    id: str
    name: str
    type: str
    huggingface_repo: Optional[str] = None


class ExplainRequest(BaseModel):
    instruction: str = Field(
        default="Explain the likely risks and safe next checks for this greenhouse reading."
    )
    sensor: Dict[str, Any]
    guarded_context: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Validated reasoner output used as the safety boundary for explanation.",
    )
    model_id: Optional[str] = None
    backend: Optional[str] = None


class ExplainResponse(BaseModel):
    model_id: str
    backend: str
    huggingface_repo: str
    explanation: str
    likely_risks: List[str]
    missing_data: List[str]
    safe_checks: List[str]
    human_review_required: bool
    safety_note: str
    fallback_reason: Optional[str] = None


class TomatoRiskReasonerRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Normalized Pomona tomato greenhouse input.")
    model_id: Optional[str] = None
    mode: Literal["rules_only", "hybrid_guarded", "model_only"] = "hybrid_guarded"
    backend: Optional[str] = None


class TomatoRiskReasonerResponse(BaseModel):
    model_id: str
    mode: str
    backend: str
    source: str
    risk_labels: List[str]
    missing_data: List[str]
    safe_next_checks: List[str]
    blocked_actions: List[str]
    human_review_required: bool
    fallback_reason: Optional[str] = None


class SensorQualityReasonerRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Normalized Pomona sensor-quality input.")
    model_id: Optional[str] = None
    mode: Literal["rules_only", "hybrid_guarded", "model_only"] = "hybrid_guarded"


class SensorQualityReasonerResponse(BaseModel):
    model_id: str
    mode: str
    source: str
    data_quality_labels: List[str]
    missing_fields: List[str]
    suspect_fields: List[str]
    safe_next_checks: List[str]
    human_review_required: bool
    rationale: str
    fallback_reason: Optional[str] = None


class WaterIrrigationReasonerRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Normalized Pomona irrigation input.")
    model_id: Optional[str] = None
    mode: Literal["rules_only", "hybrid_guarded", "model_only"] = "hybrid_guarded"
    backend: Optional[Literal["rules", "ollama", "mlx"]] = None


class WaterIrrigationReasonerResponse(BaseModel):
    model_id: str
    mode: str
    backend: str
    source: str
    irrigation_risk_labels: List[str]
    missing_fields: List[str]
    suspect_fields: List[str]
    safe_next_checks: List[str]
    blocked_actions: List[str]
    human_review_required: bool
    rationale: str
    fallback_reason: Optional[str] = None


class ActuatorGateReasonerRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Proposed command with farm, sensor, and risk context.")
    model_id: Optional[str] = None
    mode: Literal["rules_only", "hybrid_guarded", "model_only"] = "hybrid_guarded"


class ActuatorGateReasonerResponse(BaseModel):
    model_id: str
    mode: str
    source: str
    decision: str
    gate_labels: List[str]
    blocked_actions: List[str]
    human_approval_required: bool
    safe_alternatives: List[str]
    rationale: str
    fallback_reason: Optional[str] = None


class DryRunActuatorRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Proposed command and validated farm/sensor context.")
    actor: str = Field(default="assistant_model", min_length=1, max_length=64)


class DryRunActuatorResponse(BaseModel):
    dry_run: bool
    execution_performed: bool
    decision: str
    gate_labels: List[str]
    blocked_actions: List[str]
    human_approval_required: bool
    safe_alternatives: List[str]
    rationale: str
    audit_id: str


class SafetyTriageReasonerRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Proposed action with farm, sensor, and risk context.")
    model_id: Optional[str] = None
    mode: Literal["rules_only", "hybrid_guarded", "model_only"] = "hybrid_guarded"


class SafetyTriageReasonerResponse(BaseModel):
    model_id: str
    mode: str
    source: str
    safety_labels: List[str]
    blocked_actions: List[str]
    safe_alternative: str
    human_review_required: bool
    rationale: str
    fallback_reason: Optional[str] = None


class NutrientPhEcReasonerRequest(BaseModel):
    input: Dict[str, Any] = Field(..., description="Normalized hydroponic or substrate pH/EC input.")
    model_id: Optional[str] = None
    mode: Literal["rules_only", "hybrid_guarded", "model_only"] = "hybrid_guarded"
    backend: Optional[Literal["rules", "ollama"]] = None


class NutrientPhEcReasonerResponse(BaseModel):
    model_id: str
    mode: str
    backend: str
    source: str
    nutrient_risk_labels: List[str]
    missing_fields: List[str]
    safe_next_checks: List[str]
    blocked_actions: List[str]
    human_review_required: bool
    rationale: str
    fallback_reason: Optional[str] = None


class SharedReasonerChainRequest(BaseModel):
    farm_context: Dict[str, Any] = Field(..., description="Farm, crop, system, and zone context.")
    sensor: Dict[str, Any] = Field(..., description="Latest normalized sensor packet.")
    expected_fields: List[str] = Field(default_factory=list)
    proposed_command: Optional[Dict[str, Any]] = None
    actor: str = "assistant_model"
    mode: Literal["rules_only", "hybrid_guarded"] = "hybrid_guarded"


class SharedReasonerChainResponse(BaseModel):
    mode: str
    source: str
    sensor_quality: Dict[str, Any]
    water_irrigation: Dict[str, Any]
    actuator_safety: Dict[str, Any]
    blocked_actions: List[str]
    human_review_required: bool
    fallback_reason: Optional[str] = None


class PipelineEvaluateRequest(BaseModel):
    farm_context: Dict[str, Any] = Field(..., description="Farm, crop, system, and zone context.")
    sensor: Dict[str, Any] = Field(..., description="Latest normalized sensor packet.")
    expected_fields: List[str] = Field(default_factory=list)
    proposed_command: Optional[Dict[str, Any]] = None
    actor: str = "assistant_model"
    mode: Literal["rules_only", "hybrid_guarded"] = "hybrid_guarded"
    scenario_id: Optional[str] = None


class PipelineEvaluateResponse(BaseModel):
    pipeline_id: str
    evaluated_at: str
    scenario_id: Optional[str] = None
    mode: str
    source: str
    input: Dict[str, Any]
    sensor_quality: Dict[str, Any]
    water_irrigation: Dict[str, Any]
    nutrient_ph_ec: Dict[str, Any]
    crop_risk: Dict[str, Any]
    agronomist: Dict[str, Any]
    safety: Dict[str, Any]
    safety_triage: Dict[str, Any]
    final_decision: Dict[str, Any]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    models = discover_models()
    return HealthResponse(
        status="ok",
        service="pomona-model-router",
        backend=settings.backend,
        models_registered=len(models),
        huggingface_repo=settings.hf_model_id,
    )


@app.get("/v1/models", response_model=List[ModelSummary])
def list_models() -> List[ModelSummary]:
    summaries: List[ModelSummary] = []
    for model in discover_models():
        hf = model.get("huggingface") or {}
        summaries.append(
            ModelSummary(
                id=model.get("id", "unknown"),
                name=model.get("name", model.get("id", "unknown")),
                type=model.get("type", "unknown"),
                huggingface_repo=hf.get("repo_id"),
            )
        )
    return summaries


@app.get("/v1/models/{model_id}")
def get_model_detail(model_id: str) -> Dict[str, Any]:
    model = get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model not found: {model_id}")
    return model


@app.get("/v1/runtimes")
async def runtime_status() -> Dict[str, Any]:
    """Report local runtime reachability without loading or changing model state."""
    result: Dict[str, Any] = {
        "rules": {"configured": True, "available": True, "backend": "deterministic"},
        "ollama": {
            "configured": bool(settings.water_irrigation_ollama_model),
            "available": False,
            "host": settings.ollama_host,
            "model": settings.water_irrigation_ollama_model,
        },
        "mlx": {
            "configured": bool(settings.water_irrigation_mlx_model),
            "available": False,
            "host": settings.mlx_host,
            "model": settings.water_irrigation_mlx_model,
        },
    }
    async with httpx.AsyncClient(timeout=0.8) as client:
        try:
            response = await client.get(f"{settings.ollama_host.rstrip('/')}/api/tags")
            response.raise_for_status()
            names = [item.get("name") for item in response.json().get("models", [])]
            result["ollama"].update({"available": True, "models_seen": [name for name in names if name]})
        except Exception as exc:
            result["ollama"]["error"] = str(exc)
        try:
            response = await client.get(f"{settings.mlx_host.rstrip('/')}/v1/models")
            response.raise_for_status()
            result["mlx"].update({"available": True, "models_seen": response.json().get("data", [])})
        except Exception as exc:
            result["mlx"]["error"] = str(exc)
    return result


@app.post("/v1/advisor/explain", response_model=ExplainResponse)
async def advisor_explain(request: ExplainRequest) -> ExplainResponse:
    model_id = request.model_id or settings.default_model_id
    model = get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")

    result = await explain(
        request.instruction,
        request.sensor,
        backend=request.backend,
        guarded_context=request.guarded_context,
    )
    result["model_id"] = model_id
    return ExplainResponse(**result)


@app.post("/v1/reasoners/sensor-quality", response_model=SensorQualityReasonerResponse)
def sensor_quality_reasoner(request: SensorQualityReasonerRequest) -> SensorQualityReasonerResponse:
    model_id = request.model_id or "pomona-sensor-quality-reasoner-v0.1"
    model = get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")

    try:
        result = route_sensor_quality_reasoner(request.input, request.mode, model_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    logger.info(
        "sensor-quality reasoner mode=%s crop=%s labels=%s review=%s",
        request.mode,
        (request.input.get("farm_context") or {}).get("crop"),
        ",".join(result["data_quality_labels"]) or "none",
        result["human_review_required"],
    )
    return SensorQualityReasonerResponse(**result)


@app.post("/v1/reasoners/tomato-risk", response_model=TomatoRiskReasonerResponse)
async def tomato_risk_reasoner(request: TomatoRiskReasonerRequest) -> TomatoRiskReasonerResponse:
    model_id = request.model_id or "pomona-tomato-risk-reasoner-v0.1.7"
    model = get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")

    try:
        backend = request.backend or settings.reasoner_backend
        result = await route_tomato_reasoner(request.input, request.mode, model_id, backend)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    logger.info(
        "tomato reasoner mode=%s crop=%s risks=%s review=%s",
        request.mode,
        request.input.get("crop"),
        ",".join(result["risk_labels"]) or "none",
        result["human_review_required"],
    )
    return TomatoRiskReasonerResponse(**result)


@app.post("/v1/reasoners/water-irrigation-risk", response_model=WaterIrrigationReasonerResponse)
async def water_irrigation_reasoner(
    request: WaterIrrigationReasonerRequest,
) -> WaterIrrigationReasonerResponse:
    model_id = request.model_id or "pomona-water-irrigation-risk-reasoner-v0.1"
    if not get_model(model_id):
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")
    try:
        backend = request.backend or settings.reasoner_backend
        result = await route_water_irrigation_reasoner(
            request.input,
            request.mode,
            backend,
            model_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    logger.info(
        "water-irrigation reasoner mode=%s backend=%s labels=%s review=%s",
        request.mode,
        backend,
        ",".join(result["irrigation_risk_labels"]) or "none",
        result["human_review_required"],
    )
    return WaterIrrigationReasonerResponse(**result)


@app.post("/v1/reasoners/actuator-command-gate", response_model=ActuatorGateReasonerResponse)
def actuator_command_gate_reasoner(
    request: ActuatorGateReasonerRequest,
) -> ActuatorGateReasonerResponse:
    model_id = request.model_id or "pomona-actuator-command-gate-reasoner-v0.1"
    if not get_model(model_id):
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")
    try:
        result = route_actuator_gate_reasoner(request.input, request.mode, model_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "actuator-gate reasoner mode=%s decision=%s labels=%s review=%s",
        request.mode,
        result["decision"],
        ",".join(result["gate_labels"]) or "none",
        result["human_approval_required"],
    )
    return ActuatorGateReasonerResponse(**result)


@app.post("/v1/actuator-commands/dry-run", response_model=DryRunActuatorResponse)
def actuator_command_dry_run(request: DryRunActuatorRequest) -> DryRunActuatorResponse:
    """Classify a proposed command without any actuator execution capability."""
    from uuid import uuid4

    input_data = dict(request.input)
    input_data["actor"] = request.actor
    result = route_actuator_gate_reasoner(
        input_data,
        "rules_only",
        "pomona-actuator-command-gate-deterministic",
    )
    audit_id = f"dry-run-{uuid4().hex[:12]}"
    write_pipeline_audit(
        {
            "audit_id": audit_id,
            "event_type": "actuator_command_dry_run",
            "actor": request.actor,
            "decision": result["decision"],
            "blocked_actions": result["blocked_actions"],
            "human_approval_required": result["human_approval_required"],
            "execution_performed": False,
        }
    )
    logger.info(
        "actuator dry-run audit=%s decision=%s blocked=%s execution=false",
        audit_id,
        result["decision"],
        ",".join(result["blocked_actions"]) or "none",
    )
    return DryRunActuatorResponse(
        dry_run=True,
        execution_performed=False,
        audit_id=audit_id,
        **{key: result[key] for key in (
            "decision",
            "gate_labels",
            "blocked_actions",
            "human_approval_required",
            "safe_alternatives",
            "rationale",
        )},
    )


@app.post("/v1/reasoners/safety-triage", response_model=SafetyTriageReasonerResponse)
def safety_triage_reasoner(
    request: SafetyTriageReasonerRequest,
) -> SafetyTriageReasonerResponse:
    model_id = request.model_id or "pomona-safety-triage-reasoner-v0.1"
    if not get_model(model_id):
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")
    try:
        result = route_safety_triage_reasoner(request.input, request.mode, model_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "safety-triage reasoner mode=%s labels=%s review=%s",
        request.mode,
        ",".join(result["safety_labels"]) or "none",
        result["human_review_required"],
    )
    return SafetyTriageReasonerResponse(**result)


@app.post("/v1/reasoners/nutrient-ph-ec", response_model=NutrientPhEcReasonerResponse)
async def nutrient_ph_ec_reasoner(
    request: NutrientPhEcReasonerRequest,
) -> NutrientPhEcReasonerResponse:
    model_id = request.model_id or "pomona-nutrient-ph-ec-reasoner-v0.1"
    try:
        backend = request.backend or settings.reasoner_backend
        result = await route_nutrient_ph_ec_reasoner(
            request.input,
            request.mode,
            model_id,
            backend,
        )
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return NutrientPhEcReasonerResponse(**result)


@app.post("/v1/reasoners/shared-chain", response_model=SharedReasonerChainResponse)
def shared_reasoner_chain(request: SharedReasonerChainRequest) -> SharedReasonerChainResponse:
    result = run_shared_reasoner_chain(
        request.farm_context,
        request.sensor,
        request.expected_fields,
        request.proposed_command,
        request.actor,
        request.mode,
    )
    logger.info(
        "shared chain mode=%s quality_labels=%s water_labels=%s safety_decision=%s review=%s",
        request.mode,
        ",".join(result["sensor_quality"]["data_quality_labels"]) or "none",
        ",".join(result["water_irrigation"]["irrigation_risk_labels"]) or "none",
        result["actuator_safety"]["decision"],
        result["human_review_required"],
    )
    return SharedReasonerChainResponse(**result)


@app.post("/v1/pipeline/evaluate", response_model=PipelineEvaluateResponse)
async def evaluate_pomona_pipeline(request: PipelineEvaluateRequest) -> PipelineEvaluateResponse:
    result = await evaluate_pipeline(
        request.farm_context,
        request.sensor,
        request.expected_fields,
        request.proposed_command,
        request.actor,
        request.mode,
        request.scenario_id,
    )
    logger.info(
        "pipeline id=%s scenario=%s risk=%s review=%s",
        result["pipeline_id"],
        request.scenario_id or "ad_hoc",
        result["final_decision"]["risk_level"],
        result["final_decision"]["human_review_required"],
    )
    return PipelineEvaluateResponse(**result)


@app.get("/v1/pipeline/audit")
def pipeline_audit(limit: int = 50) -> Dict[str, Any]:
    """Return recent local audit summaries; sensor payloads are excluded."""
    events = read_pipeline_audit(min(max(limit, 1), 200))
    return {"count": len(events), "events": events}
