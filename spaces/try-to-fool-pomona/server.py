"""HTTP side of "Try to fool Pomona": serves the page and one JSON API, holds no user data.

  GET  /                 the page (static/index.html)
  GET  /api/info         tricks, zones, verdict table, caps, build commit
  GET  /api/health       {"ok": true}
  POST /api/act          {scenario?, seed?, commands?, advance?} -> {scenario, view}

The client holds the scenario (seed + recorded commands + ticks run). A request names its session by sending that
scenario; the server finds the live session in a small in-memory cache (idle TTL 30 min, at most 500, least recently
used goes first) or rebuilds it by replaying the scenario. Nothing is stored on disk and nothing is logged.

Limits: 24 simulated hours per session, 64 KB per request, a per-IP token bucket. No auth: there is no hardware and no
user data behind this page.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.middleware.gzip import GZipMiddleware

import game

STATIC = Path(__file__).resolve().parent / "static"


@dataclass
class Limits:
    max_body_bytes: int = 64 * 1024
    cache_size: int = 500
    idle_ttl_s: float = 30 * 60
    bucket_capacity: float = 40.0       # requests worth of burst per IP
    bucket_refill_per_s: float = 1.0    # sustained: one light request a second per IP
    cost_per_60_ticks: float = 1.0      # simulating costs tokens too: 2 simulated hours = 4 extra
    max_buckets: int = 10_000
    max_in_flight: int = 24             # requests being worked on at once; more get a 503 and retry (one CPU does the simulating)


class SessionCache:
    """Live sessions by scenario. A session is taken out while a request uses it, and put back under its new scenario."""

    def __init__(self, size: int, idle_ttl_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.size, self.idle_ttl_s, self.clock = size, idle_ttl_s, clock
        self._items: "OrderedDict[str, Tuple[game.Session, float]]" = OrderedDict()
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._items)

    def take(self, key: str) -> Optional[game.Session]:
        with self._lock:
            self._expire()
            entry = self._items.pop(key, None)
        return entry[0] if entry else None

    def put(self, key: str, session: game.Session) -> None:
        evicted: List[game.Session] = []
        with self._lock:
            self._expire(evicted)
            old = self._items.pop(key, None)
            if old:
                evicted.append(old[0])
            self._items[key] = (session, self.clock())
            while len(self._items) > self.size:
                evicted.append(self._items.popitem(last=False)[1][0])
        for gone in evicted:
            gone.close()

    def _expire(self, evicted: Optional[List[game.Session]] = None) -> None:
        now = self.clock()
        gone = evicted if evicted is not None else []
        while self._items:
            key, (session, used) = next(iter(self._items.items()))
            if now - used < self.idle_ttl_s:
                break
            del self._items[key]
            gone.append(session)
        if evicted is None:
            for session in gone:
                session.close()


class TokenBuckets:
    """Per-IP token buckets. A request needs one token to start; its real cost is charged afterwards (it may go negative)."""

    def __init__(self, capacity: float, refill_per_s: float, max_buckets: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity, self.refill, self.max_buckets, self.clock = capacity, refill_per_s, max_buckets, clock
        self._buckets: "OrderedDict[str, List[float]]" = OrderedDict()
        self._lock = threading.Lock()

    def _level(self, ip: str) -> List[float]:
        now = self.clock()
        bucket = self._buckets.pop(ip, None) or [self.capacity, now]
        bucket[0] = min(self.capacity, bucket[0] + (now - bucket[1]) * self.refill)
        bucket[1] = now
        self._buckets[ip] = bucket
        while len(self._buckets) > self.max_buckets:
            self._buckets.popitem(last=False)
        return bucket

    def allow(self, ip: str) -> bool:
        with self._lock:
            return self._level(ip)[0] >= 1.0

    def charge(self, ip: str, cost: float) -> None:
        with self._lock:
            self._level(ip)[0] -= cost


def client_ip(request: Request) -> str:
    """The address the proxy saw: the last X-Forwarded-For entry (the first ones can be forged), else the socket peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()[:64]
    return request.client.host if request.client else "unknown"


