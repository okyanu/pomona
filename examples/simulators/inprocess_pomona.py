"""Pomona's alert path in one process, one reading at a time: Core's checks plus the real router and alerts.

What a reading goes through on the real stack (Core stores it, its outcome feed asks the model-router for
a verdict, the automation-engine turns labels into cards), as one importable class:

  1. Core: reject a dead clock (sample time before Core's `min_sample_time`) and a packet with no reading at
     all (every reading field absent or null); a packet with some readings missing is accepted.
  2. Core: build the sticky trusted baseline of the stream (core/app/trusted_baseline.py, loaded by path)
     from the stream's earlier readings, less what the pipeline vetoed, and from the calibrations. The engine
     keeps it up to date reading by reading (`StreamBaseline`, byte-identical to Core's `stream_baseline`), so a
     late reading costs no more than the first.
  3. Model-router: the real `app.pipeline.evaluate_pipeline` in `rules_only` mode, with the stream's last
     11 packets as history. No network, no model weights. In a multi-device zone (another device of the farm and zone
     sent a packet within 7 days of the reading) it also passes `device_fields`, the fields the device has sent in that
     window, as Core's feed does.
  4. Automation-engine: the real `AlertMonitor` (alerts.py, in-memory SQLite) with the real rules.yaml
     rules, advanced by the reading's sample time (never the wall clock). In a multi-device zone the alert also
     carries the router's sensor check text (`detail`, `alert_detail`), as Core's feed sends it.

Pair check (docs/design/slow-drift-pair-check.md, Design 2): in a multi-device zone where two or more devices carry a pair
field (air temperature, humidity, soil/substrate moisture; `PAIR_FIELDS`), each device's reading is also judged against
the zone's other devices. A per-zone `PairBuffer` keeps the judged rows (with what the pipeline vetoed) within the
baseline window, and per device and field the series `pair_reference` reads; for each paired field the engine hands the
device's own series and its partners' series to `pair_reference` (trusted_baseline.py, the function Core's outcome feed
calls with rows; the two give the same result) and puts the result as `pair` into a copy
of the field's `stream_baseline` entry, so the router's pair check sees what it sees on Core. A single-device zone (the
whole game) runs none of this; `pair_check=False` switches it off. The buffer starts when the zone becomes paired (see
`PairBuffer`), so the first device's earlier readings are not in it.

`observe(capture=...)` hands the exact pipeline input of a reading to a callback and `evaluate_input` runs such an input
again at another clock without touching the engine (the abstention eval's stale cases).

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
import math
import re
import sys
import threading
from bisect import bisect_left, bisect_right
from datetime import datetime, timedelta, timezone
from itertools import chain
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[2]
ROUTER_DIR = ROOT / "services" / "model-router"
CORE_APP = ROOT / "services" / "core" / "app"
AUTOMATION_APP = ROOT / "services" / "automation-engine" / "app"

SENSOR_ACTION = "check_sensor"  # every rule with this action is a sensor card (sensor_check, sensor_flatline), not advice
# Core's SensorEvent reading fields (services/core/app/schemas.py READING_FIELDS): a packet needs at least one that
# is a number, else Core refuses it (422). A probe that did not report is absent or null.
READING_FIELDS = ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph", "soil_moisture_pct",
                  "substrate_temperature_c", "substrate_moisture_pct")
# Core's SensorEvent optional fields: Core's stored packet has them as null when absent (every reading field too).
CORE_OPTIONAL = (*READING_FIELDS, "weather", "zone_area_m2", "crop_kc", "npk_target")
# Core's default `min_sample_time` (services/core/app/config.py): earlier sample times are a dead clock.
# Core's `max_future_sample_s` (a sample time ahead of Core's wall clock) is not mirrored: a replay runs on virtual
# sample time, with no wall clock to be ahead of.
MIN_SAMPLE_TIME = datetime(2020, 1, 1, tzinfo=timezone.utc)
HISTORY_PACKETS = 11  # the model-router's temporal checks see this many earlier packets per stream (farm, zone, device)
# Core's `retention_days` (services/core/app/config.py): the window for the multi-device test and a device's expected
# fields (docs/design/multi-device-zones.md 1.1, 1.3). The engine's clock for it is the reading's sample time.
RETENTION = timedelta(days=7)
PACKET_FIELD = "__packet__"  # the pseudo-field that records a device's live packets, as in Core's device_fields table

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


DETAIL_MAX_CHARS = 500  # the automation engine cuts to the same length
ROUTINE_CHECK = "continue routine monitoring"


def alert_detail(result: Dict[str, Any]) -> Optional[str]:
    """Same as services/core/app/outcome_feed.py (copied: that package cannot be imported next to this one; the pin
    test is services/core/tests/test_alert_detail_pin.py). The router's own sensor check text for one reading: its
    safe next checks without "continue routine monitoring", joined with "; ", cut to 500 characters ending in "…".
    None when there is nothing to say."""
    checks = [c for c in (result.get("sensor_quality") or {}).get("safe_next_checks") or []
              if isinstance(c, str) and c and c != ROUTINE_CHECK]
    text = "; ".join(checks)
    if len(text) > DETAIL_MAX_CHARS:
        text = text[:DETAIL_MAX_CHARS - 1] + "…"
    return text or None


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


# --- The pair buffer ------------------------------------------------------------------------

PAIR_BUFFER_MAX_ROWS = 4000  # judged rows kept per zone, all devices together (the oldest go first)


class PairBuffer:
    """The judged readings of multi-device zones, for the pair check: per (farm, zone), per device, oldest first.

    A row is `{device_id, timestamp (aware datetime), <the pair fields the reading carried>, vetoed_fields}`, the shape
    `trusted_baseline.pair_reference` takes (Core's `stream_history` rows). Rows older than the zone's newest sample
    time minus `keep_s` are dropped (the engine passes the baseline window plus the longest partner age, which is
    what Core reads back too), and so are the oldest rows beyond `PAIR_BUFFER_MAX_ROWS` in a zone. Standard library
    only. Rows are expected in sample-time order (an engine is fed that way); a late one is inserted in its place.

    Start-up: the engine gives a zone a buffer when it first becomes paired, so a device's readings judged before that
    are not in it, while Core still has them (see `InProcessPomona.observe`).

    Series (speed): with `fields` and `entry` (`pair_row_entry`) given, the buffer also keeps, per device and field, the
    series `pair_reference` takes (`own_series` / `partner_series`; four parallel lists, one entry per sample time),
    updated as rows come and go, so a judgement does not read every buffered row again. They always equal what
    `pair_reference` would build from the rows.
    """

    def __init__(self, keep_s: float, max_rows: int = PAIR_BUFFER_MAX_ROWS, fields: Tuple[str, ...] = (),
                 entry: Optional[Callable[[Dict[str, Any], str], Optional[tuple]]] = None) -> None:
        self.keep_s, self.max_rows = keep_s, max_rows
        self.fields, self._entry = (fields, entry) if entry is not None else ((), None)
        self._zones: Dict[Tuple[str, str], Dict[str, List[Dict[str, Any]]]] = {}  # zone -> device -> rows
        self._series: Dict[Tuple[str, str], Dict[str, Dict[str, tuple]]] = {}  # zone -> device -> field -> series
        self._newest: Dict[Tuple[str, str], datetime] = {}

    def rows(self, zone: Tuple[str, str], device_id: str) -> List[Dict[str, Any]]:
        """The device's own buffered rows, oldest first (the live list: do not change it)."""
        return self._zones.get(zone, {}).get(device_id, [])

    def partner_rows(self, zone: Tuple[str, str], device_id: str):
        """An iterator over every other device's buffered rows (each device oldest first)."""
        return chain.from_iterable(rows for device, rows in self._zones.get(zone, {}).items() if device != device_id)

    def series(self, zone: Tuple[str, str], device_id: str, field: str) -> tuple:
        """The device's series of the field (the live lists: do not change them); empty lists if it has none."""
        return self._series.get(zone, {}).get(device_id, {}).get(field) or ([], [], [], [])

    def partner_series(self, zone: Tuple[str, str], device_id: str, field: str) -> Dict[str, tuple]:
        """Every other device's series of the field, for the devices that have one (device id -> series)."""
        return {device: found[field] for device, found in self._series.get(zone, {}).items()
                if device != device_id and field in found}

    def _rebuild(self, zone: Tuple[str, str], device_id: str) -> None:
        """The device's series again from its rows (after a row was inserted late or dropped by the row cap)."""
        found: Dict[str, tuple] = {}
        for field in self.fields:
            latest: Dict[datetime, tuple] = {}  # one entry per sample time, the last row wins
            for row in self._zones[zone][device_id]:
                entry = self._entry(row, field)
                if entry is not None:
                    latest[row["timestamp"]] = entry
            if latest:
                ordered = sorted(latest.items())
                found[field] = ([t for t, _ in ordered], [t.timestamp() for t, _ in ordered],
                                [e[0] for _, e in ordered], [e[1] for _, e in ordered])
        self._series.setdefault(zone, {})[device_id] = found

    def _append(self, zone: Tuple[str, str], row: Dict[str, Any]) -> None:
        """The row, which is not older than the device's newest, joins its series."""
        found = self._series.setdefault(zone, {}).setdefault(row["device_id"], {})
        stamp = row["timestamp"]
        for field in self.fields:
            entry = self._entry(row, field)
            if entry is None:
                continue
            stamps, times, values, vetoed = found.setdefault(field, ([], [], [], []))
            if stamps and stamps[-1] == stamp:  # the same sample time again: the last row wins
                values[-1], vetoed[-1] = entry
            else:
                stamps.append(stamp)
                times.append(stamp.timestamp())
                values.append(entry[0])
                vetoed.append(entry[1])

    def add(self, zone: Tuple[str, str], row: Dict[str, Any]) -> None:
        devices = self._zones.setdefault(zone, {})
        rows = devices.setdefault(row["device_id"], [])
        stamp = row["timestamp"]
        late = bool(rows) and stamp < rows[-1]["timestamp"]
        if late:
            rows.insert(bisect_right([r["timestamp"] for r in rows], stamp), row)
        else:
            rows.append(row)
        if self._entry is not None:
            if late:
                self._rebuild(zone, row["device_id"])
            else:
                self._append(zone, row)
        newest = max(self._newest.get(zone, stamp), stamp)
        self._newest[zone] = newest
        floor = newest - timedelta(seconds=self.keep_s)
        total = 0
        for device, items in devices.items():
            cut = 0
            while cut < len(items) and items[cut]["timestamp"] < floor:
                cut += 1
            if cut:
                del items[:cut]
                for lists in self._series.get(zone, {}).get(device, {}).values():  # the same cut, by sample time
                    drop = bisect_left(lists[0], floor)
                    if drop:
                        for part in lists:
                            del part[:drop]
            total += len(items)
        while total > self.max_rows:  # the oldest row of the zone goes
            device = min((d for d, items in devices.items() if items), key=lambda d: devices[d][0]["timestamp"])
            del devices[device][0]
            total -= 1
            if self._entry is not None:
                self._rebuild(zone, device)


# --- The engine ---------------------------------------------------------------------------

class InProcessPomona:
    """Feed readings in sample-time order with `observe`; record calibrations with `calibrate`.

    `rules` are the parsed rules.yaml rules (`load_rules()`), `defaults` the monitor's (raise, clear)
    seconds (`alert_defaults()`). The engine keeps, per stream (farm, zone, device), the last 11 packets, the
    readings the trusted baseline is built from, the calibrations and the fields the device has sent; and one
    AlertMonitor. Not thread-safe by itself per engine: serialise calls on one engine; different engines
    may run in different threads (pipeline calls share PIPELINE_LOCK). `loop` (optional) is an event loop
    shared with other engines; the engine then leaves it open on close.
    """

    def __init__(self, rules: Optional[List[Dict[str, Any]]] = None, defaults: Optional[Tuple[int, int]] = None, *,
                 router_dir: Path = ROUTER_DIR, core_app: Path = CORE_APP, automation_app: Path = AUTOMATION_APP,
                 min_sample_time: datetime = MIN_SAMPLE_TIME, max_events: int = 1_000_000,
                 loop: Optional[asyncio.AbstractEventLoop] = None, pair_check: bool = True) -> None:
        self.pair_check = pair_check
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
        self._history: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}  # per stream, the last 11 packets
        # per stream, field (or PACKET_FIELD) -> [first_seen, last_seen] sample times (Core's device_fields table)
        self._device_fields: Dict[Tuple[str, str, str], Dict[str, List[datetime]]] = {}
        self._streams: Dict[Tuple[str, str, str], Any] = {}  # per stream, its StreamBaseline (Core's trusted reference)
        # (farm_id or None, zone_id, device_id or None, measurement, performed_at); None matches any
        self._calibrations: List[Tuple[Optional[str], str, Optional[str], str, str]] = []
        # the judged rows of zones with two or more devices carrying a pair field (the pair check); none otherwise
        self._pairs = PairBuffer(self._baseline.DEFAULT_WINDOW_S + self._baseline.PAIR_MAX_AGE_MAX_S,
                                 fields=self._baseline.PAIR_FIELDS, entry=self._baseline.pair_row_entry)

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

    def _zone_calibrations(self, farm: str, zone: str) -> List[Dict[str, Any]]:
        """Every calibration recorded for the zone on any device (the pair starts at the newest one)."""
        return [{"measurement": field, "performed_at": at} for f, z, d, field, at in self._calibrations
                if z == zone and f in (None, farm)]

    def _paired_devices(self, stream: Tuple[str, str, str], sample: datetime) -> int:
        """How many devices of the stream's farm and zone carry a pair field now (Core's `device_fields` counting rule)."""
        found = 0
        for other, rows in self._device_fields.items():
            if other[:2] != stream[:2]:
                continue
            if any(name in rows and rows[name][0] <= sample and rows[name][1] >= sample - RETENTION
                   for name in self._baseline.PAIR_FIELDS):
                found += 1
        return found

    # Multi-device zones: the same bookkeeping as Core's device_fields table (store.py), on sample time.

    def _record_and_device_fields(self, stream: Tuple[str, str, str], sensor: Dict[str, Any],
                                  sample: datetime) -> Optional[List[str]]:
        """Remember the fields this packet carries; return the device's fields if the zone is multi-device now, else None.

        Multi-device: another device of the same farm and zone has a packet row with first_seen <= sample and
        last_seen >= sample - 7 days. The device's fields are the finite-number READING_FIELDS whose rows count the same way.
        """
        carried = [name for name in READING_FIELDS
                   if isinstance(sensor[name], (int, float)) and not isinstance(sensor[name], bool)
                   and math.isfinite(sensor[name])]
        rows = self._device_fields.setdefault(stream, {})
        for name in [*carried, PACKET_FIELD]:
            seen = rows.setdefault(name, [sample, sample])
            seen[0], seen[1] = min(seen[0], sample), max(seen[1], sample)

        def counts(seen: List[datetime]) -> bool:
            return seen[0] <= sample and seen[1] >= sample - RETENTION

        multi = any(other != stream and other[:2] == stream[:2] and PACKET_FIELD in other_rows
                    and counts(other_rows[PACKET_FIELD]) for other, other_rows in self._device_fields.items())
        if not multi:
            return None
        return sorted(name for name, seen in rows.items() if name != PACKET_FIELD and counts(seen))

    # One reading

    def observe(self, event: Dict[str, Any], *, include_result: bool = False,
                capture: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """Run one reading through Core's checks, the pipeline and the alert monitor.

        `event` is the sensor packet the device sent (farm_id, zone_id, device_id, timestamp, readings...).
        Returns `accepted` / `rejection` (Core's verdict: a dead-clock or unreadable timestamp, or a packet with no
        reading, is rejected and leaves no trace), then for an accepted reading: `labels` (risk labels), `trust` (verdict),
        `vetoed_fields`, `card_labels` (labels some advice card matches), `sensor_check_labels`,
        `alert_events` (raised / recovered, with sample times) and `ignored` (the monitor already saw a
        later sample of the stream). `include_result` adds the full pipeline result as `pipeline`.

        `capture` (optional) is called with the exact pipeline input, just before the pipeline runs (nothing else is
        changed by it): a dict with `farm_context`, `sensor`, `expected_fields` (`[]`), `history`, `stream_baseline`,
        `device_fields` (the key is absent in a single-device zone) and `now` (a datetime: sample time + 1 s). The
        objects are the engine's own; copy what you keep. `evaluate_input` runs such an input again.
        """
        try:
            sample = parse_ts(str(event["timestamp"]))
        except (KeyError, ValueError):
            return {"accepted": False, "rejection": "invalid_timestamp"}
        if sample < self.min_sample_time:
            return {"accepted": False, "rejection": "dead_clock", "sample_time": sample}
        sensor = core_packet(event)
        if all(not isinstance(sensor[name], (int, float)) or isinstance(sensor[name], bool) for name in READING_FIELDS):
            return {"accepted": False, "rejection": "no_reading", "sample_time": sample}
        sensor.update(received_at=iso_z(sample + timedelta(seconds=1)), mqtt_retained=False)
        farm_id, zone_id, device_id = event["farm_id"], event["zone_id"], event["device_id"]
        stream = (farm_id, zone_id, device_id)
        prior = [{k: v for k, v in p.items() if k not in ("received_at", "mqtt_retained")}
                 for p in self._history.get(stream, [])[-HISTORY_PACKETS:]]
        farm = {"crop": sensor["crop"], "system_type": sensor["system_type"], "zone_id": sensor["zone_id"],
                "weather": sensor.get("weather"), "zone_area_m2": sensor.get("zone_area_m2"),
                "crop_kc": sensor.get("crop_kc"), "npk_target": sensor.get("npk_target")}
        device_fields = self._record_and_device_fields(stream, sensor, sample)
        baseline = self._baseline
        tracked = self._streams.get(stream)
        if tracked is None:
            tracked = self._streams[stream] = baseline.StreamBaseline(
                baseline.DEFAULT_WINDOW_S, baseline.DEFAULT_MIN_N, baseline.DEFAULT_MAX_AGE_S or None,
                baseline.DEFAULT_SCAN_LIMIT)
        reference = tracked.baseline(self._stream_calibrations(stream), sample)
        zone = (farm_id, zone_id)
        paired = self.pair_check and device_fields is not None and self._paired_devices(stream, sample) >= 2
        if paired and reference:
            # Pair check (a copy of each paired field's entry: the StreamBaseline's own state is not touched). The buffer
            # of a zone starts at the first reading judged while the zone is paired. Core also has the readings judged
            # before that, so the two can differ in the first baseline window (2 h) after a zone becomes paired:
            # - the joining device's first offsets: the partner reading of its first one or two readings is from before the
            #   buffer, so Core has up to two more offsets (`n` up to 2 higher, the first entry up to 2 readings earlier,
            #   and a median that can differ by a few percent of the limit while `n` is small) until they leave the window;
            # - the first device's own rows from before the buffer count in Core's cadence (partner age) and flat
            #   tests: only an irregular early cadence, or a stream that went flat within the first window, changes
            #   an entry; both are outside the readings the engine is fed (regular 30 s ticks).
            # After one window the two are equal (tests: scripts/tests/test_inprocess_pair.py,
            # services/core/tests/test_pair_inprocess_equality.py).
            current = {"device_id": device_id, "timestamp": sample, **{name: sensor.get(name) for name in baseline.PAIR_FIELDS}}
            calibrations = None
            reference = dict(reference)
            for name in baseline.PAIR_FIELDS:
                if name in reference:
                    # Pre-built series (the buffer keeps them): no partner series of the field means no pair entry, so
                    # that case (e.g. two devices that carry different pair fields) costs nothing.
                    partners = self._pairs.partner_series(zone, device_id, name)
                    if not partners:
                        continue
                    if calibrations is None:
                        calibrations = self._zone_calibrations(farm_id, zone_id)
                    entry = baseline.pair_reference(
                        (), (), name, baseline.pair_start_time(calibrations, name, sample), current,
                        baseline.DEFAULT_WINDOW_S, baseline.DEFAULT_MAX_AGE_S or None,
                        own_series=self._pairs.series(zone, device_id, name), partner_series=partners)
                    if entry is not None:
                        reference[name] = {**reference[name], "pair": entry}
        pipeline_input = {"farm_context": farm, "sensor": sensor, "expected_fields": [], "history": prior,
                          "stream_baseline": reference or None, "now": sample + timedelta(seconds=1)}
        if device_fields is not None:  # absent in a single-device zone
            pipeline_input["device_fields"] = device_fields
        if capture is not None:
            capture(pipeline_input)
        result = self._evaluate(pipeline_input, pipeline_input["now"])
        history = self._history.setdefault(stream, [])
        history.append(sensor)
        del history[:-HISTORY_PACKETS]
        tracked.add({**sensor, "timestamp": sample, "vetoed_fields": result["trust_gate"]["vetoed_fields"]})
        if paired:  # the judged row joins the zone's buffer (from here on the zone has one)
            values = {name: sensor[name] for name in baseline.PAIR_FIELDS if sensor.get(name) is not None}
            if values:
                self._pairs.add(zone, {"device_id": device_id, "timestamp": sample, **values,
                                       "vetoed_fields": list(result["trust_gate"]["vetoed_fields"])})
        labels = pipeline_risk_labels(result)
        if device_fields is None:  # a single-device zone: the monitor call is exactly as it always was
            verdict = self.monitor.observe(farm_id, zone_id, device_id, sample, labels)
        else:  # a multi-device zone: the check text and the data-quality labels, as Core's feed sends them
            detail = alert_detail(result)
            verdict = self.monitor.observe(
                farm_id, zone_id, device_id, sample, labels, **({"detail": detail} if detail else {}),
                data_quality_labels=(result.get("sensor_quality") or {}).get("data_quality_labels", []))
        out = {"accepted": True, "rejection": None, "farm_id": farm_id, "zone_id": zone_id, "device_id": device_id,
               "sample_time": sample, "labels": labels, "trust": result["trust_gate"]["trust_verdict"],
               "vetoed_fields": result["trust_gate"]["vetoed_fields"],
               "card_labels": sorted(set(labels) & self.card_labels),
               "sensor_check_labels": sorted(set(labels) & self.check_labels),
               "alert_events": verdict["events"], "ignored": bool(verdict.get("ignored"))}
        if include_result:
            out["pipeline"] = result
        return out

    def _evaluate(self, pipeline_input: Dict[str, Any], now: datetime) -> Dict[str, Any]:
        """The pipeline on one input with its clock set to `now` (set `_now`, evaluate, restore, under PIPELINE_LOCK)."""
        pipeline = self._pipeline
        with PIPELINE_LOCK:
            original_now = pipeline._now
            pipeline._now = lambda now=now: now
            try:
                extra = ({"device_fields": pipeline_input["device_fields"]}
                         if "device_fields" in pipeline_input else {})  # absent in a single-device zone
                return self._loop.run_until_complete(pipeline.evaluate_pipeline(
                    pipeline_input["farm_context"], pipeline_input["sensor"], pipeline_input["expected_fields"],
                    {"action_type": "continue_monitoring"}, "core_feed", "rules_only", "core_feed",
                    history=pipeline_input["history"], stream_baseline=pipeline_input["stream_baseline"], **extra))
            finally:
                pipeline._now = original_now

    def evaluate_input(self, pipeline_input: Dict[str, Any], now: Any = None) -> Dict[str, Any]:
        """Run the pipeline again on a recorded input (the dict `observe(capture=...)` gave), with the clock at `now`.

        `now` is a datetime or ISO text; left out, the input's own `now`. Nothing of the engine changes: no history,
        no trusted reference, no alert monitor, no device bookkeeping. Returns the pipeline result, as
        `observe(include_result=True)` puts it under `pipeline`. Used to judge the same packet again at a later clock.
        """
        stamp = pipeline_input["now"] if now is None else now
        return self._evaluate(pipeline_input, parse_ts(stamp) if isinstance(stamp, str) else stamp)

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
