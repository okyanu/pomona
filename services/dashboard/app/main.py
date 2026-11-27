from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
import hashlib
import json
import logging
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, Response
from typing import Literal
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
    automation_engine_url: str = "http://localhost:8085"
    # No reading from a zone for longer than this: the trust line stops saying "all readings passed". Twice the 5-minute
    # real log interval; fixed, not learned per zone. 0 turns it off (demos and fixed-timestamp replays).
    zone_stale_after_s: int = 600


settings = Settings()
request_scope: ContextVar[dict] = ContextVar("dashboard_scope", default={})
logger = logging.getLogger(__name__)


def service_unavailable(label: str, exc: Exception) -> str:
    """The text the browser gets when a service call fails: generic, since an exception names internal hosts and URLs.
    The detail goes to the log."""
    logger.warning("%s unavailable: %s: %s", label, type(exc).__name__, exc)
    return f"{label} unavailable; check the service and the dashboard log."


class HealthResponse(BaseModel):
    status: str
    service: str
    core_url: str


class FarmTimeResponse(BaseModel):
    """The farm time zone Core reports on /health; UTC with available=False when Core does not say."""
    available: bool
    farm_timezone: str = "UTC"
    utc_offset_now: str = "+00:00"
    next_offset_change: Optional[str] = None
    offset_after_change: Optional[str] = None
    tzdata_version: Optional[str] = None


class OverviewResponse(BaseModel):
    core_available: bool
    latest_event: Optional[Dict[str, Any]] = None
    recent_events: List[Dict[str, Any]] = []
    # Seconds from the latest reading's sample time to this server's clock (never negative); the page never uses the
    # browser clock. stale_after_s is ZONE_STALE_AFTER_S (0 = off); both are None/0 when there is nothing to judge.
    latest_age_s: Optional[float] = None
    stale_after_s: int = 0
    # Core's multi-device test for the latest event's zone and that device's expected fields (docs/design/multi-device-zones.md
    # 1.5). False/None in a single-device zone: nothing then changes.
    zone_multi_device: bool = False
    latest_device_fields: Optional[List[str]] = None
    # Multi-device zones only (docs/design/multi-device-zones-slice2.md 2.4); all three are null in a single-device zone.
    # zone_snapshot: Core's zone view as it answered (not judged further here); device_events: device id to that device's
    # last events, oldest first (trends); zone_snapshot_error: set when the snapshot call failed.
    zone_snapshot: Optional[Dict[str, Any]] = None
    device_events: Optional[Dict[str, List[Dict[str, Any]]]] = None
    zone_snapshot_error: Optional[str] = None
    error: Optional[str] = None


class RiskResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PipelineResponse(BaseModel):
    available: bool
    sensor_snapshot: Dict[str, Any] = Field(default_factory=dict)
    history_snapshot: List[Dict[str, Any]] = Field(default_factory=list)
    history_sha256: Optional[str] = None
    sensor_timestamp: Optional[str] = None
    sensor_event_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    # Zone-view path only (multi-device zones, slice 2 2.4/2.5); null otherwise. sources: field to the devices that
    # supplied (or should have supplied) it; dashboard_judged: devices whose sensor check the dashboard ran itself.
    sources: Optional[Dict[str, List[str]]] = None
    dashboard_judged: Optional[List[str]] = None
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


class AutomationResponse(BaseModel):
    available: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class AutomationDecisionRequest(BaseModel):
    reviewer: Optional[str] = Field(default=None, max_length=80)


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


@app.middleware("http")
async def scoped_request(request: Request, call_next):
    """Request-local scope also follows internal overview/risk calls; never global state."""
    scope = {key: request.query_params[key] for key in ("farm_id", "zone_id") if request.query_params.get(key)}
    if scope and (len(scope) != 2 or any(len(v) > 128 for v in scope.values())):
        return JSONResponse({"detail": "Provide both farm_id and zone_id (maximum 128 characters each)."}, status_code=422)
    token = request_scope.set(scope)
    try:
        prefix = "/api/automation/suggestions/"
        if scope and request.method == "POST" and request.url.path.startswith(prefix):
            suggestion_id = request.url.path[len(prefix):].rsplit("/", 1)[0]
            listing = await automation_suggestions()
            if not listing.available:
                return JSONResponse({"available": False, "error": "Cannot verify suggestion zone while automation is unavailable."}, status_code=503)
            if not any(s["id"] == suggestion_id for s in (listing.result or {}).get("suggestions", [])):
                return JSONResponse({"available": False, "error": "Suggestion does not belong to this zone."}, status_code=404)
        return await call_next(request)
    finally:
        request_scope.reset(token)


@app.get("/api/farm-time", response_model=FarmTimeResponse)
async def farm_time() -> FarmTimeResponse:
    """Display zone only: Core stores UTC. Unreachable Core or an older Core without the field keeps UTC."""
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
            response = await client.get("/health")
            response.raise_for_status()
        info = response.json().get("time") or {}
        if not isinstance(info.get("farm_timezone"), str):
            return FarmTimeResponse(available=False)
        text = lambda key: info[key] if isinstance(info.get(key), str) else None  # noqa: E731
        return FarmTimeResponse(available=True, farm_timezone=info["farm_timezone"],
                                utc_offset_now=text("utc_offset_now") or "+00:00",
                                next_offset_change=text("next_offset_change"),
                                offset_after_change=text("offset_after_change"),
                                tzdata_version=text("tzdata_version"))
    except Exception:
        return FarmTimeResponse(available=False)


@app.get("/api/devices")
async def devices():
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
            response = await client.get("/v1/sensors/devices", params=request_scope.get())
            response.raise_for_status()
        return {"available": True, "result": response.json()}
    except Exception as exc:
        return {"available": False, "error": service_unavailable("Device status", exc)}


@app.get("/api/probe-health")
async def probe_health():
    """pH probe sensitivity trend from stored calibrations. Read-only."""
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
            response = await client.get("/v1/sensors/probe-health", params=request_scope.get())
            response.raise_for_status()
        return {"available": True, "result": response.json()}
    except Exception as exc:
        return {"available": False, "error": service_unavailable("Probe health", exc)}


@app.get("/api/history")
async def history(kind: Literal["events", "observations"] = "events", offset: int = Query(0, ge=0)):
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
            response = await client.get(f"/v1/sensors/{kind}", params={**request_scope.get(), "limit": 100, "offset": offset})
            response.raise_for_status()
        return {"available": True, "result": response.json()}
    except Exception as exc:
        return {"available": False, "error": service_unavailable("History", exc)}


@app.get("/api/history/export.csv")
async def history_export(kind: Literal["events", "observations"] = "events", offset: int = Query(0, ge=0)):
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=10.0) as client:
            response = await client.get("/v1/sensors/export.csv", params={**request_scope.get(), "kind": kind, "limit": 100, "offset": offset})
            response.raise_for_status()
        return Response(response.content, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="pomona-{kind}.csv"'})
    except Exception:
        return JSONResponse({"detail": "History export unavailable; retry when Core is online."}, status_code=502)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def reading_age_s(event: Optional[Dict[str, Any]]) -> Optional[float]:
    """Seconds since the event's sample time on this host's clock (Core allows a sample time up to MAX_FUTURE_SAMPLE_S ahead and shows it as current: clamped at 0)."""
    stamp = (event or {}).get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        sampled = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if sampled.tzinfo is None:
        return None
    return max((utc_now() - sampled).total_seconds(), 0.0)


# --- Multi-device zones, slice 2: the zone view (docs/design/multi-device-zones-slice2.md 2.4) ------------------------

SNAPSHOT_CACHE_S = 5.0  # one zone view per cache life; also how long a failed device check is kept
JUDGED_CACHE_MAX = 256
TREND_DEVICES = 8
TREND_LIMIT = 120  # an hour at 30 s
# The router's GLOBAL_VETO_LABELS (services/model-router/app/trust_gate.py): a device carrying one of these has all the
# fields it supplies vetoed, because the router does not take them as labels from another device.
GLOBAL_VETO_LABELS = frozenset({"stale_reading", "insufficient_context", "unit_mismatch"})
ROUTINE_CHECK = "continue routine monitoring"
# The moisture probe may be published under either name (Core's trusted_baseline.ALIASES).
ALIASES = {"soil_moisture_pct": "substrate_moisture_pct", "substrate_moisture_pct": "soil_moisture_pct"}
DETAIL_MAX_CHARS = 500
_clock = time.monotonic  # tests replace this to move the caches' time
_snapshot_cache: Dict[tuple, tuple] = {}  # (farm, zone) -> (expires, snapshot)
_judged_cache: "OrderedDict[tuple, Dict[str, Any]]" = OrderedDict()  # (farm, zone, device, sample time) -> judgment
_judging: Dict[tuple, "asyncio.Future"] = {}  # judgments in flight, so concurrent views make one router call


def reset_zone_caches() -> None:
    _snapshot_cache.clear()
    _judged_cache.clear()
    _judging.clear()


async def _zone_snapshot(farm_id: str, zone_id: str) -> Dict[str, Any]:
    """Core's zone snapshot for (farm, zone), cached for SNAPSHOT_CACHE_S. Never changed by callers."""
    key = (farm_id, zone_id)
    hit = _snapshot_cache.get(key)
    now = _clock()
    if hit and hit[0] > now:
        return hit[1]
    async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
        response = await client.get("/v1/sensors/zone-snapshot", params={
            "farm_id": farm_id, "zone_id": zone_id, "stale_after_s": max(settings.zone_stale_after_s, 0)})
        response.raise_for_status()
        snapshot = response.json()
    if not isinstance(snapshot, dict):
        raise ValueError("zone snapshot is not an object")
    _snapshot_cache[key] = (_clock() + SNAPSHOT_CACHE_S, snapshot)
    return snapshot


async def _device_trend(farm_id: str, zone_id: str, device_id: str) -> List[Dict[str, Any]]:
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
            response = await client.get("/v1/sensors/events", params={
                "farm_id": farm_id, "zone_id": zone_id, "device_id": device_id, "limit": TREND_LIMIT})
            response.raise_for_status()
        events = [dict(item) for item in response.json().get("events") or []]
    except Exception:
        return []
    floor = datetime.min.replace(tzinfo=timezone.utc)
    events.sort(key=lambda item: sample_time(item) or floor)  # oldest first by sample time; arrival order breaks ties
    return events


async def _attach_zone_snapshot(data: OverviewResponse, trends: bool) -> OverviewResponse:
    """Multi-device zone: add Core's zone snapshot to the overview. A failed call leaves the slice-1 newest-packet path
    and sets zone_snapshot_error; a snapshot that says the zone is not multi-device turns the overview single-device."""
    scope = request_scope.get()
    event = data.latest_event or {}
    farm_id = scope.get("farm_id") or event.get("farm_id")
    zone_id = scope.get("zone_id") or event.get("zone_id")
    if not (farm_id and zone_id):
        return data
    try:
        snapshot = await _zone_snapshot(farm_id, zone_id)
    except Exception as exc:
        return data.model_copy(update={"zone_snapshot_error": service_unavailable("Zone snapshot", exc)})
    if not snapshot.get("multi_device"):
        return data.model_copy(update={"zone_multi_device": False, "latest_device_fields": None})
    update: Dict[str, Any] = {"zone_snapshot": snapshot}
    if snapshot.get("newest_age_s") is not None:
        update["latest_age_s"] = snapshot["newest_age_s"]
    if trends:
        ids = sorted(d["device_id"] for d in snapshot.get("devices") or [] if d.get("device_id"))[:TREND_DEVICES]
        series = await asyncio.gather(*(_device_trend(farm_id, zone_id, device_id) for device_id in ids))
        update["device_events"] = dict(zip(ids, series))
    return data.model_copy(update=update)


class ZoneView:
    """What every view reasons on. `sensor` is the snapshot's zone reading (S) on the zone-view path, else None and the
    view takes today's path (or slice 1's newest-packet path in a multi-device zone)."""

    def __init__(self, data: OverviewResponse) -> None:
        self.overview = data
        snapshot = data.zone_snapshot
        self.snapshot: Optional[Dict[str, Any]] = snapshot if isinstance(snapshot, dict) and snapshot.get("sensor") else None

    @property
    def sensor(self) -> Optional[Dict[str, Any]]:
        return dict(self.snapshot["sensor"]) if self.snapshot else None

    @property
    def sources(self) -> Dict[str, List[str]]:
        return {name: list(ids) for name, ids in ((self.snapshot or {}).get("sources") or {}).items()}

    @property
    def device_fields(self) -> List[str]:
        return list((self.snapshot or {}).get("zone_device_fields") or [])


async def _zone_view() -> ZoneView:
    """One zone view for a refresh (docs 2.4): the events call as today and, in a multi-device zone, the cached snapshot.
    No trend fetches (those are /api/overview's). Single-device zones: nothing but the events call."""
    return ZoneView(await overview())


def alert_detail(result: Dict[str, Any]) -> Optional[str]:
    """The router's sensor check text for one reading, as Core's feed builds it: its safe next checks without
    "continue routine monitoring", joined with "; ", cut to 500 characters ending in "…". None when empty."""
    checks = [c for c in (result.get("sensor_quality") or {}).get("safe_next_checks") or []
              if isinstance(c, str) and c and c != ROUTINE_CHECK]
    text = "; ".join(checks)
    if len(text) > DETAIL_MAX_CHARS:
        text = text[:DETAIL_MAX_CHARS - 1] + "…"
    return text or None


class DeviceChecks:
    """The devices' own sensor-check results as the router wants them (docs 2.4), and which devices the dashboard judged."""

    def __init__(self) -> None:
        self.vetoed: List[str] = []
        self.labels: List[str] = []
        self.checks: List[str] = []
        self.dashboard_judged: List[str] = []

    def keys(self) -> Dict[str, List[str]]:
        return {"known_vetoed_fields": list(self.vetoed), "known_data_quality_labels": list(self.labels),
                "known_safe_next_checks": list(self.checks)}

    def mask(self, sensor: Dict[str, Any]) -> Dict[str, Any]:
        vetoed = set(self.vetoed)
        return {key: value for key, value in sensor.items() if key not in vetoed}


def _add_unique(target: List[str], items: Any) -> None:
    for item in items or []:
        if item not in target:
            target.append(item)


async def _judge_pending_device(farm_id: str, zone_id: str, device: Dict[str, Any]) -> Dict[str, Any]:
    """Judge one device's latest packet here, as Core's feed would have (rules_only, the device's own history and its
    device_fields). Never raises: a failure is returned as {"failed": True}."""
    event = dict(device.get("event") or {})
    event.pop("source", None)
    device_id = device["device_id"]
    history: List[Dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=5.0) as client:
            response = await client.get("/v1/sensors/events", params={
                "limit": 24, "farm_id": farm_id, "zone_id": zone_id, "device_id": device_id})
            response.raise_for_status()
        for item in earlier_samples(response.json().get("events") or [], event.get("timestamp")):
            packet = dict(item)
            for name in ("source", "received_at", "mqtt_retained"):
                packet.pop(name, None)
            history.append(packet)
    except Exception:
        history = []
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=10.0) as client:
            response = await client.post("/v1/pipeline/evaluate", json={
                "scenario_id": "dashboard-device-check",
                "farm_context": {
                    "crop": event.get("crop", "tomato"),
                    "system_type": event.get("system_type", "greenhouse_substrate"),
                    "zone_id": event.get("zone_id", "unknown"),
                    "weather": event.get("weather"),
                    "zone_area_m2": event.get("zone_area_m2"),
                    "crop_kc": event.get("crop_kc"),
                    "npk_target": event.get("npk_target"),
                },
                "sensor": event,
                "history": history,
                "proposed_command": {"action_type": "continue_monitoring"},
                "actor": "dashboard",
                "mode": "rules_only",
                "device_fields": list(device.get("device_fields") or []),
            })
            response.raise_for_status()
        result = response.json()
    except Exception:
        return {"failed": True}
    quality = result.get("sensor_quality") or {}
    gate = result.get("trust_gate") or {}
    judgment = {
        "failed": False,
        "vetoed_fields": list(gate.get("vetoed_fields") or (result.get("final_decision") or {}).get("vetoed_fields") or []),
        "data_quality_labels": list(quality.get("data_quality_labels") or []),
        "safe_next_checks": list(quality.get("safe_next_checks") or []),
    }
    # Core's feed never judges a retained packet (retained state never proves live availability): such a device is
    # judged here for the view only, and not given to the alert monitor.
    if not event.get("mqtt_retained"):
        await feed_alert_monitor(event, result, alert_detail(result))
    return judgment


