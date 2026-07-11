import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.advisor import explain
from app.config import settings
from app.registry import discover_models, get_model
from app.sensor_quality import route_sensor_quality_reasoner
from app.tomato_reasoner import route_tomato_reasoner

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


class TomatoRiskReasonerResponse(BaseModel):
    model_id: str
    mode: str
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


@app.post("/v1/advisor/explain", response_model=ExplainResponse)
async def advisor_explain(request: ExplainRequest) -> ExplainResponse:
    model_id = request.model_id or settings.default_model_id
    model = get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")

    result = await explain(request.instruction, request.sensor, backend=request.backend)
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
def tomato_risk_reasoner(request: TomatoRiskReasonerRequest) -> TomatoRiskReasonerResponse:
    model_id = request.model_id or "pomona-tomato-risk-reasoner-v0.1.7"
    model = get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"Model not registered: {model_id}")

    try:
        result = route_tomato_reasoner(request.input, request.mode, model_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc

    logger.info(
        "tomato reasoner mode=%s crop=%s risks=%s review=%s",
        request.mode,
        request.input.get("crop"),
        ",".join(result["risk_labels"]) or "none",
        result["human_review_required"],
    )
    return TomatoRiskReasonerResponse(**result)
