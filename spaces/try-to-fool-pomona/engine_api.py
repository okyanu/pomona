"""What the page's Web Worker calls: request checks plus play / info / rebuild, around one live `game.Session`.

The Space is static. This file runs in the visitor's browser (Pyodide) next to `game.py` and the vendored engine, and
in plain CPython for the tests. Nothing here talks to a network, and there is no server behind it.

The page keeps the scenario (seed + recorded commands + ticks run) and sends it with every request. The worker
holds one live session, keyed by that scenario: a request for the scenario it holds continues it, any other scenario is
rebuilt by replaying it (a page reload, a replay link). A rebuild can be done in slices so the page can show progress.

Entry point for the worker: `handle(kind, json_text) -> json_text`, kinds `info`, `act`, `begin`, `step`.
"""

from __future__ import annotations

import json
import secrets
from typing import Any, Dict, Generator, Optional

import game

REBUILD_SLICE_TICKS = 120  # the rebuild reports progress every simulated hour


class SyncLoop:
    """The only 'event loop' the engine needs here: it drives a coroutine that never waits on real I/O.

    In rules_only mode every `await` in the pipeline is on a coroutine that returns without suspending, so one
    send(None) runs it to StopIteration. If it ever suspends (a pending future would mean real I/O) it fails loudly.
    Pyodide has no usable blocking event loop, so the browser build installs this one (`install_sync_loop`).
    """

    def run_until_complete(self, coro: Any) -> Any:
        try:
            coro.send(None)
        except StopIteration as stop:
            return stop.value
        coro.close()
        raise RuntimeError("the pipeline suspended on a pending future: it is not rules_only-pure")


def install_sync_loop() -> None:
    game.LOOP = SyncLoop()


def build_in_slices(scenario: Dict[str, Any], slice_ticks: int = REBUILD_SLICE_TICKS) -> Generator[int, None, game.Session]:
    """`game.Session.build` in steps: yields the session's tick after every slice, returns the finished session.

    Ticks and commands happen in the same order as in `Session.build`, so the result is identical.
    """
    session = game.Session(scenario["seed"])

    def run_to(tick: int) -> Generator[int, None, None]:
        while session.tick < tick:
            session.advance(min(slice_ticks, tick - session.tick))
            yield session.tick

    try:
        for cmd in scenario["commands"]:
            yield from run_to(cmd["t"])
            session.command({k: v for k, v in cmd.items() if k != "t"})
        yield from run_to(scenario["ticks"])
    except Exception:
        session.close()
        raise
    return session


class Engine:
    """One live session. Not thread-safe: the worker answers one request at a time."""

    def __init__(self) -> None:
        self.session: Optional[game.Session] = None
        self.key: Optional[str] = None
        self._pending: Optional[Generator[int, None, game.Session]] = None
        self._pending_scenario: Optional[Dict[str, Any]] = None

    def close(self) -> None:
        self._drop_pending()
        self._drop_session()

    def _drop_session(self) -> None:
        if self.session is not None:
            self.session.close()
        self.session, self.key = None, None

    def _drop_pending(self) -> None:
        if self._pending is not None:
            self._pending.close()  # the generator's own cleanup closes its half-built session
        self._pending, self._pending_scenario = None, None

    def info(self) -> Dict[str, Any]:
        return game.info()

    # Rebuilding a long session in slices -----------------------------------------------------------

    def begin(self, body: Any) -> Dict[str, Any]:
        """Start a sliced rebuild of body["scenario"] unless the live session already is that scenario.

        Returns {"rebuild": bool, "total": ticks}. When "rebuild" is true, call `step` until it says done.
        """
        if not isinstance(body, dict) or body.get("scenario") is None:
            return {"rebuild": False, "total": 0}
        scenario = game.check_scenario(body["scenario"])
        self._drop_pending()
        if self.session is not None and self.key == game.scenario_key(scenario):
            return {"rebuild": False, "total": scenario["ticks"]}
        self._pending, self._pending_scenario = build_in_slices(scenario), scenario
        return {"rebuild": True, "total": scenario["ticks"]}

    def step(self) -> Dict[str, Any]:
        """Run one slice of the rebuild. Returns {"tick", "total", "done"}."""
        if self._pending is None or self._pending_scenario is None:
            raise ValueError("there is no rebuild in progress")
        scenario = self._pending_scenario
        try:
            tick = next(self._pending)
        except StopIteration as finished:
            self._drop_session()
            self.session, self.key = finished.value, game.scenario_key(scenario)
            self._pending, self._pending_scenario = None, None
            return {"tick": scenario["ticks"], "total": scenario["ticks"], "done": True}
        except Exception:
            self._pending, self._pending_scenario = None, None
            raise
        return {"tick": tick, "total": scenario["ticks"], "done": False}

    # Playing ---------------------------------------------------------------------------------------

    def act(self, body: Any) -> Dict[str, Any]:
        """{scenario?, seed?, commands?, advance?} -> {scenario, view}. Raises ValueError with a visitor-safe message."""
        if not isinstance(body, dict):
            raise ValueError("body must be a JSON object")
        if set(body) - {"scenario", "seed", "commands", "advance"}:
            raise ValueError("unknown fields in the request")
        commands = body.get("commands", [])
        advance = body.get("advance", 0)
        if not isinstance(commands, list) or len(commands) > 8 or not all(isinstance(c, dict) for c in commands):
            raise ValueError("commands must be a short list")
        if isinstance(advance, bool) or not isinstance(advance, int) or not 0 <= advance <= game.MAX_ADVANCE_TICKS:
            raise ValueError(f"advance must be a whole number from 0 to {game.MAX_ADVANCE_TICKS}")
        session = self._session_for(body)
        try:
            for cmd in commands:
                session.command({k: v for k, v in cmd.items() if k != "t"})
            session.advance(advance)
            result = {"scenario": session.scenario(), "view": session.view()}
        except Exception:
            session.close()  # state is unknown after a failed command; the page still has its last good scenario
            raise
        self.session, self.key = session, game.scenario_key(result["scenario"])
        return result

    def _session_for(self, body: Dict[str, Any]) -> game.Session:
        """The live session to play on, taken out of `self` while the request uses it."""
        if body.get("scenario") is None:
            seed = body.get("seed")
            if seed is None:
                seed = secrets.randbelow(10**6)
            if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed < 2**31:
                raise ValueError("seed must be a whole number")
            self.close()
            return game.Session.start_new(seed)
        scenario = game.check_scenario(body["scenario"])
        key = game.scenario_key(scenario)
        self._drop_pending()
        if self.session is not None and self.key == key:
            session, self.session, self.key = self.session, None, None
            return session
        self._drop_session()
        return game.Session.build(scenario)


# The worker's single engine and its text entry point ---------------------------------------------------

_ENGINE = Engine()


def handle(kind: str, text: str = "") -> str:
    """JSON text in, JSON text out. A refused request is {"error": message}; anything else is {"result": ...}."""
    try:
        if kind == "info":
            return json.dumps({"result": _ENGINE.info()})
        body = json.loads(text or "{}")
        if kind == "act":
            return json.dumps({"result": _ENGINE.act(body)})
        if kind == "begin":
            return json.dumps({"result": _ENGINE.begin(body)})
        if kind == "step":
            return json.dumps({"result": _ENGINE.step()})
        raise ValueError("unknown request")
    except ValueError as error:  # includes bad JSON
        return json.dumps({"error": str(error)})