async def _device_judgment(farm_id: str, zone_id: str, device: Dict[str, Any]) -> Dict[str, Any]:
    """The dashboard's own check of a pending device, cached by (farm, zone, device, sample time): a success until
    evicted (256 entries), a failure for SNAPSHOT_CACHE_S. Concurrent views share one call."""
    key = (farm_id, zone_id, device["device_id"], device.get("sample_time"))
    hit = _judged_cache.get(key)
    if hit and (hit["until"] is None or hit["until"] > _clock()):
        return hit["judgment"]
    loop = asyncio.get_running_loop()
    running = _judging.get(key)
    if running is not None and running.get_loop() is loop:
        try:
            return await asyncio.shield(running)
        except asyncio.CancelledError:
            if not running.cancelled():
                raise
    future = loop.create_future()
    _judging[key] = future
    try:
        judgment = await _judge_pending_device(farm_id, zone_id, device)
        _judged_cache[key] = {"judgment": judgment, "until": _clock() + SNAPSHOT_CACHE_S if judgment["failed"] else None}
        _judged_cache.move_to_end(key)
        while len(_judged_cache) > JUDGED_CACHE_MAX:
            _judged_cache.popitem(last=False)
        future.set_result(judgment)
        return judgment
    except BaseException:
        future.cancel()
        raise
    finally:
        _judging.pop(key, None)


async def device_checks(snapshot: Dict[str, Any]) -> DeviceChecks:
    """Turn each device that supplies a field into the router's `known_*` inputs (docs 2.4). A judged device's row comes
    from Core; a pending one is judged here. A stale device supplies nothing and so counts for nothing."""
    farm_id, zone_id = snapshot.get("farm_id"), snapshot.get("zone_id")
    devices = sorted((d for d in snapshot.get("devices") or [] if d.get("supplied")), key=lambda d: d["device_id"])
    pending = [d for d in devices if (d.get("trust") or {}).get("status") != "judged"]
    judgments = dict(zip((d["device_id"] for d in pending),
                         await asyncio.gather(*(_device_judgment(farm_id, zone_id, d) for d in pending))))
    out = DeviceChecks()
    for device in devices:
        supplied = list(device["supplied"])
        trust = device.get("trust") or {}
        if trust.get("status") == "judged":
            row = trust
        else:
            row = judgments[device["device_id"]]
            if row["failed"]:
                _add_unique(out.vetoed, supplied)
                _add_unique(out.checks, [f"sensor check for {device['device_id']} could not run; verify its readings"])
                continue
            out.dashboard_judged.append(device["device_id"])
            row = {"vetoed_fields": row["vetoed_fields"], "data_quality_labels": row["data_quality_labels"],
                   "safe_next_checks": row["safe_next_checks"]}
        own_vetoed = list(row.get("vetoed_fields") or [])
        labels = list(row.get("data_quality_labels") or [])  # null in a row from before the labels were kept
        flagged = [f for f in supplied if f in own_vetoed]
        if GLOBAL_VETO_LABELS & set(labels):
            flagged = supplied
        _add_unique(out.vetoed, flagged)
        if flagged or not own_vetoed:  # a flagged probe outside the zone view puts nothing on the zone's badge
            _add_unique(out.labels, labels)
            _add_unique(out.checks, [c for c in row.get("safe_next_checks") or [] if c != ROUTINE_CHECK])
    # Probes disagree (docs/design/slow-drift-pair-check.md 4b): Core marked the field, so no advice uses either value
    # (it goes to the router as vetoed), and the pair text of every live probe that took the flag goes on the zone's
    # badge even when that probe does not supply the field (the loop above skips such a probe).
    disagree = {name for name, field in (snapshot.get("fields") or {}).items() if field.get("disagree")}
    if disagree:
        both = disagree | {ALIASES[name] for name in disagree if name in ALIASES}
        _add_unique(out.vetoed, sorted(disagree))
        for device in sorted(snapshot.get("devices") or [], key=lambda d: d["device_id"]):
            trust = device.get("trust") or {}
            if device.get("stale") or trust.get("status") != "judged" or not both & set(trust.get("pair_fields") or ()):
                continue
            _add_unique(out.labels, trust.get("data_quality_labels") or [])
            _add_unique(out.checks, [c for c in trust.get("safe_next_checks") or [] if c != ROUTINE_CHECK])
    return out


@app.get("/api/overview", response_model=OverviewResponse)
async def overview_page() -> OverviewResponse:
    return await overview(trends=True)


async def overview(trends: bool = False) -> OverviewResponse:
    """The overview. `trends` (only /api/overview asks) adds each device's recent events in a multi-device zone; the
    other views take the same zone view without them. Pending devices are not judged here (it never waits on the router)."""
    try:
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=3.0) as client:
            response = await client.get("/v1/sensors/events", params={"limit": 20, **request_scope.get()})
            response.raise_for_status()
            payload = response.json()
        events = payload.get("events") or []
        latest = payload.get("latest_event", events[-1] if events else None)
        data = OverviewResponse(
            core_available=True,
            latest_event=latest,
            recent_events=list(reversed(events)),
            latest_age_s=reading_age_s(latest),
            stale_after_s=max(settings.zone_stale_after_s, 0),
            zone_multi_device=bool(payload.get("zone_multi_device")),
            latest_device_fields=payload.get("latest_device_fields"),
        )
    except Exception as exc:
        return OverviewResponse(core_available=False, error=service_unavailable("Core", exc))
    if data.zone_multi_device and data.latest_event:
        data = await _attach_zone_snapshot(data, trends)
    return data


@app.get("/api/risk", response_model=RiskResponse)
async def risk() -> RiskResponse:
    view = await _zone_view()
    overview_data = view.overview
    if not overview_data.core_available or not overview_data.latest_event:
        return RiskResponse(available=False, error="No persisted sensor event is available.")

    zone_keys: Dict[str, Any] = {}
    if view.snapshot:
        # Zone-view path (slice 2 2.5): the zone's reading, the devices' own check results, and the fields the zone's
        # devices carry, so the risk panel and the trust line agree on what is missing.
        sensor = view.sensor
        checks = await device_checks(view.snapshot)
        zone_keys = {"device_fields": view.device_fields, **checks.keys()}
        event = sensor
    else:
        event = overview_data.latest_event
        sensor = dict(event)
        sensor.pop("source", None)
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=5.0) as client:
            response = await client.post(
                "/v1/reasoners/shared-chain",
                json={
                    "farm_context": {
                        "farm_id": event.get("farm_id"),
                        "crop": event.get("crop", "tomato"),
                        "system_type": event.get("system_type", "greenhouse_substrate"),
                        "zone_id": event.get("zone_id", "unknown"),
                    },
                    "sensor": sensor,
                    "proposed_command": {"action_type": "continue_monitoring"},
                    "actor": "dashboard",
                    "mode": "hybrid_guarded",
                    **zone_keys,
                },
            )
            response.raise_for_status()
        return RiskResponse(available=True, result=response.json())
    except Exception as exc:
        return RiskResponse(available=False, error=service_unavailable("Reasoner chain", exc))


def sample_time(packet: Dict[str, Any]) -> Optional[datetime]:
    stamp = packet.get("timestamp")
    if not isinstance(stamp, str):
        return None
    try:
        parsed = datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def earlier_samples(events: List[Dict[str, Any]], timestamp: Any, keep: int = 11) -> List[Dict[str, Any]]:
    """The packets sampled strictly before `timestamp`, in sample-time order (Core's order breaks ties), newest `keep`.

    Unlike the single-device path this does not drop "the last by arrival": a late packet is not the latest sample.
    """
    cutoff = sample_time({"timestamp": timestamp})
    earlier = [(sample_time(item), item) for item in events]
    earlier = [(when, item) for when, item in earlier if when is not None and cutoff is not None and when < cutoff]
    earlier.sort(key=lambda pair: pair[0])  # stable: the API's order breaks equal sample times
    return [item for _, item in earlier[-keep:]]


