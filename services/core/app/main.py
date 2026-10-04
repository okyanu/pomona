import logging
import csv
import io
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.auth import require_api_key
from app.mqtt_client import mqtt_client
from app.schemas import (
    HealthResponse,
    SensorEvent,
    SensorObservation,
    SensorEventListResponse,
    CalibrationEvent,
    CorrectedObservation,
)
from app.probe_health import probe_health
from app.store import event_store


class RecalibrateQualityBody(BaseModel):
    quality_by_device: Dict[str, List[str]] = Field(default_factory=dict)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting pomona-core")
    mqtt_client.start()
    yield
    logger.info("Stopping pomona-core")
    mqtt_client.stop()


app = FastAPI(
    title="Pomona Core",
    version="0.1.0",
    description="Sensor ingest and API for the Pomona agriculture platform.",
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="pomona-core",
        mqtt_connected=mqtt_client.connected,
        events_stored=event_store.count(),
    )


@app.post(
    "/v1/sensors/events",
    response_model=SensorEvent,
    status_code=201,
    dependencies=[Depends(require_api_key)],
)
def ingest_sensor_event(event: SensorEvent) -> SensorEvent:
    event.mqtt_retained = False
    event.source = event.source or "http"
    event_store.add(event)
    logger.info(
        "sensor event (http) device=%s farm=%s zone=%s ph=%.2f ec=%.2f",
        event.device_id,
        event.farm_id,
        event.zone_id,
        event.ph,
        event.ec_ms_cm,
    )
    return event


@app.get("/v1/sensors/events", response_model=SensorEventListResponse)
def list_sensor_events(limit: int = Query(default=50, ge=1, le=500), farm_id: Optional[str] = None, zone_id: Optional[str] = None, offset: int = Query(0, ge=0)) -> SensorEventListResponse:
    events = event_store.list_events(limit=limit, farm_id=farm_id, zone_id=zone_id, offset=offset)
    return SensorEventListResponse(count=len(events), events=events, latest_event=event_store.latest_event(farm_id, zone_id))


@app.get("/v1/sensors/events/latest", response_model=SensorEvent)
def latest_sensor_event(farm_id: Optional[str] = None, zone_id: Optional[str] = None) -> SensorEvent:
    event = event_store.latest_event(farm_id=farm_id, zone_id=zone_id)
    if event is None:
        raise HTTPException(status_code=404, detail="No sensor events recorded yet")
    return event


@app.post("/v1/sensors/observations", status_code=201, response_model=SensorObservation, dependencies=[Depends(require_api_key)])
def ingest_observation(observation: SensorObservation) -> SensorObservation:
    observation.mqtt_retained = False
    event_store.add_observation(observation)
    return observation


@app.get("/v1/sensors/observations")
def list_observations(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), farm_id: Optional[str] = None, zone_id: Optional[str] = None):
    observations = event_store.list_observations(limit, farm_id, zone_id, offset)
    return {"count": len(observations), "observations": observations}


@app.post("/v1/sensors/calibrations", status_code=201, response_model=CalibrationEvent, dependencies=[Depends(require_api_key)])
def ingest_calibration(event: CalibrationEvent) -> CalibrationEvent:
    return event_store.add_calibration(event)


@app.get("/v1/sensors/calibrations")
def list_calibrations(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), farm_id: Optional[str] = None, zone_id: Optional[str] = None):
    items = event_store.list_calibrations(limit, farm_id, zone_id, offset)
    return {"count": len(items), "calibrations": items}


@app.post("/v1/sensors/corrected-observations", status_code=201, response_model=CorrectedObservation, dependencies=[Depends(require_api_key)])
def ingest_corrected(observation: CorrectedObservation) -> CorrectedObservation:
    try:
        return event_store.add_corrected_observation(observation)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/v1/sensors/corrected-observations")
def list_corrected(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0), farm_id: Optional[str] = None, zone_id: Optional[str] = None):
    items = event_store.list_corrected(limit, farm_id, zone_id, offset)
    return {"count": len(items), "corrected_observations": items}


@app.get("/v1/sensors/probe-health")
def probe_health_report(farm_id: Optional[str] = None, zone_id: Optional[str] = None):
    """pH probe sensitivity trend from stored calibrations. Advisory: never acts, never edits data."""
    calibrations = event_store.list_calibrations(500, farm_id, zone_id)
    probes = probe_health(calibrations)
    return {"count": len(probes), "probes": probes}


@app.get("/v1/sensors/recalibrate-next")
def recalibrate_next(
    budget: int = Query(3, ge=0, le=50),
    farm_id: Optional[str] = None,
    zone_id: Optional[str] = None,
    device_id: Optional[str] = None,
    quality_labels: Optional[str] = Query(
        default=None,
        description="Comma-separated SQI labels to boost this device in the budget ranking.",
    ),
):
    """HITL ranking of which probes to recalibrate next. Never executes maintenance."""
    quality_map = {}
    if device_id and quality_labels:
        quality_map[device_id] = [part.strip() for part in quality_labels.split(",") if part.strip()]
    return event_store.recalibrate_ranking(
        farm_id=farm_id,
        zone_id=zone_id,
        budget=budget,
        quality_labels=quality_map,
    )


@app.post("/v1/sensors/recalibrate-next")
def recalibrate_next_with_quality(
    body: RecalibrateQualityBody,
    budget: int = Query(3, ge=0, le=50),
    farm_id: Optional[str] = None,
    zone_id: Optional[str] = None,
):
    """Same ranking with a JSON map of device_id -> SQI labels."""
    return event_store.recalibrate_ranking(
        farm_id=farm_id,
        zone_id=zone_id,
        budget=budget,
        quality_labels=body.quality_by_device,
    )


@app.get("/v1/sensors/devices")
def list_devices(farm_id: Optional[str] = None, zone_id: Optional[str] = None):
    return {"devices": event_store.devices(farm_id, zone_id)}


@app.get("/v1/sensors/export.csv")
def export_history(kind: Literal["events", "observations"] = "events", limit: int = Query(1000, ge=1, le=10000), offset: int = Query(0, ge=0), farm_id: Optional[str] = None, zone_id: Optional[str] = None):
    """Bounded export; offset pages newest records first, each page chronological."""
    model = SensorEvent if kind == "events" else SensorObservation
    loader = event_store.list_events if kind == "events" else event_store.list_observations
    rows = loader(limit, farm_id, zone_id, offset)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(model.model_fields))
    writer.writeheader()
    for row in rows:
        values = row.model_dump(mode="json")
        # Avoid spreadsheet formula interpretation for user-controlled strings.
        for key, value in values.items():
            if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
                values[key] = "'" + value
        writer.writerow(values)
    return Response(output.getvalue(), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="pomona-{kind}.csv"'})