class BodyLimit:
    """ASGI middleware: refuse a request body over the cap, by Content-Length or by counting what arrives."""

    def __init__(self, app: Any, max_bytes: int) -> None:
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope["headers"])
        try:
            declared = int(headers.get(b"content-length", b"0") or 0)
        except ValueError:
            declared = 0
        too_big = JSONResponse({"error": "request body too large"}, status_code=413)
        if declared > self.max_bytes:
            return await too_big(scope, receive, send)
        seen = 0

        async def counted() -> Dict[str, Any]:
            nonlocal seen
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    raise BodyTooLarge()
            return message

        try:
            await self.app(scope, counted, send)
        except BodyTooLarge:
            await too_big(scope, receive, send)


class BodyTooLarge(Exception):
    pass


class SecurityHeaders:
    """ASGI middleware: no sniffing, no outside scripts or styles (the page loads nothing from other hosts)."""

    POLICY = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
              "base-uri 'none'; form-action 'none'")

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        api = scope["path"].startswith("/api/")

        async def with_headers(message: Dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                         (b"content-security-policy", self.POLICY.encode())]
                if api:
                    extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)

        await self.app(scope, receive, with_headers)


def create_app(limits: Optional[Limits] = None, clock: Callable[[], float] = time.monotonic) -> FastAPI:
    limits = limits or Limits()
    cache = SessionCache(limits.cache_size, limits.idle_ttl_s, clock)
    buckets = TokenBuckets(limits.bucket_capacity, limits.bucket_refill_per_s, limits.max_buckets, clock)
    page_info = game.info()
    busy = {"now": 0}  # requests inside run_in_threadpool (the event loop is single-threaded, so plain ints are safe)
    app = FastAPI(title="Try to fool Pomona", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cache, app.state.buckets, app.state.limits, app.state.busy = cache, buckets, limits, busy
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(BodyLimit, max_bytes=limits.max_body_bytes)
    app.add_middleware(SecurityHeaders)

    @app.get("/api/health")
    def health() -> Dict[str, bool]:
        return {"ok": True}

    @app.get("/api/info")
    def get_info() -> Dict[str, Any]:
        return page_info

    @app.post("/api/act")
    async def act(request: Request) -> Response:
        ip = client_ip(request)
        if not buckets.allow(ip):
            return JSONResponse({"error": "Slow down a little: too many requests from your address."},
                                status_code=429, headers={"Retry-After": "5"})
        if busy["now"] >= limits.max_in_flight:
            return JSONResponse({"error": "The Space is busy right now. Trying again in a moment."},
                                status_code=503, headers={"Retry-After": "3"})
        buckets.charge(ip, 1.0)
        try:
            body = json.loads(await request.body() or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            busy["now"] += 1
            try:
                result, ticks_run = await run_in_threadpool(play, body)
            finally:
                busy["now"] -= 1
        except ValueError as error:  # includes bad JSON
            return JSONResponse({"error": str(error)}, status_code=400)
        buckets.charge(ip, limits.cost_per_60_ticks * ticks_run / 60)
        return JSONResponse(result)

    def play(body: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
        unknown = set(body) - {"scenario", "seed", "commands", "advance"}
        if unknown:
            raise ValueError("unknown fields in the request")
        commands = body.get("commands", [])
        advance = body.get("advance", 0)
        if not isinstance(commands, list) or len(commands) > 8 or not all(isinstance(c, dict) for c in commands):
            raise ValueError("commands must be a short list")
        if isinstance(advance, bool) or not isinstance(advance, int) or not 0 <= advance <= game.MAX_ADVANCE_TICKS:
            raise ValueError(f"advance must be a whole number from 0 to {game.MAX_ADVANCE_TICKS}")
        ran = 0
        session: Optional[game.Session] = None
        if body.get("scenario") is None:
            seed = body.get("seed")
            if seed is None:
                seed = secrets.randbelow(10**6)
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
                raise ValueError("seed must be a whole number")
            session = game.Session.start_new(seed)
            ran = game.WARMUP_TICKS
        else:
            scenario = game.check_scenario(body["scenario"])
            key = game.scenario_key(scenario)
            session = cache.take(key)
            if session is None:
                session = game.Session.build(scenario)
                ran = scenario["ticks"]
        try:
            for cmd in commands:
                session.command({k: v for k, v in cmd.items() if k != "t"})
            ran += session.advance(advance)
            result = {"scenario": session.scenario(), "view": session.view()}
        except Exception:
            session.close()  # state is unknown after a failed command: the client still has its last good scenario
            raise
        cache.put(game.scenario_key(result["scenario"]), session)
        return result, ran

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


app = create_app()