@app.get("/api/pipeline", response_model=PipelineResponse)
async def pipeline() -> PipelineResponse:
    """Return the unified guarded pipeline for the latest persisted event (or, in a multi-device zone whose devices are
    live, for the zone view: docs/design/multi-device-zones-slice2.md 2.5)."""
    view = await _zone_view()
    overview_data = view.overview
    if not overview_data.core_available or not overview_data.latest_event:
        return PipelineResponse(available=False, error="No persisted sensor event is available.")
    if view.snapshot:
        return await _zone_pipeline(view)

    event = dict(overview_data.latest_event)
    event.pop("source", None)
    history: List[Dict[str, Any]] = []
    multi_device = overview_data.zone_multi_device
    try:
        params = {"limit": 12}
        scope = request_scope.get()
        if scope.get("farm_id"):
            params["farm_id"] = scope["farm_id"]
        if scope.get("zone_id"):
            params["zone_id"] = scope["zone_id"]
        if multi_device:
            # Multi-device zone: this device's own history, from the evaluated event's farm, zone and device even when the
            # request is unscoped (docs/design/multi-device-zones.md 1.6).
            params = {"limit": 24, "farm_id": event.get("farm_id"), "zone_id": event.get("zone_id"),
                      "device_id": event.get("device_id")}
        async with httpx.AsyncClient(base_url=settings.core_url, timeout=5.0) as core_client:
            history_response = await core_client.get("/v1/sensors/events", params=params)
            history_response.raise_for_status()
        events = history_response.json().get("events") or []
        if multi_device:
            prior = earlier_samples(events, event.get("timestamp"))
        else:
            # Core returns chronological pages; drop the latest packet so history is prior-only.
            prior = events[:-1] if len(events) > 1 else []
        for item in prior:
            packet = dict(item)
            packet.pop("source", None)
            packet.pop("received_at", None)
            packet.pop("mqtt_retained", None)
            history.append(packet)
    except Exception:
        history = []

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
                        # Optional inputs for the FAO-56/NPK calculator
                        # (agronomy_calc); the pipeline skips the estimate
                        # whenever any of these is absent.
                        "weather": event.get("weather"),
                        "zone_area_m2": event.get("zone_area_m2"),
                        "crop_kc": event.get("crop_kc"),
                        "npk_target": event.get("npk_target"),
                    },
                    "sensor": event,
                    "history": history,
                    "proposed_command": {"action_type": "continue_monitoring"},
                    "actor": "dashboard",
                    "mode": "hybrid_guarded",
                    **({"device_fields": overview_data.latest_device_fields} if multi_device else {}),
                },
            )
            response.raise_for_status()
        result = response.json()
        await feed_alert_monitor(event, result)
        event_id = hashlib.sha256(json.dumps(event, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return PipelineResponse(available=True, result=result, sensor_event_id=event_id,
                                sensor_timestamp=event.get("timestamp"), sensor_snapshot=event, history_snapshot=history,
                                history_sha256=hashlib.sha256(json.dumps(history, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
    except Exception as exc:
        return PipelineResponse(available=False, error=service_unavailable("Integrated pipeline", exc))


async def _zone_pipeline(view: ZoneView) -> PipelineResponse:
    """The pipeline on the zone view: the snapshot's reading, no history, the zone's device_fields, the devices' own
    check results. It does not post to the alert monitor: alerts stay per device (Core's feed, or the fallback in
    device_checks)."""
    event = view.sensor
    sources = view.sources
    try:
        checks = await device_checks(view.snapshot)
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=10.0) as client:
            response = await client.post(
                "/v1/pipeline/evaluate",
                json={
                    "scenario_id": "dashboard-latest-event",
                    "farm_context": {
                        "crop": event.get("crop", "tomato"),
                        "system_type": event.get("system_type", "greenhouse_substrate"),
                        "zone_id": event.get("zone_id", "unknown"),
                        "weather": event.get("weather"),
                        "zone_area_m2": event.get("zone_area_m2"),
                        "crop_kc": event.get("crop_kc"),
                        "npk_target": event.get("npk_target"),
                    },
                    "sensor": event,
                    "history": [],
                    "proposed_command": {"action_type": "continue_monitoring"},
                    "actor": "dashboard",
                    "mode": "hybrid_guarded",
                    "device_fields": view.device_fields,
                    **checks.keys(),
                },
            )
            response.raise_for_status()
        result = response.json()
        event_id = hashlib.sha256(json.dumps({"sensor": event, "sources": sources}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        return PipelineResponse(available=True, result=result, sensor_event_id=event_id, sensor_timestamp=event.get("timestamp"),
                                sensor_snapshot=event, history_snapshot=[],
                                history_sha256=hashlib.sha256(b"[]").hexdigest(),
                                sources=sources, dashboard_judged=list(checks.dashboard_judged))
    except Exception as exc:
        return PipelineResponse(available=False, error=service_unavailable("Integrated pipeline", exc))


def pipeline_risk_labels(result: Dict[str, Any]) -> List[str]:
    return list(dict.fromkeys([
        *(result.get("sensor_quality") or {}).get("data_quality_labels", []),
        *(result.get("water_irrigation") or {}).get("irrigation_risk_labels", []),
        *(result.get("nutrient_ph_ec") or {}).get("nutrient_risk_labels", []),
        *(result.get("crop_risk") or {}).get("risk_labels", []),
    ]))


async def feed_alert_monitor(event: Dict[str, Any], result: Dict[str, Any], detail: Optional[str] = None) -> None:
    """Give this reading's risk labels to the alert monitor. Failure-isolated: an alert-service
    outage never hides the pipeline result. Repeated readings are ignored by the monitor.
    `detail` is the sensor check text for multi-device zones (docs/design/multi-device-zones-slice2.md 2.6); the
    single-device path never passes it and the request body stays as it was."""
    if not (event.get("farm_id") and event.get("zone_id") and event.get("timestamp")):
        return
    try:
        async with httpx.AsyncClient(base_url=settings.automation_engine_url, timeout=2.0) as client:
            await client.post("/v1/automation/alerts/observe", json={
                "farm_id": event["farm_id"], "zone_id": event["zone_id"], "device_id": event.get("device_id"),
                "sample_time": event["timestamp"], "risk_labels": pipeline_risk_labels(result),
                "data_quality_labels": (result.get("sensor_quality") or {}).get("data_quality_labels", []),
                **({"detail": detail} if detail else {})})
    except Exception:
        pass


@app.get("/api/alerts", response_model=AutomationResponse)
async def alerts() -> AutomationResponse:
    """Alert states (pending / active / recovering) and recent raised / recovered events. Read-only."""
    try:
        async with httpx.AsyncClient(base_url=settings.automation_engine_url, timeout=3.0) as client:
            response = await client.get("/v1/automation/alerts", params=request_scope.get() or None)
            response.raise_for_status()
        return AutomationResponse(available=True, result=response.json())
    except Exception as exc:
        return AutomationResponse(available=False, error=service_unavailable("Alert monitor", exc))


@app.get("/api/automation", response_model=AutomationResponse)
async def automation_suggestions() -> AutomationResponse:
    """List automation suggestions. Read-only: never approves/rejects/evaluates."""
    try:
        async with httpx.AsyncClient(base_url=settings.automation_engine_url, timeout=3.0) as client:
            response = await client.get("/v1/automation/suggestions")
            response.raise_for_status()
        result = response.json()
        scope = request_scope.get()
        if scope:
            result["suggestions"] = [s for s in result.get("suggestions", []) if all((s.get("context") or {}).get(k) == v for k, v in scope.items())]
            result["count"] = len(result["suggestions"])
        return AutomationResponse(available=True, result=result)
    except Exception as exc:
        return AutomationResponse(available=False, error=service_unavailable("Automation engine", exc))


@app.get("/api/advice-cards", response_model=AutomationResponse)
async def advice_cards() -> AutomationResponse:
    """HITL advice cards derived from automation suggestions. Never executes hardware."""
    try:
        async with httpx.AsyncClient(base_url=settings.automation_engine_url, timeout=3.0) as client:
            response = await client.get("/v1/automation/advice-cards")
            response.raise_for_status()
        result = response.json()
        scope = request_scope.get()
        if scope:
            result["cards"] = [
                card
                for card in result.get("cards", [])
                if all((card.get("evidence") or {}).get(k) == v for k, v in scope.items() if k in {"farm_id", "zone_id"})
            ]
            result["count"] = len(result["cards"])
        return AutomationResponse(available=True, result=result)
    except Exception as exc:
        return AutomationResponse(available=False, error=service_unavailable("Automation engine", exc))


@app.post("/api/automation/evaluate", response_model=AutomationResponse)
async def automation_evaluate() -> AutomationResponse:
    """Evaluate the latest pipeline's risk labels against automation rules.

    This is an explicit, user-triggered action (a dashboard button), not part
    of the 10s auto-refresh loop. A stable sensor-event key makes retries reuse
    retained suggestions, even when the pipeline run ID changes.
    """
    pipeline_data = await pipeline()
    if not pipeline_data.available or not pipeline_data.result:
        return AutomationResponse(available=False, error="No pipeline result is available to evaluate.")

    result = pipeline_data.result
    risk_labels = pipeline_risk_labels(result)
    blocked_actions = (result.get("final_decision") or {}).get("blocked_actions", [])
    try:
        async with httpx.AsyncClient(base_url=settings.automation_engine_url, timeout=5.0) as client:
            response = await client.post(
                "/v1/automation/evaluate",
                json={
                    "risk_labels": risk_labels,
                    "event_id": pipeline_data.sensor_event_id,
                    "blocked_actions": blocked_actions,
                    "context": {
                        "pipeline_id": result.get("pipeline_id"),
                        "sensor_timestamp": pipeline_data.sensor_timestamp,
                        "sensor_event_id": pipeline_data.sensor_event_id,
                        "sensor_snapshot": pipeline_data.sensor_snapshot,
                        "history_sha256": pipeline_data.history_sha256,
                        "history_snapshot": pipeline_data.history_snapshot,
                        "readings": {k: v for k, v in pipeline_data.sensor_snapshot.items() if k in {
                            "air_temperature_c", "water_temperature_c", "humidity_pct", "ph", "ec_ms_cm",
                            "soil_moisture_pct", "substrate_moisture_pct", "root_zone_moisture_pct"}},
                        "farm_id": pipeline_data.sensor_snapshot.get("farm_id"),
                        "zone_id": pipeline_data.sensor_snapshot.get("zone_id"),
                        "sensor_quality_labels": (result.get("sensor_quality") or {}).get("data_quality_labels", []),
                        "missing_fields": (result.get("sensor_quality") or {}).get("missing_fields", []),
                        "trust_verdict": (result.get("final_decision") or {}).get("trust_verdict"),
                        "vetoed_fields": (result.get("final_decision") or {}).get("vetoed_fields")
                        or (result.get("trust_gate") or {}).get("vetoed_fields", []),
                        "risk_labels": risk_labels,
                        "blocked_actions": blocked_actions,
                        "reasoner_ids": list(dict.fromkeys(part["model_id"] for name in (
                            "sensor_quality", "water_irrigation", "nutrient_ph_ec", "crop_risk")
                            if isinstance(part := result.get(name), dict) and part.get("model_id"))),
                        "reasoner_snapshot": {name: result.get(name) for name in (
                            "sensor_quality", "water_irrigation", "nutrient_ph_ec", "crop_risk", "trust_gate", "final_decision")},
                        # Zone-view suggestions name who supplied each field, so outcomes follow those devices
                        # (multi-device zones only; a single-device context is unchanged).
                        **({"sources": pipeline_data.sources} if pipeline_data.sources else {}),
                        **request_scope.get(),
                    },
                },
            )
            response.raise_for_status()
        return AutomationResponse(available=True, result=response.json())
    except Exception as exc:
        return AutomationResponse(available=False, error=service_unavailable("Automation engine", exc))


@app.post("/api/automation/suggestions/{suggestion_id}/approve", response_model=AutomationResponse)
async def automation_approve(suggestion_id: str, decision: Optional[AutomationDecisionRequest] = None) -> AutomationResponse:
    """Record a human decision to approve a suggestion. No actuator is ever executed."""
    try:
        async with httpx.AsyncClient(base_url=settings.automation_engine_url, timeout=3.0) as client:
            response = await client.post(f"/v1/automation/suggestions/{suggestion_id}/approve",
                                         json={"reviewer": decision.reviewer if decision else None})
            response.raise_for_status()
        return AutomationResponse(available=True, result=response.json())
    except Exception as exc:
        return AutomationResponse(available=False, error=service_unavailable("Automation engine", exc))


@app.post("/api/automation/suggestions/{suggestion_id}/reject", response_model=AutomationResponse)
async def automation_reject(suggestion_id: str, decision: Optional[AutomationDecisionRequest] = None) -> AutomationResponse:
    """Record a human decision to reject a suggestion."""
    try:
        async with httpx.AsyncClient(base_url=settings.automation_engine_url, timeout=3.0) as client:
            response = await client.post(f"/v1/automation/suggestions/{suggestion_id}/reject",
                                         json={"reviewer": decision.reviewer if decision else None})
            response.raise_for_status()
        return AutomationResponse(available=True, result=response.json())
    except Exception as exc:
        return AutomationResponse(available=False, error=service_unavailable("Automation engine", exc))


@app.get("/api/audit", response_model=AuditResponse)
async def audit() -> AuditResponse:
    if request_scope.get():
        return AuditResponse(available=False, error="Legacy audit summaries have no zone identity; hidden in scoped view.")
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=3.0) as client:
            response = await client.get("/v1/pipeline/audit", params={"limit": 20})
            response.raise_for_status()
        return AuditResponse(available=True, result=response.json())
    except Exception as exc:
        return AuditResponse(available=False, error=service_unavailable("Pipeline audit", exc))


@app.get("/api/safety", response_model=SafetyResponse)
async def safety() -> SafetyResponse:
    view = await _zone_view()
    overview_data = view.overview
    if not overview_data.core_available or not overview_data.latest_event:
        return SafetyResponse(available=False, error="No persisted sensor event is available.")

    # Zone-view path: the zone's reading, unmasked. The triage gate reads only sensor_quality and the command, and
    # this call sends no sensor_quality, so the reading never changes its answer; it is sent so the request names no
    # single device.
    event = view.sensor if view.snapshot else overview_data.latest_event
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
        return SafetyResponse(available=False, error=service_unavailable("Safety triage", exc))


@app.get("/api/services", response_model=ServiceStatusResponse)
async def service_status() -> ServiceStatusResponse:
    targets = {
        "core": settings.core_url,
        "model_router": settings.model_router_url,
        "safety_checker": settings.safety_checker_url,
        "digital_twin": settings.digital_twin_url,
        "automation_engine": settings.automation_engine_url,
    }
    statuses: Dict[str, Dict[str, Any]] = {}
    async with httpx.AsyncClient(timeout=2.0) as client:
        for name, base_url in targets.items():
            try:
                response = await client.get(f"{base_url.rstrip('/')}/health")
                response.raise_for_status()
                statuses[name] = {"available": True, "health": response.json()}
            except Exception as exc:
                statuses[name] = {"available": False, "error": service_unavailable(name.replace("_", " "), exc)}
    return ServiceStatusResponse(services=statuses)


@app.get("/api/runtimes", response_model=RuntimeStatusResponse)
async def runtime_status() -> RuntimeStatusResponse:
    try:
        async with httpx.AsyncClient(base_url=settings.model_router_url, timeout=3.0) as client:
            response = await client.get("/v1/runtimes")
            response.raise_for_status()
        return RuntimeStatusResponse(available=True, result=response.json())
    except Exception as exc:
        return RuntimeStatusResponse(available=False, error=service_unavailable("Runtime status", exc))


async def _digital_twin_preview(request: DigitalTwinScenarioRequest) -> DigitalTwinResponse:
    """Run a bounded forecast and validate its endpoint against guarded rules."""
    view = await _zone_view()
    overview_data = view.overview
    if not overview_data.core_available or not overview_data.latest_event:
        return DigitalTwinResponse(available=False, error="No persisted sensor event is available.")

    zone_keys: Dict[str, Any] = {}
    if view.snapshot:
        # Zone-view path (slice 2 2.5): the state is the zone's reading with the carried vetoes removed, and the guarded
        # call names the zone's device_fields and sends no expected_fields, so a field missing from the snapshot is
        # reported missing instead of silently dropped. The twin needs air, humidity or moisture: a masked reading
        # with none of them gets its 422, as a single-device packet without them does.
        checks = await device_checks(view.snapshot)
        event = checks.mask(view.sensor)
        zone_keys = {"device_fields": view.device_fields, **checks.keys()}
    else:
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
        guard_fields = zone_keys or {"expected_fields": expected_fields}
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
                    **guard_fields,
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
        return DigitalTwinResponse(available=False, error=service_unavailable("Digital Twin", exc))


@app.get("/api/digital-twin", response_model=DigitalTwinResponse)
async def digital_twin() -> DigitalTwinResponse:
    return await _digital_twin_preview(DigitalTwinScenarioRequest())


@app.post("/api/digital-twin", response_model=DigitalTwinResponse)
async def digital_twin_scenario(request: DigitalTwinScenarioRequest) -> DigitalTwinResponse:
    return await _digital_twin_preview(request)


@app.get("/api/explanation", response_model=ExplanationResponse)
async def explanation() -> ExplanationResponse:
    view = await _zone_view()
    overview_data = view.overview
    if not overview_data.core_available or not overview_data.latest_event:
        return ExplanationResponse(available=False, error="No persisted sensor event is available.")
    risk_data = await risk()
    if not risk_data.available:
        return ExplanationResponse(available=False, error=risk_data.error or "Guarded risk result unavailable.")
    sensor = overview_data.latest_event
    if view.snapshot:  # zone-view path: the zone's reading with the carried vetoes removed
        sensor = (await device_checks(view.snapshot)).mask(view.sensor)
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
                    "sensor": sensor,
                    "guarded_context": risk_data.result,
                    "backend": "stub",
                },
            )
            response.raise_for_status()
        return ExplanationResponse(available=True, result=response.json())
    except Exception as exc:
        return ExplanationResponse(available=False, error=service_unavailable("Agronomist advisor", exc))


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
    :root {
      color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif;
      --bg: #0d1117; --bg-card: #161b22; --border: #30363d; --border-soft: #21262d;
      --text: #e6edf3; --text-dim: #8b949e; --accent: #3fb950;
      --success: #3fb950; --success-bg: rgba(63, 185, 80, 0.15);
      --warning: #d29922; --warning-bg: rgba(210, 153, 34, 0.15);
      --danger: #f85149; --danger-bg: rgba(248, 81, 73, 0.15);
      --neutral: #8b949e; --neutral-bg: rgba(139, 148, 158, 0.15);
      --radius: 10px;
    }
    body {
      margin: 0; color: var(--text);
      background:
        radial-gradient(900px 320px at 15% -120px, rgba(63, 185, 80, 0.10), transparent),
        var(--bg);
    }
    main { max-width: 1100px; margin: 0 auto; padding: 32px 20px 48px; }
    header { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; border-bottom: 1px solid var(--border); padding-bottom: 20px; }
    h1 { margin: 0; font-size: 28px; letter-spacing: 0; display: flex; align-items: center; gap: 10px; }
    .status { color: var(--text-dim); font-size: 14px; }
    .grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; margin: 24px 0; }
    .metric { border: 1px solid var(--border); border-left: 3px solid var(--border); background: var(--bg-card); border-radius: var(--radius); padding: 18px; min-height: 84px; box-shadow: 0 1px 2px rgba(0, 0, 0, 0.25); transition: border-color .15s ease, transform .15s ease; }
    .metric:hover { border-color: #484f58; transform: translateY(-1px); }
    .label { color: var(--text-dim); font-size: 13px; }
    .value { font-size: 26px; font-weight: 700; margin-top: 10px; font-variant-numeric: tabular-nums; }
    section { border-top: 1px solid var(--border); padding-top: 22px; }
    section h2 { display: flex; align-items: center; gap: 10px; font-size: 18px; }
    section h2::before { content: ''; width: 4px; height: 18px; background: var(--accent); border-radius: 2px; display: inline-block; }
    table { width: 100%; border-collapse: collapse; font-size: 14px; }
    th, td { text-align: left; padding: 12px 8px; border-bottom: 1px solid var(--border-soft); }
    th { color: var(--text-dim); font-weight: 500; }
    .empty { color: var(--text-dim); padding: 28px 0; }
    .badge { display: inline-block; padding: 3px 10px; border-radius: 999px; font-size: 13px; font-weight: 600; font-variant-numeric: tabular-nums; }
    .badge.success { background: var(--success-bg); color: var(--success); }
    .badge.warning { background: var(--warning-bg); color: var(--warning); }
    .badge.danger { background: var(--danger-bg); color: var(--danger); }
    .badge.neutral { background: var(--neutral-bg); color: var(--neutral); }
    .trend-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
    .trend-card { border: 1px solid var(--border); border-left: 3px solid var(--border); background: var(--bg-card); border-radius: var(--radius); padding: 14px; transition: transform .15s ease; }
    .trend-card:hover { transform: translateY(-1px); }
    .trend-card svg { width: 100%; height: 56px; display: block; margin-top: 8px; }
    .accent-temp { border-left-color: #f0883e; }
    .accent-humidity { border-left-color: #58a6ff; }
    .accent-ph { border-left-color: #a371f7; }
    .accent-ec { border-left-color: #3fb950; }
    .accent-vpd { border-left-color: #2bb3c0; }
    .tile-src { font-size: 12px; font-weight: 400; color: var(--text-dim); margin-top: 4px; font-variant-numeric: tabular-nums; }
    .trend-card svg.swatch { width: 28px; height: 8px; display: inline-block; margin: 0 4px 0 0; vertical-align: middle; }
    .legend-item { display: inline-block; margin-right: 10px; white-space: nowrap; }
    @media (max-width: 720px) { .grid, .trend-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } header { display: block; } .status { display: block; margin-top: 8px; } }
  </style>
</head>
<body>
<main>
  <header><h1>🌱 Pomona Control Center</h1><div class="status" id="status">Connecting to services...</div></header>
  <form method="get" id="scope-form">
    <label for="farm-selector">Farm ID</label><input id="farm-selector" name="farm_id" required maxlength="128">
    <label for="zone-selector">Zone ID</label><input id="zone-selector" name="zone_id" required maxlength="128">
    <label for="history-kind">History</label><select id="history-kind" name="kind"><option value="events">Full packets</option><option value="observations">Modular observations</option></select>
    <label for="history-offset">History offset</label><input id="history-offset" name="offset" type="number" min="0" step="100" value="0">
    <button type="submit">Open zone</button>
  </form>
  <p id="scope-status" class="status">Select a farm and zone to monitor.</p>
  <p id="farm-time" class="status">Farm time: UTC (checking Core)</p>
  <section><h2>pH probe health</h2><div id="probe-health">Select a zone.</div><p>Sensitivity (mV per pH) is fitted from each stored buffer calibration and compared with the first one. Advisory: it never changes readings or calibrations.</p></section>
  <section><h2>Device health</h2><div id="devices">Select a zone.</div><p>Recent/silent is inferred from last receipt, not proof of connectivity. Quality is sender-reported.</p></section>
  <section><h2>Sensor history</h2><a id="history-download">Download this page as CSV</a><div id="history">Select a zone.</div><p>100 records per page; increase offset by 100 for older records. Pages can shift during ingestion. Modular observations do not feed reasoners.</p></section>
  <div class="grid">
    <div class="metric accent-temp"><div class="label">🌡️ Air temperature</div><div class="value" id="air">--</div></div>
    <div class="metric accent-humidity"><div class="label">💧 Humidity</div><div class="value" id="humidity">--</div></div>
    <div class="metric accent-ph"><div class="label">⚗️ pH</div><div class="value" id="ph">--</div></div>
    <div class="metric accent-ec"><div class="label">⚡ EC</div><div class="value" id="ec">--</div></div>
    <div class="metric accent-vpd" title="Vapour-pressure deficit from air temperature and humidity. Tomato: below 0.4 kPa leaves stay wet (mould risk); above 1.6 kPa plants close stomata."><div class="label">🌫️ VPD</div><div class="value" id="vpd">--</div></div>
  </div>
  <div id="zone-notes"></div>
  <section><h2>Sensor trends</h2><div id="trends" class="empty">Loading...</div></section>
  <section><h2>Integrated guarded pipeline</h2><div id="pipeline" class="empty">Loading...</div></section>
  <section><h2>Specialist results</h2><div id="specialists" class="empty">Loading...</div></section>
  <section><h2>Agronomy calculator (FAO-56 / NPK)</h2><div id="agronomy" class="empty">Loading...</div></section>
  <section><h2>Recent pipeline audit</h2><div id="audit" class="empty">Loading...</div></section>
  <section><h2>Guarded risk status</h2><div id="risk" class="empty">Loading...</div></section>
  <section><h2>Safety triage</h2><div id="safety" class="empty">Loading...</div></section>
  <section><h2>Alerts</h2>
    <p class="status">An alert is raised only after a risk lasts its wait time (10 min; humidity 30 min) and clears only after it stays away (15 min; humidity 30 min), so short flickers do not alert. Advisory only.</p>
    <div id="alerts" class="empty">Loading...</div>
  </section>
  <section><h2>Automation suggestions</h2>
    <label>Reviewer label (optional, unverified) <input id="automation-reviewer" maxlength="80" placeholder="Local operator"></label>
    <button id="automation-evaluate" type="button">Evaluate current risk</button>
    <p id="automation-feedback" role="status" aria-live="polite"></p>
    <div id="automation" class="empty">Loading...</div>
  </section>
  <section><h2>Advice cards</h2>
    <p class="status">HITL cards from automation suggestions. Approvals never execute actuators.</p>
    <div id="advice-cards" class="empty">Loading...</div>
  </section>
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
// Vapour-pressure deficit (kPa), same formula as the tomato rules (FAO-56 eq. 11). Null when a
// reading is missing or implausible, so it never invents a value.
const vpdKpa = (t, rh) => (typeof t === 'number' && typeof rh === 'number' && Number.isFinite(t) && Number.isFinite(rh)
  && t >= -5 && t <= 60 && rh >= 0 && rh <= 100)
  ? Math.round(Math.max(0.6108 * Math.exp(17.27 * t / (t + 237.3)) * (1 - rh / 100), 0) * 1000) / 1000 : null;
// Escape API/model text at HTML sinks, including quoted attribute values.
// Keep plain textContent values unescaped so they display exactly once.
const escapeHtml = (text) => String(text ?? '').replace(/[&<>"']/g, (char) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
}[char]));
const badge = (text, severity = 'neutral') => `<span class="badge ${escapeHtml(severity)}">${escapeHtml(text)}</span>`;
const riskSeverity = (level) => {
  const l = (level || '').toLowerCase();
  if (l.includes('high')) return 'danger';
  if (l.includes('medium') || l.includes('moderate')) return 'warning';
  return 'success';
};
const trustTone = new Map([['trusted', 'success'], ['partial', 'warning'], ['cannot_confirm', 'danger']]);
const trustFields = new Map([['ph', 'pH'], ['previous_ph', 'pH'], ['ec_ms_cm', 'EC'], ['humidity_pct', 'humidity'],
  ['air_temperature_c', 'air temperature'], ['backup_air_temperature_c', 'air temperature'], ['temperature_f', 'air temperature'],
  ['water_temperature_c', 'water temperature'], ['substrate_temperature_c', 'substrate temperature'],
  ['substrate_moisture_pct', 'moisture'], ['soil_moisture_pct', 'moisture'], ['timestamp', 'timestamp']]);
// Plain-language sensor trust: a badge for the verdict plus which readings were not used. `missing` (the sensor
// quality block's missing_fields) are probes that did not report in the latest reading; `fields` (vetoed_fields) are
// readings that were there but not trusted. A field in both is said once, as not reported.
const fieldNames = (fields) => [...new Set((fields || []).map(field => trustFields.get(field) || field))];
// Multi-device zones (docs/design/multi-device-zones-slice2.md 2.8): `zone` is the zone snapshot, or just {sources} for an
// advice card. `sources` maps a field to the device(s) that supplied it (or should have); `devices` carries each device's
// age_s, stale flag and supplied fields; `dashboard_judged` names devices the dashboard checked itself (PipelineResponse).
// Parts: fields not used (with their device), then probes of a quiet device, then probes no device reported.
const zoneTrustLine = (verdict, fields, missing, zone) => {
  const sources = zone.sources && typeof zone.sources === 'object' ? zone.sources : {};
  const devices = Array.isArray(zone.devices) ? zone.devices : null;
  const judged = Array.isArray(zone.dashboard_judged) ? zone.dashboard_judged : [];
  const byId = new Map((devices || []).map(device => [device.device_id, device]));
  const owners = (field) => {
    if (Object.prototype.hasOwnProperty.call(sources, field) && Array.isArray(sources[field])) return sources[field];
    const name = trustFields.get(field);
    const found = [];
    if (name) for (const key of Object.keys(sources)) {
      if (trustFields.get(key) === name && Array.isArray(sources[key])) sources[key].forEach(id => { if (!found.includes(id)) found.push(id); });
    }
    return found;
  };
  const named = (list, pick) => {  // field name -> devices, in the order the fields came
    const byName = new Map();
    for (const field of list || []) {
      const name = trustFields.get(field) || field;
      if (!byName.has(name)) byName.set(name, []);
      pick(field).forEach(id => { if (!byName.get(name).includes(id)) byName.get(name).push(id); });
    }
    return byName;
  };
  const missingNames = fieldNames(missing);
  const checked = (id) => (judged.includes(id) ? ' (checked by the dashboard)' : '');
  let text = 'All readings passed the sensor check';
  if (verdict === 'trusted') {
    if (devices) {
      const supplying = devices.filter(device => (device.supplied || []).length);
      if (supplying.length) {
        const noun = supplying.length === 1 ? 'device' : 'devices';
        const dashboard = supplying.filter(device => judged.includes(device.device_id)).map(device => `${device.device_id}${checked(device.device_id)}`);
        text += ` (${[`${supplying.length} ${noun}`, ...dashboard].join(', ')})`;
      }
    }
  } else {
    const parts = [];
    for (const [name, ids] of named((fields || []).filter(field => !missingNames.includes(trustFields.get(field) || field)), owners)) {
      parts.push(`${name}${ids.length ? ` (${ids[0]})${checked(ids[0])}` : ''} not used`);
    }
    const quiet = new Map();  // devices that are stale -> the probe names they were expected to supply
    const unreported = [];
    for (const [name, ids] of named(missing, owners)) {
      const stale = ids.filter(id => byId.has(id) && byId.get(id).stale === true);
      if (!stale.length) { unreported.push(name); continue; }
      const key = stale.join('\u0000');
      if (!quiet.has(key)) quiet.set(key, {ids: stale, names: []});
      quiet.get(key).names.push(name);
    }
    for (const {ids, names} of quiet.values()) {
      const since = ids.map(id => `${id} for ${typeof byId.get(id).age_s === 'number' ? ageText(byId.get(id).age_s) : 'an unknown time'}`);
      parts.push(`${names.join(', ')} not reported: no reading from ${since.join(', ')}`);
    }
    if (unreported.length) parts.push(`${unreported.join(', ')} not reported by any device in this zone`);
    if (!parts.length) parts.push('some readings not used');
    text = `Can't confirm: ${parts.join('; ')}`;
  }
  return `${badge(String(verdict).replace(/_/g, ' '), trustTone.get(verdict) || 'neutral')} ${escapeHtml(text)}`;
};
const trustLine = (verdict, fields, missing, zone) => {
  if (!verdict) return 'not reported';
  if (zone) return zoneTrustLine(verdict, fields, missing, zone);
  const notReported = fieldNames(missing);
  const notUsed = fieldNames(fields).filter(name => !notReported.includes(name));
  let text = 'All readings passed the sensor check';
  if (verdict !== 'trusted') {
    const parts = [];
    if (notReported.length) parts.push(`${notReported.join(', ')} not reported in the latest reading`);
    if (notUsed.length || !parts.length) parts.push(`${notUsed.join(', ') || 'some readings'} not used`);
    text = `Can't confirm: ${parts.join('; ')}`;
  }
  return `${badge(String(verdict).replace(/_/g, ' '), trustTone.get(verdict) || 'neutral')} ${escapeHtml(text)}`;
};
// A missing value (a probe that did not report) shown as an en dash; other values exactly as sent.
const dash = (x) => x === null || x === undefined ? '–' : x;
// Age of the latest reading, from the dashboard server's clock (overview.latest_age_s), never the browser's.
const ageText = (seconds) => seconds < 120 ? `${Math.round(seconds)} s` : seconds < 7200 ? `${Math.round(seconds / 60)} min`
  : seconds < 172800 ? `${(seconds / 3600).toFixed(1)} h` : `${Math.round(seconds / 86400)} days`;
// Farm time: Core stores UTC; the farm zone comes from Core's /health (via /api/farm-time) and is display only.
// timeCell returns escaped HTML: the time in the farm zone with its UTC offset, the original string in a title.
// Anything that is not an ISO time with a UTC offset (or no farm zone from Core) is shown exactly as before.
let farmTime = {available: false, farm_timezone: 'UTC'};
const isoWithOffset = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}(:?\d{2})?)$/i;
const formatters = new Map();
const farmFormatter = (zone) => {
  if (!formatters.has(zone)) formatters.set(zone, new Intl.DateTimeFormat('en-US', {timeZone: zone, hourCycle: 'h23',
    year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', timeZoneName: 'longOffset'}));
  return formatters.get(zone);
};
const farmParts = (date, zone) => {
  const parts = Object.fromEntries(farmFormatter(zone).formatToParts(date).map(part => [part.type, part.value]));
  const offset = (parts.timeZoneName || 'GMT').replace('GMT', '').replace(/^$/, '+00:00').replace(/^([+-]\d{2}):00$/, '$1');
  return {day: `${parts.year}-${parts.month}-${parts.day}`, time: `${parts.hour}:${parts.minute}`,
    offset: zone === 'UTC' || zone === 'Etc/UTC' ? 'UTC' : offset};
};
const farmTimeText = (raw) => {
  if (!farmTime.available || typeof raw !== 'string' || !isoWithOffset.test(raw.trim())) return null;
  const date = new Date(raw.trim().replace(' ', 'T'));
  if (Number.isNaN(date.getTime())) return null;
  try { const p = farmParts(date, farmTime.farm_timezone); return `${p.day} ${p.time} ${p.offset}`; } catch (error) { return null; }
};
const timeCell = (raw) => {
  const text = farmTimeText(raw);
  return text === null ? escapeHtml(raw) : `<span title="${escapeHtml(raw)}">${escapeHtml(text)}</span>`;
};
// The latest reading's time for the "no reading from this zone" line: farm time with its offset (the date too when it is
// not recent, or `full`), else UTC. Escaped by the caller.
const readingTime = (raw, full) => {
  const date = typeof raw === 'string' && isoWithOffset.test(raw.trim()) ? new Date(raw.trim().replace(' ', 'T')) : null;
  if (date === null || Number.isNaN(date.getTime())) return 'an unknown time';
  try {
    if (farmTime.available) { const p = farmParts(date, farmTime.farm_timezone); return `${full ? p.day + ' ' : ''}${p.time} ${p.offset}`; }
  } catch (error) { /* an unknown zone name: UTC below */ }
  const iso = date.toISOString();
  return `${full ? iso.slice(0, 10) + ' ' : ''}${iso.slice(11, 16)} UTC`;
};
const farmTimeLine = () => {
  if (!farmTime.available) return 'Farm time: UTC (Core did not report a farm time zone) · times below are UTC as stored';
  let change = 'no clock change in the next year';
  if (farmTime.next_offset_change) {
    const when = new Date(farmTime.next_offset_change);
    try { change = `clock changes to UTC${farmTime.offset_after_change || '?'} on ${farmParts(when, farmTime.farm_timezone).day}`; }
    catch (error) { change = 'clock change coming'; }
  }
  return `Farm time: ${farmTime.farm_timezone} (UTC${farmTime.utc_offset_now}, ${change}) · times below are farm time (hover for the stored UTC time)`;
};
async function loadFarmTime() {
  try {
    const info = await (await scopedFetch('/api/farm-time')).json();
    farmTime = info && info.available && typeof info.farm_timezone === 'string' ? info : {available: false, farm_timezone: 'UTC'};
    if (farmTime.available) farmFormatter(farmTime.farm_timezone);  // an unknown zone name throws here: show UTC as before
  } catch (error) { farmTime = {available: false, farm_timezone: 'UTC'}; }
  $('farm-time').textContent = farmTimeLine();
}
const listSeverity = (list) => (list && list.length ? 'warning' : 'success');
const boolSeverity = (flag) => (flag ? 'warning' : 'success');
// sparkline(series, color): series is a list of {label, points: [{t, v}], dash}. One series with no times is drawn by index,
// exactly as before (the single-device page). With times (multi-device zones): one line per series on a shared y scale, x
// = sample time over the 60 minutes before the newest plotted point, a legend of device ids with each dash pattern.
const dashPatterns = ['', '6 3', '2 3', '8 3 2 3'];
const dashAttr = (n) => (dashPatterns[n % dashPatterns.length] ? ` stroke-dasharray="${dashPatterns[n % dashPatterns.length]}"` : '');
const sparklineTimed = (series, color) => {
  const windowMs = 3600000;
  const usable = series.map((s, i) => ({label: s.label, dash: s.dash === undefined ? i : s.dash,
    points: s.points.filter((p) => Number.isFinite(p.t) && typeof p.v === 'number' && Number.isFinite(p.v))}));
  const newest = Math.max(...usable.flatMap((s) => s.points.map((p) => p.t)));
  const shown = usable.map((s) => ({...s, points: s.points.filter((p) => p.t >= newest - windowMs && p.t <= newest).sort((a, b) => a.t - b.t)}));
  const drawn = shown.filter((s) => s.points.length >= 2);
  const legend = shown.length ? `<p class="status">${shown.map((s) => `<span class="legend-item"><svg class="swatch" viewBox="0 0 28 8"><line x1="1" y1="4" x2="27" y2="4" stroke="${color}" stroke-width="2"${dashAttr(s.dash)}/></svg>${escapeHtml(s.label)}${s.points.length < 2 ? ': not enough data' : ''}</span>`).join('')}</p>` : '';
  if (!drawn.length) return `<p class="status">Not enough data yet</p>${legend}`;
  const w = 280, h = 56, pad = 4;
  const all = drawn.flatMap((s) => s.points.map((p) => p.v));
  const min = Math.min(...all), max = Math.max(...all);
  const range = max - min || 1;
  const lines = drawn.map((s) => {
    const points = s.points.map((p) => {
      const x = pad + ((p.t - (newest - windowMs)) / windowMs) * (w - pad * 2);
      const y = h - pad - ((p.v - min) / range) * (h - pad * 2);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `<polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"${dashAttr(s.dash)}/>`;
  }).join('');
  const stats = drawn.map((s) => {
    const v = s.points.map((p) => p.v);
    return `<p class="status">${escapeHtml(s.label)}: min ${Math.min(...v).toFixed(1)} · max ${Math.max(...v).toFixed(1)} · latest ${v[v.length - 1].toFixed(1)}</p>`;
  }).join('');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">${lines}</svg>${legend}${stats}`;
};
const sparkline = (series, color) => {
  if (series.some((s) => s.points.some((p) => p.t !== undefined))) return sparklineTimed(series, color);
  const values = series.length ? series[0].points.map((p) => p.v) : [];
  const nums = values.filter((v) => typeof v === 'number' && !Number.isNaN(v));
  if (nums.length < 2) return '<p class="status">Not enough data yet</p>';
  const w = 280, h = 56, pad = 4;
  const min = Math.min(...nums), max = Math.max(...nums);
  const range = max - min || 1;
  const step = (w - pad * 2) / (nums.length - 1);
  const points = nums.map((v, i) => {
    const x = pad + i * step;
    const y = h - pad - ((v - min) / range) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"><polyline points="${points}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/></svg><p class="status">min ${min.toFixed(1)} · max ${max.toFixed(1)} · latest ${nums[nums.length - 1].toFixed(1)}</p>`;
};
let twinPreview = null;
const pageQuery = new URLSearchParams(location.search);
const selectedFarm = pageQuery.get('farm_id') || '';
const selectedZone = pageQuery.get('zone_id') || '';
const hasScope = Boolean(selectedFarm && selectedZone);
$('farm-selector').value = selectedFarm;
$('zone-selector').value = selectedZone;
const historyKind = pageQuery.get('kind') === 'observations' ? 'observations' : 'events';
const historyOffset = Math.max(0, Number.parseInt(pageQuery.get('offset') || '0', 10) || 0);
$('history-kind').value = historyKind;
$('history-offset').value = historyOffset;
const scopedUrl = (url) => {
  const [path, query = ''] = url.split('?');
  const params = new URLSearchParams(query);
  if (hasScope) { params.set('farm_id', selectedFarm); params.set('zone_id', selectedZone); }
  return path + (params.size ? '?' + params.toString() : '');
};
const scopedFetch = (url, options) => fetch(scopedUrl(url), options);
$('scope-status').textContent = hasScope ? `Farm: ${selectedFarm} · Zone: ${selectedZone}` : 'Enter both IDs above. No cross-zone recommendations are shown.';
if (hasScope) $('history-download').href = scopedUrl(`/api/history/export.csv?kind=${historyKind}&offset=${historyOffset}`);
async function renderHistory() {
  const devices = await (await scopedFetch('/api/devices')).json();
  $('devices').innerHTML = devices.available ? `<table><thead><tr><th scope="col">Device</th><th scope="col">Last seen</th><th scope="col">Availability</th><th scope="col">Sample stale</th><th scope="col">Reported quality</th></tr></thead><tbody>${(devices.result.devices || []).map(d => `<tr><td>${escapeHtml(d.device_id)}</td><td>${timeCell(d.last_seen)}</td><td>${escapeHtml(d.availability)}</td><td>${d.sample_stale ? 'yes' : 'no'}</td><td>${escapeHtml(d.quality || 'not reported')}</td></tr>`).join('')}</tbody></table>` : escapeHtml(devices.error || 'Device status unavailable');
  const probes = await (await scopedFetch('/api/probe-health')).json();
  const probeTone = { ok: 'success', baseline_only: 'neutral', weakening: 'warning', worn: 'danger', suspect: 'danger', no_data: 'neutral' };
  $('probe-health').innerHTML = !probes.available ? escapeHtml(probes.error || 'Probe health unavailable')
    : (probes.result.probes || []).length ? `<table><thead><tr><th scope="col">Probe</th><th scope="col">Status</th><th scope="col">Sensitivity</th><th scope="col">vs first</th><th scope="col">pH 7 shift</th><th scope="col">Calibrations</th><th scope="col">Since last</th><th scope="col">Advice</th></tr></thead><tbody>${probes.result.probes.map(p => `<tr><td>${escapeHtml(p.sensor_id)}</td><td>${badge(p.status, probeTone[p.status] || 'neutral')}</td><td>${p.latest ? escapeHtml(Number(p.latest.sensitivity_mv_per_ph).toFixed(0)) + ' mV/pH' : '--'}</td><td>${p.sensitivity_vs_first_pct === undefined ? '--' : escapeHtml(p.sensitivity_vs_first_pct) + ' %'}</td><td>${p.v_at_ph7_shift_v === undefined ? '--' : escapeHtml((p.v_at_ph7_shift_v * 1000).toFixed(0)) + ' mV'}</td><td>${escapeHtml(p.calibrations ?? 0)}</td><td>${p.days_since_last_calibration === null || p.days_since_last_calibration === undefined ? '--' : escapeHtml(p.days_since_last_calibration) + ' d'}</td><td>${escapeHtml((p.reasons || []).join(' '))}</td></tr>`).join('')}</tbody></table>`
      : '<p class="status">No pH calibrations recorded yet. Record one with POST /v1/sensors/calibrations (see the pilot doc).</p>';
  const history = await (await scopedFetch(`/api/history?kind=${historyKind}&offset=${historyOffset}`)).json();
  if (!history.available) { $('history').textContent = history.error || 'History unavailable'; return; }
  const rows = history.result[historyKind] || [];
  $('history').innerHTML = rows.length ? `<table><thead><tr><th scope="col">Sample time</th><th scope="col">Device</th><th scope="col">Reading</th><th scope="col">Quality</th></tr></thead><tbody>${rows.map(r => `<tr><td>${timeCell(r.timestamp)}</td><td>${escapeHtml(r.device_id)}</td><td>${escapeHtml(historyKind === 'observations' ? `${r.measurement}: ${r.value ?? 'missing'} ${r.unit}` : `Temperature ${dash(r.air_temperature_c)} °C · pH ${dash(r.ph)} · EC ${dash(r.ec_ms_cm)}`)}</td><td>${escapeHtml(r.quality || 'full packet — see sensor-quality assessment')}</td></tr>`).join('')}</tbody></table>` : 'No records on this page.';
}
let automationBusy = false;
let telemetryUnavailable = true;
// Multi-device zones only (slice 2): Device columns and alert detail lines; and the status lines under the tiles.
let zoneMulti = false;
let zoneNotesShown = false;
const setZoneNotes = (lines) => {
  if (!lines.length && !zoneNotesShown) return;  // a single-device zone never touches the element
  $('zone-notes').innerHTML = lines.map((line) => `<p class="status">${escapeHtml(line)}</p>`).join('');
  zoneNotesShown = lines.length > 0;
};
const markUnavailable = (message) => {
  telemetryUnavailable = true;
  twinPreview = null;
  setZoneNotes([]);
  $('status').textContent = `STALE / unavailable: ${message}`;
  ['air', 'humidity', 'ph', 'ec', 'vpd', 'alerts', 'pipeline', 'risk', 'safety', 'explanation', 'digital-twin', 'advice-cards'].forEach(id => { $(id).textContent = 'Unavailable — refresh required'; });
  setAutomationBusy(automationBusy);
};
const setAutomationBusy = (busy) => {
  automationBusy = busy;
  document.querySelectorAll('#automation-evaluate, .automation-approve, .automation-reject')
    .forEach(button => { button.disabled = busy || telemetryUnavailable; });
};
setAutomationBusy(false);
async function automationRequest(url, body) {
  const response = await scopedFetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  if (!response.ok) throw new Error(`Request failed (HTTP ${response.status}).`);
  const payload = await response.json();
  if (!payload.available) throw new Error(payload.error || 'Automation request failed.');
  return payload.result;
}
async function renderAlerts() {
  const payload = await (await scopedFetch('/api/alerts')).json();
  if (!payload.available) { $('alerts').textContent = payload.error || 'Alert monitor unavailable'; return; }
  const items = payload.result.alerts || [];
  const recent = (payload.result.events || []).slice(0, 5);
  const tone = { active: 'danger', pending: 'warning', recovering: 'neutral' };
  const label = { active: 'active', pending: 'waiting', recovering: 'recovering' };
  const table = items.length
    ? `<table><thead><tr><th scope="col">State</th>${zoneMulti ? '<th scope="col">Device</th>' : ''}<th scope="col">Rule</th><th scope="col">Message</th><th scope="col">First seen</th><th scope="col">Raised</th><th scope="col">Clear since</th></tr></thead><tbody>${items.map(a => `<tr><td>${badge(label[a.state] || a.state, tone[a.state] || 'neutral')}</td>${zoneMulti ? `<td>${escapeHtml(a.device_id || '--')}</td>` : ''}<td>${escapeHtml(a.rule_id)}</td><td>${escapeHtml(a.message || '')}${zoneMulti && a.detail ? `<div class="status">${escapeHtml(a.detail)}</div>` : ''}</td><td>${timeCell(a.since)}</td><td>${timeCell(a.raised_at || '--')}</td><td>${timeCell(a.recovering_since || '--')}</td></tr>`).join('')}</tbody></table>`
    : '<p class="status">No open alerts.</p>';
  const history = recent.length
    ? `<p class="status">Recent: ${recent.map(e => `${escapeHtml(e.rule_id)}${zoneMulti && e.device_id ? ` (${escapeHtml(e.device_id)})` : ''} ${escapeHtml(e.event)} at ${timeCell(e.sample_time)}`).join(' · ')}</p>`
    : '';
  $('alerts').innerHTML = table + history;
}
const outcomeBadge = (status) => status ? badge(status, {awaiting: 'warning', confirmed: 'success', not_recovered: 'danger'}[status] || 'neutral') : '--';
async function renderAutomation() {
  const automation = await (await scopedFetch('/api/automation')).json();
  if (!automation.available) {
    $('automation').textContent = automation.error || 'Automation engine unavailable';
    return;
  }
  const suggestions = automation.result.suggestions || [];
  if (!suggestions.length) {
    $('automation').innerHTML = `<p class="status">No suggestions yet. Click "Evaluate current risk" to check the latest reading against automation rules.</p>`;
    return;
  }
  $('automation').innerHTML = `<table><thead><tr><th scope="col">Rule</th><th scope="col">Action</th><th scope="col">Message</th><th scope="col">Status</th><th scope="col">Outcome</th><th scope="col">Decision time</th><th scope="col">Reviewer (unverified)</th><th scope="col"></th></tr></thead><tbody>${suggestions.map(s => `<tr><td>${escapeHtml(s.rule_id)}</td><td>${escapeHtml(s.action)}</td><td>${escapeHtml(s.message)}</td><td>${badge(s.status, s.status === 'pending' ? 'warning' : (s.status === 'approved' ? 'success' : 'neutral'))}</td><td>${outcomeBadge(s.outcome_status)}</td><td>${timeCell(s.decided_at || '--')}</td><td>${escapeHtml(s.reviewer || '--')}</td><td>${s.status === 'pending' ? `<button type="button" class="automation-approve" data-id="${escapeHtml(s.id)}">Approve</button> <button type="button" class="automation-reject" data-id="${escapeHtml(s.id)}">Reject</button>` : ''}</td></tr>`).join('')}</tbody></table><p class="status">A person decides every suggestion; nothing here executes an actuator.</p>`;
  setAutomationBusy(automationBusy);
  await renderAdviceCards();
}
async function renderAdviceCards() {
  const payload = await (await scopedFetch('/api/advice-cards')).json();
  if (!payload.available) {
    $('advice-cards').textContent = payload.error || 'Advice cards unavailable';
    return;
  }
  const cards = payload.result.cards || [];
  if (!cards.length) {
    $('advice-cards').innerHTML = `<p class="status">No advice cards yet. Evaluate current risk first.</p>`;
    return;
  }
  $('advice-cards').innerHTML = `<div class="grid">${cards.map(card => `
    <article class="metric">
      <div class="label">${escapeHtml(card.opportunity || 'operations')} · ${badge(card.severity || 'warn', card.severity === 'info' ? 'neutral' : 'warning')}</div>
      <div class="value" style="font-size:1.05rem">${escapeHtml(card.title || card.summary || '--')}</div>
      <p class="status">${escapeHtml(card.summary || '')}</p>
      <p class="status">Sensor trust: ${trustLine((card.evidence || {}).trust_verdict, (card.evidence || {}).vetoed_fields, (card.evidence || {}).missing_fields, (card.evidence || {}).sources ? {sources: card.evidence.sources} : undefined)}</p>
      <p class="status">Checks: ${escapeHtml((card.safe_next_checks || []).join('; ') || 'none')}</p>
      <p class="status">Sample: ${timeCell((card.evidence || {}).sample_time || 'unknown')} · Evidence: ${escapeHtml((card.evidence || {}).provenance_status || 'legacy_missing_snapshot')}</p>
      <p class="status">Readings: ${escapeHtml(Object.entries((card.evidence || {}).readings || {}).map(([key, value]) => value === null || value === undefined ? `${key}: –` : `${key}: ${value} ${((card.evidence || {}).units || {})[key] || ''}`).join('; ') || 'not recorded')}</p>
      <details><summary>Recorded evidence</summary><pre>${escapeHtml(JSON.stringify(card.evidence || {}, null, 2))}</pre></details>
      <p class="status">Blocked: ${badge((card.blocked_actions || []).join(', ') || 'none', (card.blocked_actions || []).length ? 'danger' : 'success')}</p>
      <p class="status">Status: ${badge(card.status || 'pending', card.status === 'pending' ? 'warning' : 'neutral')}</p>
      ${card.outcome ? `<p class="status">Outcome: ${outcomeBadge(card.outcome.status)} · clean readings ${escapeHtml(card.outcome.clean_streak ?? 0)}/${escapeHtml(card.outcome.required_clean_readings ?? '--')} · until ${timeCell(card.outcome.deadline || '--')}</p>` : ''}
    </article>`).join('')}</div>`;
}
document.body.addEventListener('click', async (event) => {
  const target = event.target;
  const evaluate = target.id === 'automation-evaluate';
  const approve = target.classList.contains('automation-approve');
  const reject = target.classList.contains('automation-reject');
  if (!(evaluate || approve || reject) || automationBusy || telemetryUnavailable) return;
  setAutomationBusy(true);
  const feedback = $('automation-feedback');
  feedback.textContent = 'Saving request...';
  let saved = false;
  try {
    const path = approve ? 'approve' : 'reject';
    const url = evaluate ? '/api/automation/evaluate' : `/api/automation/suggestions/${encodeURIComponent(target.dataset.id)}/${path}`;
    const result = await automationRequest(url, evaluate ? {} : {reviewer: $('automation-reviewer').value.trim() || null});
    saved = true;
    feedback.textContent = evaluate ? `${(result.suggestions || []).length} suggestion(s) returned (existing retries reused).` : `Decision recorded: ${result.status}. No actuator executed.`;
    await renderAutomation();
  } catch (error) {
    feedback.textContent = saved ? 'Request saved, but list refresh failed. Refresh to check history.' : `${error.message} Check history before retrying; the request may have reached the service.`;
  } finally {
    setAutomationBusy(false);
  }
});
async function refresh() {
  await loadFarmTime();
  if (!hasScope) { markUnavailable('Select a farm and zone'); return; }
  if (refresh.running) return;
  refresh.running = true;
  try { await renderHistory(); await refreshData(); }
  catch (error) { markUnavailable(error.message || 'Dashboard API unavailable'); }
  finally { refresh.running = false; }
}
async function refreshData() {
  const response = await scopedFetch('/api/overview');
  if (!response.ok) throw new Error(`Overview HTTP ${response.status}`);
  const data = await response.json();
  if (!data.core_available || !data.latest_event) { markUnavailable(data.error || 'No sensor event available'); return; }
  telemetryUnavailable = false;
  setAutomationBusy(automationBusy);
  $('status').textContent = `Core online · ${data.recent_events.length} recent events`;
  const event = data.latest_event;
  // No reading from the zone for too long: say so instead of the trust line of the last stored reading.
  const age = typeof data.latest_age_s === 'number' ? data.latest_age_s : null;
  let stale = Number(data.stale_after_s) > 0 && age !== null && age > Number(data.stale_after_s);
  // Multi-device zone: latest_age_s is the newest device's age, but a slow device is live for 3x its own interval, so the
  // zone-wide line is for a zone view with no reading at all: every device stale by the snapshot's own per-device flags.
  const snapshot = data.zone_snapshot || null;
  if (snapshot && stale) stale = !snapshot.sensor && (snapshot.devices || []).every((device) => device.stale === true);
  const zoneView = snapshot && snapshot.sensor ? snapshot : null;  // the zone-view path; else today's newest-packet path
  let zoneTrust = zoneView ? {sources: zoneView.sources || {}, devices: zoneView.devices || [], dashboard_judged: []} : undefined;
  zoneMulti = data.zone_multi_device === true;
  const trustFor = (verdict, vetoed, missing) => stale
    ? `${badge('cannot confirm', 'danger')} ${escapeHtml(`Can't confirm: no reading from this zone for ${ageText(age)} (last ${readingTime(event.timestamp, age >= 43200)})`)}`
    : trustLine(verdict, vetoed, missing, zoneTrust);
  const notes = [];
  if (data.zone_snapshot_error) notes.push(`Zone view unavailable: showing the newest packet (${event.device_id || 'unknown device'})`);
  if (zoneView) {
    for (const name of zoneView.context_conflicts || []) {
      const used = (zoneView.context || {})[name];
      notes.push(`Devices disagree on ${name} (using ${used !== null && typeof used === 'object' ? JSON.stringify(used) : used} from ${(zoneView.context_source || {})[name]})`);
    }
  }
  setZoneNotes(notes);
  if (zoneView) {
    const fields = zoneView.fields || {};
    const tile = (id, name, format) => {
      const f = fields[name];
      if (!f) { $(id).textContent = '--'; return; }
      const lines = [typeof f.age_s === 'number' ? `${f.device_id} · ${ageText(f.age_s)}` : `${f.device_id}`,
        ...(f.others || []).map((o) => `also ${o.device_id}: ${format(o.value)}${o.vetoed && !f.disagree ? ' (not used)' : ''}`),
        ...(f.disagree ? ['probes disagree: check both with a meter'] : [])];  // docs/design/slow-drift-pair-check.md 4b
      $(id).innerHTML = `${escapeHtml(format(f.value))}${lines.map((line) => `<div class="tile-src">${escapeHtml(line)}</div>`).join('')}`;
    };
    tile('air', 'air_temperature_c', (v) => value(v, ' °C'));
    tile('humidity', 'humidity_pct', (v) => value(v, ' %'));
    tile('ph', 'ph', (v) => value(v));
    tile('ec', 'ec_ms_cm', (v) => value(v, ' mS/cm'));
    const air = fields.air_temperature_c, humid = fields.humidity_pct;
    const vpd = air && humid ? vpdKpa(air.value, humid.value) : null;
    if (vpd === null) $('vpd').textContent = '--';
    else {
      const from = air.device_id === humid.device_id
        ? `${air.device_id}${typeof air.age_s === 'number' && typeof humid.age_s === 'number' ? ` · ${ageText(Math.max(air.age_s, humid.age_s))}` : ''}`
        : `air ${air.device_id}, humidity ${humid.device_id}`;
      $('vpd').innerHTML = `${escapeHtml(`${vpd.toFixed(2)} kPa${vpd < 0.4 ? ' · low' : vpd >= 1.6 ? ' · high' : ''}`)}<div class="tile-src">${escapeHtml(from)}</div>`;
    }
  } else if (event) {
    $('air').textContent = value(event.air_temperature_c, ' °C');
    $('humidity').textContent = value(event.humidity_pct, ' %');
    $('ph').textContent = value(event.ph);
    $('ec').textContent = value(event.ec_ms_cm, ' mS/cm');
    const vpd = vpdKpa(event.air_temperature_c, event.humidity_pct);
    $('vpd').textContent = vpd === null ? '--' : `${vpd.toFixed(2)} kPa${vpd < 0.4 ? ' · low' : vpd >= 1.6 ? ' · high' : ''}`;
  }
  const chronological = [...data.recent_events].reverse();
  const single = (pick) => [{label: '', points: chronological.map((e) => ({v: pick(e)}))}];
  if (snapshot && data.device_events) {
    // One line per device that carries the field, against sample time (docs 2.8); device n keeps dash pattern n in every card.
    const deviceIds = Object.keys(data.device_events).sort();
    const perDevice = (pick) => deviceIds.map((id, n) => ({label: id, dash: n,
      points: (data.device_events[id] || []).map((e) => ({t: Date.parse(e.timestamp), v: pick(e)}))}))
      .filter((s) => s.points.some((p) => typeof p.v === 'number' && Number.isFinite(p.v)));
    const vpdSeries = perDevice((e) => vpdKpa(e.air_temperature_c, e.humidity_pct));
    const unplotted = (snapshot.devices || []).map((d) => d.device_id).filter((id) => !deviceIds.includes(id)).sort();
    $('trends').innerHTML = `<div class="trend-grid">
    <div class="trend-card accent-temp"><div class="label">🌡️ Air temperature (°C)</div>${sparkline(perDevice((e) => e.air_temperature_c), '#f0883e')}</div>
    <div class="trend-card accent-humidity"><div class="label">💧 Humidity (%)</div>${sparkline(perDevice((e) => e.humidity_pct), '#58a6ff')}</div>
    <div class="trend-card accent-ph"><div class="label">⚗️ pH</div>${sparkline(perDevice((e) => e.ph), '#a371f7')}</div>
    <div class="trend-card accent-ec"><div class="label">⚡ EC (mS/cm)</div>${sparkline(perDevice((e) => e.ec_ms_cm), '#3fb950')}</div>
    <div class="trend-card accent-vpd"><div class="label">🌫️ VPD (kPa)</div>${vpdSeries.length ? sparkline(vpdSeries, '#2bb3c0') : '<p class="status">No device carries both air temperature and humidity</p>'}</div>
  </div>${unplotted.length ? `<p class="status">${unplotted.map((id) => `${escapeHtml(id)}: not plotted`).join(' · ')}</p>` : ''}`;
  } else $('trends').innerHTML = `<div class="trend-grid">
    <div class="trend-card accent-temp"><div class="label">🌡️ Air temperature (°C)</div>${sparkline(single((e) => e.air_temperature_c), '#f0883e')}</div>
    <div class="trend-card accent-humidity"><div class="label">💧 Humidity (%)</div>${sparkline(single((e) => e.humidity_pct), '#58a6ff')}</div>
    <div class="trend-card accent-ph"><div class="label">⚗️ pH</div>${sparkline(single((e) => e.ph), '#a371f7')}</div>
    <div class="trend-card accent-ec"><div class="label">⚡ EC (mS/cm)</div>${sparkline(single((e) => e.ec_ms_cm), '#3fb950')}</div>
    <div class="trend-card accent-vpd"><div class="label">🌫️ VPD (kPa)</div>${sparkline(single((e) => vpdKpa(e.air_temperature_c, e.humidity_pct)), '#2bb3c0')}</div>
  </div>`;
  const pipelineResponse = await scopedFetch('/api/pipeline');
  const pipeline = await pipelineResponse.json();
  if (!pipeline.available) {
    $('pipeline').textContent = pipeline.error || 'Integrated pipeline unavailable';
  } else {
    const result = pipeline.result;
    if (zoneTrust) zoneTrust = {...zoneTrust, sources: pipeline.sources || zoneTrust.sources, dashboard_judged: pipeline.dashboard_judged || []};
    const decision = result.final_decision || {};
    const quality = result.sensor_quality || {};
    const water = result.water_irrigation || {};
    const nutrient = result.nutrient_ph_ec || {};
    const crop = result.crop_risk || {};
    const safety = result.safety || {};
    const waterNutrientLabels = [...(water.irrigation_risk_labels || []), ...(nutrient.nutrient_risk_labels || [])];
    const blockedActions = decision.blocked_actions || [];
    $('pipeline').innerHTML = `<div class="grid"><div class="metric"><div class="label">Risk level</div><div class="value">${badge(decision.risk_level || '--', riskSeverity(decision.risk_level))}</div></div><div class="metric"><div class="label">Sensor quality</div><div class="value">${badge((quality.data_quality_labels || []).join(', ') || 'normal', listSeverity(quality.data_quality_labels))}</div></div><div class="metric"><div class="label">Water / nutrient</div><div class="value">${badge(waterNutrientLabels.join(', ') || 'normal', listSeverity(waterNutrientLabels))}</div></div><div class="metric"><div class="label">Human review</div><div class="value">${badge(decision.human_review_required ? 'required' : 'not required', boolSeverity(decision.human_review_required))}</div></div></div><p class="status">Sensor trust: ${trustFor(decision.trust_verdict, decision.vetoed_fields, quality.missing_fields)}</p>${stale ? `<p class="status">Pipeline result from the last reading at ${escapeHtml(readingTime(event.timestamp, true))}.</p>` : ''}<p class="status">Pipeline: ${escapeHtml(result.pipeline_id || '--')} · Blocked actions: ${badge(blockedActions.join(', ') || 'none', blockedActions.length ? 'danger' : 'success')}</p><p class="status">Read-only dashboard view. No action is executed.</p>`;
    const specialistRows = [
      ['Sensor quality', quality.data_quality_labels || [], quality.source || 'deterministic_rules', quality.human_review_required],
      ['Water / irrigation', water.irrigation_risk_labels || [], water.source || 'deterministic_rules', water.human_review_required],
      ['Nutrient / pH-EC', nutrient.nutrient_risk_labels || [], nutrient.source || 'deterministic_rules', nutrient.human_review_required],
      ['Crop risk', crop.risk_labels || [], crop.source || 'deterministic_rules', crop.human_review_required],
      ['Actuator safety', safety.safety_labels || [], safety.source || 'deterministic_safety_rules', safety.human_approval_required],
    ];
    $('specialists').innerHTML = `<table><thead><tr><th scope="col">Specialist</th><th scope="col">Labels</th><th scope="col">Source</th><th scope="col">Review</th></tr></thead><tbody>${specialistRows.map(row => `<tr><td>${escapeHtml(row[0])}</td><td>${badge(row[1].join(', ') || 'normal', listSeverity(row[1]))}</td><td>${escapeHtml(row[2])}</td><td>${badge(row[3] ? 'required' : 'not required', boolSeverity(row[3]))}</td></tr>`).join('')}</tbody></table><p class="status">Specialists advise independently; deterministic safety remains final authority. Dashboard view is read-only.</p>`;
    const agronomy = result.agronomy_calc;
    if (!agronomy) {
      $('agronomy').innerHTML = `<p class="status">No estimate for the latest reading — zone weather, area, crop coefficient, or an NPK target were not supplied.</p>`;
    } else {
      const irrigation = agronomy.irrigation;
      const fertilizer = agronomy.fertilizer;
      const irrigationCards = irrigation
        ? `<div class="metric"><div class="label">Reference ET (ETo)</div><div class="value">${escapeHtml(value(irrigation.reference_et_mm_day, ' mm/day'))}</div></div><div class="metric"><div class="label">Crop ET (ETc)</div><div class="value">${escapeHtml(value(irrigation.crop_et_mm_day, ' mm/day'))}</div></div><div class="metric"><div class="label">Expected irrigation</div><div class="value">${escapeHtml(value(irrigation.expected_irrigation_liters, ' L/day'))}</div></div>`
        : '';
      const fertilizerCards = fertilizer
        ? `<div class="metric"><div class="label">Urea</div><div class="value">${escapeHtml(value(fertilizer.urea_g, ' g'))}</div></div><div class="metric"><div class="label">DAP</div><div class="value">${escapeHtml(value(fertilizer.dap_g, ' g'))}</div></div><div class="metric"><div class="label">SOP</div><div class="value">${escapeHtml(value(fertilizer.sop_g, ' g'))}</div></div>`
        : '';
      $('agronomy').innerHTML = `<div class="grid">${irrigationCards}${fertilizerCards}</div><p class="status">FAO-56 ET and NPK stoichiometry estimate for this zone. Advisory only — never affects risk labels or blocked actions.</p>`;
    }
  }
  const audit = await (await scopedFetch('/api/audit')).json();
  if (!audit.available) {
    $('audit').textContent = audit.error || 'Pipeline audit unavailable';
  } else if (!(audit.result.events || []).length) {
    $('audit').textContent = 'No pipeline evaluations recorded yet.';
  } else {
    $('audit').innerHTML = `<table><thead><tr><th scope="col">Time</th><th scope="col">Scenario</th><th scope="col">Risk</th><th scope="col">Review</th><th scope="col">Blocked actions</th></tr></thead><tbody>${audit.result.events.map(e => `<tr><td>${timeCell(e.evaluated_at || '--')}</td><td>${escapeHtml(e.scenario_id || '--')}</td><td>${badge(e.risk_level || '--', riskSeverity(e.risk_level))}</td><td>${badge(e.human_review_required ? 'required' : 'not required', boolSeverity(e.human_review_required))}</td><td>${badge((e.blocked_actions || []).join(', ') || 'none', (e.blocked_actions || []).length ? 'danger' : 'success')}</td></tr>`).join('')}</tbody></table><p class="status">Audit view contains summaries only; sensor payloads are excluded.</p>`;
  }
  const riskResponse = await scopedFetch('/api/risk');
  const risk = await riskResponse.json();
  if (!risk.available) {
    $('risk').textContent = risk.error || 'Risk chain unavailable';
  } else {
    const result = risk.result;
    const quality = result.sensor_quality || {};
    const water = result.water_irrigation || {};
    const safety = result.actuator_safety || {};
    const riskBlocked = result.blocked_actions || [];
    $('risk').innerHTML = `<div class="grid"><div class="metric"><div class="label">Sensor quality</div><div class="value">${badge((quality.data_quality_labels || []).join(', ') || 'normal', listSeverity(quality.data_quality_labels))}</div></div><div class="metric"><div class="label">Water risk</div><div class="value">${badge((water.irrigation_risk_labels || []).join(', ') || 'normal', listSeverity(water.irrigation_risk_labels))}</div></div><div class="metric"><div class="label">Safety decision</div><div class="value">${badge(safety.decision || '--', (safety.decision || '').toLowerCase() === 'allowed' ? 'success' : 'danger')}</div></div><div class="metric"><div class="label">Human review</div><div class="value">${badge(result.human_review_required ? 'required' : 'not required', boolSeverity(result.human_review_required))}</div></div></div><p class="status">Sensor trust: ${trustFor((result.trust_gate || {}).trust_verdict, (result.trust_gate || {}).vetoed_fields, quality.missing_fields)}</p><p class="status">Blocked actions: ${badge(riskBlocked.join(', ') || 'none', riskBlocked.length ? 'danger' : 'success')}</p>`;
  }
  const safetyResponse = await scopedFetch('/api/safety');
  const safetyData = await safetyResponse.json();
  if (!safetyData.available) {
    $('safety').textContent = safetyData.error || 'Safety triage unavailable';
  } else {
    const result = safetyData.result;
    const safetyReview = result.safety_labels?.includes('human_review_required');
    const safetyBlocked = result.blocked_actions || [];
    $('safety').innerHTML = `<div class="grid"><div class="metric"><div class="label">Decision</div><div class="value">${badge(safetyReview ? 'review' : 'allowed', safetyReview ? 'warning' : 'success')}</div></div><div class="metric"><div class="label">Safety labels</div><div class="value">${badge((result.safety_labels || []).join(', ') || 'none', listSeverity(result.safety_labels))}</div></div><div class="metric"><div class="label">Blocked actions</div><div class="value">${badge(safetyBlocked.join(', ') || 'none', safetyBlocked.length ? 'danger' : 'success')}</div></div><div class="metric"><div class="label">Human review</div><div class="value">${badge(result.human_review_required ? 'required' : 'not required', boolSeverity(result.human_review_required))}</div></div></div><p>${escapeHtml(result.safe_alternative || 'Continue routine monitoring.')}</p><p class="status">Dashboard view is read-only. No action is executed.</p>`;
  }
  await renderAlerts();
  await renderAutomation();
  if (!data.recent_events.length) { $('events').textContent = 'No sensor events recorded yet.'; return; }
  $('events').innerHTML = `<table><thead><tr><th scope="col">Time</th>${zoneMulti ? '<th scope="col">Device</th>' : ''}<th scope="col">Farm</th><th scope="col">Zone</th><th scope="col">Crop</th><th scope="col">Temperature</th><th scope="col">Humidity</th></tr></thead><tbody>${data.recent_events.map(e => `<tr><td>${timeCell(e.timestamp)}</td>${zoneMulti ? `<td>${escapeHtml(e.device_id)}</td>` : ''}<td>${escapeHtml(e.farm_id)}</td><td>${escapeHtml(e.zone_id)}</td><td>${escapeHtml(e.crop)}</td><td>${escapeHtml(value(e.air_temperature_c, ' °C'))}</td><td>${escapeHtml(value(e.humidity_pct, ' %'))}</td></tr>`).join('')}</tbody></table>`;
  const services = await (await scopedFetch('/api/services')).json();
  $('services').innerHTML = `<table><thead><tr><th scope="col">Service</th><th scope="col">Status</th><th scope="col">Detail</th></tr></thead><tbody>${Object.entries(services.services).map(([name, item]) => `<tr><td>${escapeHtml(name)}</td><td>${badge(item.available ? 'online' : 'offline', item.available ? 'success' : 'danger')}</td><td>${escapeHtml(item.available ? (item.health.service || '') : (item.error || ''))}</td></tr>`).join('')}</tbody></table>`;
  const runtimes = await (await scopedFetch('/api/runtimes')).json();
  if (!runtimes.available) {
    $('runtimes').textContent = runtimes.error || 'Runtime status unavailable';
  } else {
    $('runtimes').innerHTML = `<table><thead><tr><th scope="col">Runtime</th><th scope="col">Status</th><th scope="col">Configured model</th><th scope="col">Models seen</th></tr></thead><tbody>${Object.entries(runtimes.result).map(([name, item]) => `<tr><td>${escapeHtml(name)}</td><td>${badge(item.available ? 'available' : 'offline', item.available ? 'success' : 'danger')}</td><td>${escapeHtml(item.model || 'rules')}</td><td>${escapeHtml((item.models_seen || []).map(model => typeof model === 'string' ? model : (model.id || model.name || '')).filter(Boolean).join(', ') || (item.error || 'none'))}</td></tr>`).join('')}</tbody></table>`;
  }
  const twin = twinPreview || await (await scopedFetch('/api/digital-twin')).json();
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
    $('digital-twin').innerHTML = `<div class="grid"><div class="metric"><div class="label">Mode</div><div class="value">${escapeHtml(result.mode || 'forecast_only')}</div></div><div class="metric"><div class="label">Horizon</div><div class="value">${escapeHtml(last.minutes_from_now || 0)} min</div></div><div class="metric"><div class="label">Temperature</div><div class="value">${escapeHtml(value(first.air_temperature_c))} to ${escapeHtml(value(last.air_temperature_c))} °C</div></div><div class="metric"><div class="label">Humidity</div><div class="value">${escapeHtml(value(first.humidity_pct))} to ${escapeHtml(value(last.humidity_pct))} %</div></div></div><p>Guarded result: ${escapeHtml(decision.risk_level || '--')} · Review: ${decision.human_review_required ? 'required' : 'not required'} · Blocked: ${escapeHtml((decision.blocked_actions || []).join(', ') || 'none')}</p><p>${escapeHtml(result.safety_note || 'Forecast only. Validate against live sensors.')}</p><p class="status">This preview is illustrative and does not execute or authorize any action.</p>`;
  }
  const explanation = await (await scopedFetch('/api/explanation')).json();
  if (!explanation.available) {
    $('explanation').textContent = explanation.error || 'Advisor unavailable';
  } else {
    const result = explanation.result;
    $('explanation').innerHTML = `<p>${escapeHtml(result.explanation || 'No explanation returned.')}</p><p class="status">Advisory only. Human review is required before operational action.</p>`;
  }
}
document.getElementById('twin-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (telemetryUnavailable || !hasScope) return;
  $('digital-twin').textContent = 'Running guarded forecast preview...';
  const scenario = {
    temperature_delta_c: Number($('twin-temperature').value),
    humidity_delta_pct: Number($('twin-humidity').value),
    irrigation_duration_min: Number($('twin-irrigation').value),
    ventilation_pct: Number($('twin-ventilation').value),
    horizon_steps: Number($('twin-horizon').value),
  };
  try {
  const response = await scopedFetch('/api/digital-twin', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(scenario)});
  if (!response.ok) throw new Error(`Forecast HTTP ${response.status}`);
  const result = await response.json();
  if (!result.available) $('digital-twin').textContent = result.error || 'Digital Twin unavailable';
  else { twinPreview = result; refresh(); }
  } catch (error) { $('digital-twin').textContent = `Forecast unavailable: ${error.message}`; }
});
  refresh().catch(() => $('status').textContent = 'Dashboard API unavailable');
setInterval(() => refresh().catch(() => {}), 10000);
</script>
</body>
</html>"""
