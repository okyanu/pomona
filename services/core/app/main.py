import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from app.mqtt_client import mqtt_client
from app.schemas import HealthResponse, SensorEvent, SensorEventListResponse
from app.store import event_store

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


@app.post("/v1/sensors/events", response_model=SensorEvent, status_code=201)
def ingest_sensor_event(event: SensorEvent) -> SensorEvent:
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
def list_sensor_events(limit: int = Query(default=50, ge=1, le=500)) -> SensorEventListResponse:
    events = event_store.list_events(limit=limit)
    return SensorEventListResponse(count=len(events), events=events)


@app.get("/v1/sensors/events/latest", response_model=SensorEvent)
def latest_sensor_event() -> SensorEvent:
    events = event_store.list_events(limit=1)
    if not events:
        raise HTTPException(status_code=404, detail="No sensor events recorded yet")
    return events[-1]
