"""Pomona's alert path in one process, one reading at a time: Core's checks plus the real router and alerts.

What a reading goes through on the real stack (Core stores it, its outcome feed asks the model-router for
a verdict, the automation-engine turns labels into cards), as one importable class:

  1. Core: reject a dead clock (sample time before Core's `min_sample_time`).
  2. Core: build the sticky trusted baseline of the stream (core/app/trusted_baseline.py, loaded by path)
     from the stream's earlier readings, less what the pipeline vetoed, and from the calibrations. The engine
     keeps it up to date reading by reading (`StreamBaseline`, byte-identical to Core's `stream_baseline`), so a
     late reading costs no more than the first.
  3. Model-router: the real `app.pipeline.evaluate_pipeline` in `rules_only` mode, with the stream's last
     11 packets as history. No network, no model weights.
  4. Automation-engine: the real `AlertMonitor` (alerts.py, in-memory SQLite) with the real rules.yaml
     rules, advanced by the reading's sample time (never the wall clock).

Shared by `scripts/score_fake_greenhouse.py --offline` and the "Try to fool Pomona" Space, so both use one
code path. Run it with the model-router venv (httpx, pydantic, pydantic-settings, pyyaml, fastapi).

The pipeline keeps a module-level `_now`, so every pipeline call (set `_now`, evaluate, restore) runs under
one module-level lock: engines may be driven from several threads, one reading at a time.

Files this module loads (relative to the repo root; the Space vendors the same layout):
  services/model-router/app/            the `app` package, imported as `app.pipeline`
  services/core/app/trusted_baseline.py loaded by path (stdlib only)
  services/automation-engine/app/alerts.py  loaded by path (stdlib only)
  services/automation-engine/app/rules.yaml the rules (read with `load_rules`; the file is not needed by the
                                            engine itself, callers pass the parsed rules)
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
ROUTER_DIR = ROOT / "services" / "model-router"
CORE_APP = ROOT / "services" / "core" / "app"
AUTOMATION_APP = ROOT / "services" / "automation-engine" / "app"

SENSOR_ACTION = "check_sensor"  # every rule with this action is a sensor card (sensor_check, sensor_flatline), not advice
# Core's SensorEvent optional fields: Core's stored packet has them as null when absent.
CORE_OPTIONAL = ("substrate_temperature_c", "substrate_moisture_pct", "weather", "zone_area_m2", "crop_kc",
                 "npk_target")
# Core's default `min_sample_time` (services/core/app/config.py): earlier sample times are a dead clock.
# Core's `max_future_sample_s` (a sample time ahead of Core's wall clock) is not mirrored: a replay runs on virtual
# sample time, with no wall clock to be ahead of.
MIN_SAMPLE_TIME = datetime(2020, 1, 1, tzinfo=timezone.utc)
HISTORY_PACKETS = 11  # the model-router's temporal checks see this many earlier packets per zone

# One lock for every pipeline call in the process: the pipeline's `_now` is module-level state.
PIPELINE_LOCK = threading.Lock()
_LOADED: Dict[str, Any] = {}


# --- Small helpers ----------------------------------------------------------------------

def parse_ts(text: str) -> datetime:
    """Any ISO spelling (Z or offset) as an aware UTC datetime."""
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_rules(text: str) -> List[Dict[str, Any]]:
    """Read rules.yaml without PyYAML: the file is a flat list of rules with scalar and list values."""
    rules: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    key = ""
    for raw in text.splitlines():
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            if body != "rules:":
                break
            continue
        if indent == 2 and body.startswith("- "):
            current = {}
            rules.append(current)
            body, indent = body[2:], 4
        if indent == 4:
            key, _, value = body.partition(":")
            value = value.strip()
            if value.startswith("["):
                current[key] = [item.strip() for item in value[1:-1].split(",") if item.strip()]
            elif value in ("", ">-", ">"):
                current[key] = [] if value == "" else ""
            else:
                current[key] = int(value) if value.isdigit() else value
        elif body.startswith("- "):
            current[key].append(body[2:].strip())
        else:
            current[key] = (current[key] + " " + body).strip()
    return rules


def load_rules(path: Optional[Path] = None) -> List[Dict[str, Any]]:
    """The real rules.yaml (default: the automation-engine's)."""
    return parse_rules(Path(path or AUTOMATION_APP / "rules.yaml").read_text())


def alert_defaults(automation_app: Optional[Path] = None) -> Tuple[int, int]:
    """Alert monitor defaults (raise, clear seconds) from automation-engine config.py."""
    text = (Path(automation_app or AUTOMATION_APP) / "config.py").read_text()
    raise_after = re.search(r"alert_raise_after_seconds:[^=]*=\s*Field\(default=(\d+)", text)
    clear_after = re.search(r"alert_clear_after_seconds:[^=]*=\s*Field\(default=(\d+)", text)
    return (int(raise_after.group(1)) if raise_after else 600, int(clear_after.group(1)) if clear_after else 900)


def pipeline_risk_labels(result: Dict[str, Any]) -> List[str]:
    """Same as services/core/app/outcome_feed.py (copied: that package cannot be imported next to this one)."""
    return list(dict.fromkeys([
        *(result.get("sensor_quality") or {}).get("data_quality_labels", []),
        *(result.get("water_irrigation") or {}).get("irrigation_risk_labels", []),
        *(result.get("nutrient_ph_ec") or {}).get("nutrient_risk_labels", []),
        *(result.get("crop_risk") or {}).get("risk_labels", []),
    ]))


def core_packet(sent: Dict[str, Any]) -> Dict[str, Any]:
    """The reading as Core stores and forwards it: UTC timestamp with Z, absent optionals as null."""
    packet = {k: v for k, v in sent.items() if k != "source"}
    for key in CORE_OPTIONAL:
        packet.setdefault(key, None)
    packet["timestamp"] = iso_z(parse_ts(sent["timestamp"]))
    return packet


def load_module(name: str, path: Path):
    """A stdlib-only module loaded by file path (once per process), so its package never clashes with another `app`."""
    key = f"{name}:{path}"
    if key not in _LOADED:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module  # needed before exec for dataclass-style lookups
        spec.loader.exec_module(module)
        _LOADED[key] = module
    return _LOADED[key]


def load_pipeline(router_dir: Path = ROUTER_DIR):
    """The model-router's `app.pipeline`, with its audit writes switched off (once per process)."""
    key = f"pipeline:{router_dir}"
    if key not in _LOADED:
        existing = sys.modules.get("app")
        if existing is not None and not str(getattr(existing, "__file__", "") or "").startswith(str(router_dir)):
            raise ImportError(f"another `app` package is already imported ({getattr(existing, '__file__', existing)}); "
                              "run the engine in a process of its own (the model-router venv)")
        if str(router_dir) not in sys.path:
            sys.path.insert(0, str(router_dir))
        from app import pipeline  # model-router's app package
        pipeline.write_pipeline_audit = lambda record: None  # no audit files, as in the scorer
        _LOADED[key] = pipeline
    return _LOADED[key]


# --- The engine ---------------------------------------------------------------------------

class InProcessPomona:
    """Feed readings in sample-time order with `observe`; record calibrations with `calibrate`.

    `rules` are the parsed rules.yaml rules (`load_rules()`), `defaults` the monitor's (raise, clear)
    seconds (`alert_defaults()`). The engine keeps, per zone, the last 11 packets; per stream
    (farm, zone, device), the readings the trusted baseline is built from and the calibrations; and one
    AlertMonitor. Not thread-safe by itself per engine: serialise calls on one engine; different engines
    may run in different threads (pipeline calls share PIPELINE_LOCK). `loop` (optional) is an event loop
    shared with other engines; the engine then leaves it open on close.
    """

    def __init__(self, rules: Optional[List[Dict[str, Any]]] = None, defaults: Optional[Tuple[int, int]] = None, *,
                 router_dir: Path = ROUTER_DIR, core_app: Path = CORE_APP, automation_app: Path = AUTOMATION_APP,
                 min_sample_time: datetime = MIN_SAMPLE_TIME, max_events: int = 1_000_000,
                 loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        self.rules = rules if rules is not None else load_rules(Path(automation_app) / "rules.yaml")
        self.defaults = defaults if defaults is not None else alert_defaults(automation_app)
        self.min_sample_time = min_sample_time
        self._pipeline = load_pipeline(Path(router_dir))
        self._baseline = load_module("pomona_trusted_baseline", Path(core_app) / "trusted_baseline.py")
        alerts = load_module("pomona_alerts", Path(automation_app) / "alerts.py")
        self.monitor = alerts.AlertMonitor(self.rules, self.defaults[0], self.defaults[1], db_path=None,
                                           max_events=max_events)
        self.card_labels = {label for r in self.rules if r.get("action") != SENSOR_ACTION
                            for label in r["match_any_labels"]}
        self.check_labels = {label for r in self.rules if r.get("action") == SENSOR_ACTION
                             for label in r["match_any_labels"]}
        # A server holding many engines passes one shared loop (each reading runs under PIPELINE_LOCK, so
        # one thread uses it at a time); an engine without one owns its loop and closes it.
        self._loop = loop if loop is not None else asyncio.new_event_loop()
        self._owns_loop = loop is None
        self._history: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}  # per zone, the last 11 packets
        self._streams: Dict[Tuple[str, str, str], Any] = {}  # per stream, its StreamBaseline (Core's trusted reference)
        # (farm_id or None, zone_id, device_id or None, measurement, performed_at); None matches any
        self._calibrations: List[Tuple[Optional[str], str, Optional[str], str, str]] = []

    # Core's calibration endpoint: a person checked the probe against a reference meter.

    def calibrate(self, zone_id: str, field: str, at: Any, farm_id: Optional[str] = None,
                  device_id: Optional[str] = None) -> None:
        """Record a calibration of `field` in the zone at sample time `at` (datetime or ISO text).

        Like Core's calibration record: it re-anchors the trusted reference of that probe, so only readings
        sampled from `at` on count; one taken after a reading does not apply to it. `farm_id` and `device_id`
        narrow it to one stream, left out it applies to every stream of the zone.
        """
        stamp = at if isinstance(at, datetime) else parse_ts(str(at))
        self._calibrations.append((farm_id, zone_id, device_id, field, iso_z(stamp)))

    def _stream_calibrations(self, stream: Tuple[str, str, str]) -> List[Dict[str, Any]]:
        farm, zone, device = stream
        return [{"measurement": field, "performed_at": at} for f, z, d, field, at in self._calibrations
                if z == zone and f in (None, farm) and d in (None, device)]

    # One reading

    def observe(self, event: Dict[str, Any], *, include_result: bool = False) -> Dict[str, Any]:
        """Run one reading through Core's checks, the pipeline and the alert monitor.

        `event` is the sensor packet the device sent (farm_id, zone_id, device_id, timestamp, readings...).
        Returns `accepted` / `rejection` (Core's verdict: a dead-clock or unreadable timestamp is rejected and
        leaves no trace), then for an accepted reading: `labels` (risk labels), `trust` (verdict),
        `vetoed_fields`, `card_labels` (labels some advice card matches), `sensor_check_labels`,
        `alert_events` (raised / recovered, with sample times) and `ignored` (the monitor already saw a
        later sample of the stream). `include_result` adds the full pipeline result as `pipeline`.
        """
        try:
            sample = parse_ts(str(event["timestamp"]))
        except (KeyError, ValueError):
            return {"accepted": False, "rejection": "invalid_timestamp"}
        if sample < self.min_sample_time:
            return {"accepted": False, "rejection": "dead_clock", "sample_time": sample}
        sensor = core_packet(event)
        sensor.update(received_at=iso_z(sample + timedelta(seconds=1)), mqtt_retained=False)
        farm_id, zone_id, device_id = event["farm_id"], event["zone_id"], event["device_id"]
        zone_key = (farm_id, zone_id)
        prior = [{k: v for k, v in p.items() if k not in ("received_at", "mqtt_retained")}
                 for p in self._history.get(zone_key, [])[-HISTORY_PACKETS:]]
        farm = {"crop": sensor["crop"], "system_type": sensor["system_type"], "zone_id": sensor["zone_id"],
                "weather": sensor.get("weather"), "zone_area_m2": sensor.get("zone_area_m2"),
                "crop_kc": sensor.get("crop_kc"), "npk_target": sensor.get("npk_target")}
        stream = (farm_id, zone_id, device_id)
        baseline = self._baseline
        tracked = self._streams.get(stream)
        if tracked is None:
            tracked = self._streams[stream] = baseline.StreamBaseline(
                baseline.DEFAULT_WINDOW_S, baseline.DEFAULT_MIN_N, baseline.DEFAULT_MAX_AGE_S or None,
                baseline.DEFAULT_SCAN_LIMIT)
        reference = tracked.baseline(self._stream_calibrations(stream), sample)
        pipeline = self._pipeline
        with PIPELINE_LOCK:
            original_now = pipeline._now
            pipeline._now = lambda now=sample + timedelta(seconds=1): now
            try:
                result = self._loop.run_until_complete(pipeline.evaluate_pipeline(
                    farm, sensor, [], {"action_type": "continue_monitoring"}, "core_feed", "rules_only",
                    "core_feed", history=prior, stream_baseline=reference or None))
            finally:
                pipeline._now = original_now
        history = self._history.setdefault(zone_key, [])
        history.append(sensor)
        del history[:-HISTORY_PACKETS]
        tracked.add({**sensor, "timestamp": sample, "vetoed_fields": result["trust_gate"]["vetoed_fields"]})
        labels = pipeline_risk_labels(result)
        verdict = self.monitor.observe(farm_id, zone_id, device_id, sample, labels)
        out = {"accepted": True, "rejection": None, "farm_id": farm_id, "zone_id": zone_id, "device_id": device_id,
               "sample_time": sample, "labels": labels, "trust": result["trust_gate"]["trust_verdict"],
               "vetoed_fields": result["trust_gate"]["vetoed_fields"],
               "card_labels": sorted(set(labels) & self.card_labels),
               "sensor_check_labels": sorted(set(labels) & self.check_labels),
               "alert_events": verdict["events"], "ignored": bool(verdict.get("ignored"))}
        if include_result:
            out["pipeline"] = result
        return out

    def states(self, farm_id: Optional[str] = None, zone_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """The alert monitor's current alert states (open and pending cards)."""
        return self.monitor.states(farm_id, zone_id)

    def close(self) -> None:
        self.monitor.close()
        if self._owns_loop:
            self._loop.close()

    def __enter__(self) -> "InProcessPomona":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
