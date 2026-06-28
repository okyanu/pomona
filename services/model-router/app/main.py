import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.advisor import explain
from app.config import settings
from app.registry import discover_models, get_model

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
