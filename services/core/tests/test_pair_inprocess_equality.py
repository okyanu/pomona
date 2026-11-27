"""The pair entry from Core's store path equals the in-process engine's, for the same readings judged in order
(docs/design/slow-drift-pair-check.md, Design 2 "Equality with the in-process engine").

Core side: each reading is stored, built into a request body by `OutcomeFeed._process` (router call mocked, vetoes
chosen by a deterministic rule) and its trust row written. In-process side: the same reading through `PairBuffer` and
`pair_reference` exactly as `InProcessPomona.observe` does it. `examples/simulators/inprocess_pomona.py` is loaded by
path; only its standard-library `PairBuffer` is used, no pipeline. Readings are integer arithmetic.
"""
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
ROOT = SERVICE_DIR.parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import app.outcome_feed as feed_module
import app.store as store_module
import app.trusted_baseline as tb
from app.config import settings
from app.outcome_feed import OutcomeFeed
from app.schemas import CalibrationEvent, SensorEvent
from app.store import SensorEventStore, event_store

_spec = importlib.util.spec_from_file_location("inprocess_pomona_by_path", ROOT / "examples" / "simulators" / "inprocess_pomona.py")
inprocess = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(inprocess)

AIR, HUMIDITY, SOIL, SUBSTRATE = "air_temperature_c", "humidity_pct", "soil_moisture_pct", "substrate_moisture_pct"
T0 = datetime.now(timezone.utc).replace(microsecond=0) - 20 * timedelta(days=1)
WINDOW = settings.trust_baseline_window_s
ZONE = ("farm", "a")


def stamp(i):
    return T0 + timedelta(seconds=30 * i)


def noise(i, k, span):
    """A deterministic wobble of +-span/2 that differs per device k (integer arithmetic, one division)."""
    return ((i * 7919 + k * 104729) % 41 - 20) * span / 40


def wave(i, amplitude):
    """A shared slow triangle of +-amplitude over 120 readings."""
    phase = i % 120
    return amplitude * ((phase if phase <= 60 else 120 - phase) - 30) / 30


def vetoed(device, i):
    """The router's (mock) veto: about one reading in 37 per device, on air or the moisture field."""
    return (i * 13 + device * 7) % 37 == 0


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    value = Clock()
    monkeypatch.setattr(store_module, "utc_now", value)
    return value


@pytest.fixture(autouse=True)
def fresh_store(tmp_path, monkeypatch):
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "equality.db")
    SensorEventStore(db_path=event_store._db_path)


class Layout(SimpleNamespace):
    """devices: [(id, field names, constant offsets)], ticks, quiet: {device index: ticks it sends nothing},
    calibrate: (tick, device, measurement), join: {device index: first tick it sends}."""


def readings_of(layout, device, i):
    """The reading device `device` (an index) sends at tick `i`: shared variation + constant offset + own noise."""
    _, fields, offsets = layout.devices[device]
    out = {}
    for name in fields:
        if name == AIR:
            out[name] = 20 + wave(i, 0.5) + offsets[name] + noise(i, device, 0.4)
        elif name == HUMIDITY:
            out[name] = 60 + wave(i, 3) + offsets[name] + noise(i, device, 2.0)
        else:
            out[name] = 40 + wave(i, 2) + offsets[name] + noise(i, device, 1.0)
    return out


def run(clock, monkeypatch, layout, like_the_engine=False):
    """Both paths for every reading, in order. Returns one (tick, device, field, in-process entry, Core entry) per
    reading and paired field. The in-process buffer holds every judged reading, or with `like_the_engine` only those
    judged once two devices had sent (the engine gives a zone a buffer when it becomes paired)."""
    monkeypatch.setattr(settings, "model_router_url", "http://router.test")
    monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
    bodies = []

    def veto_of(sensor):
        index = round((SensorEvent.model_validate(sensor).timestamp - T0).total_seconds() / 30)
        device = [d[0] for d in layout.devices].index(sensor["device_id"])
        return [name for name in (AIR, SOIL, SUBSTRATE) if sensor.get(name) is not None] if vetoed(device, index) else []

    def post(base_url, path, body):
        if path != "/v1/pipeline/evaluate":
            return {}
        bodies.append(body)
        return {"trust_gate": {"trust_verdict": "trusted", "vetoed_fields": veto_of(body["sensor"])}}

    monkeypatch.setattr(feed_module, "_post", post)
    feed = OutcomeFeed(event_store, queue_size=5)
    buffer = inprocess.PairBuffer(tb.DEFAULT_WINDOW_S + tb.PAIR_MAX_AGE_MAX_S)
    calibrations = []
    records, senders = [], set()
    for i in range(layout.ticks):
        if layout.calibrate and layout.calibrate[0] == i:
            _, device, measurement = layout.calibrate
            performed = stamp(i) - timedelta(seconds=15)
            clock.now = max(clock.now, performed)
            event_store.add_calibration(CalibrationEvent.model_validate({
                "device_id": layout.devices[device][0], "farm_id": "farm", "zone_id": "a", "sensor_id": "s",
                "measurement": measurement, "method": "reference_meter", "points": [{"reference": 20.0, "raw": 20.5}],
                "performed_at": performed.isoformat()}))
            calibrations.append({"measurement": measurement, "performed_at": performed})
        for device, (name, fields, _) in enumerate(layout.devices):
            if i in layout.quiet.get(device, ()) or i < layout.join.get(device, 0):
                continue
            senders.add(name)
            values = readings_of(layout, device, i)
            clock.now = stamp(i)
            event = SensorEvent.model_validate({"device_id": name, "farm_id": "farm", "zone_id": "a",
                                                "timestamp": stamp(i).isoformat(), **values})
            assert event_store.add(event)
            feed._process(event)  # Core: the request body, then the trust row
            body = bodies[-1]
            # the in-process path, as observe does it
            current = {"device_id": name, "timestamp": stamp(i), **{k: values.get(k) for k in tb.PAIR_FIELDS}}
            own = buffer.rows(ZONE, name)
            entries = {}
            for field in tb.PAIR_FIELDS:
                if field in values:
                    entries[field] = tb.pair_reference(own, buffer.partner_rows(ZONE, name), field,
                                                       tb.pair_start_time(calibrations, field, stamp(i)), current,
                                                       tb.DEFAULT_WINDOW_S, tb.DEFAULT_MAX_AGE_S or None)
            if len(senders) >= 2 or not like_the_engine:
                buffer.add(ZONE, {"device_id": name, "timestamp": stamp(i),
                                  **{k: values[k] for k in tb.PAIR_FIELDS if k in values}, "vetoed_fields": veto_of(body["sensor"])})
            for field, entry in entries.items():
                records.append((i, name, field, entry, ((body.get("stream_baseline") or {}).get(field) or {}).get("pair")))
    return records


TWO = Layout(devices=[("A", [AIR, HUMIDITY], {AIR: 0.0, HUMIDITY: 0.0}), ("B", [AIR, HUMIDITY], {AIR: 0.4, HUMIDITY: -1.5})],
             ticks=330, quiet={1: range(150, 156)}, calibrate=(200, 1, AIR), join={})
THREE = Layout(devices=[("A", [AIR, SOIL], {AIR: 0.0, SOIL: 0.0}), ("B", [AIR, SUBSTRATE], {AIR: 0.4, SUBSTRATE: -2.0}),
                        ("C", [AIR, SOIL], {AIR: -0.3, SOIL: 1.0})],
               ticks=330, quiet={2: range(120, 127), 1: range(240, 244)}, calibrate=(180, 0, SOIL), join={})


@pytest.mark.parametrize("layout", [TWO, THREE], ids=["two devices, air and humidity", "three devices, air and the moisture alias"])
def test_the_pair_entry_is_the_same_through_core_and_the_in_process_buffer(clock, monkeypatch, layout):
    records = run(clock, monkeypatch, layout)
    for tick, device, field, entry, core_entry in records:
        assert entry == core_entry, f"tick {tick} {device} {field}: in-process {entry} vs Core {core_entry}"
    assert len(records) > 500 and len([r for r in records if r[3] is not None]) >= 100  # not vacuous


def test_the_start_up_difference_a_second_device_joining_a_zone_is_bounded_and_ends_with_the_window(clock, monkeypatch):
    """The engine's buffer starts when the zone becomes paired, so the first device's readings from before that are
    not in it, and Core has them. Only the joining device's entries can differ: Core has the offsets of its first one
    or two readings (their partner readings are from before the buffer), so `n` is higher by at most 2 and the first
    entry comes up to 2 readings earlier, and the median can differ a little (under a quarter of the limit here). From one window after the join on, equal."""
    join = 25
    layout = Layout(devices=[("A", [AIR, HUMIDITY], {AIR: 0.0, HUMIDITY: 0.0}), ("B", [AIR, HUMIDITY], {AIR: 0.4, HUMIDITY: -1.5})],
                    ticks=join + 270, quiet={}, calibrate=None, join={1: join})
    records = run(clock, monkeypatch, layout, like_the_engine=True)
    differing = []
    for tick, device, field, entry, core_entry in records:
        if entry == core_entry:
            continue
        differing.append((tick, device, field))
        assert device == "B" and tick < join + 242, (tick, device, field, entry, core_entry)
        if entry is None or core_entry is None:  # Core's first entries come one or two readings earlier
            assert entry is None and core_entry["n"] <= tb.PAIR_MIN_N + 1
            continue
        assert {k: v for k, v in entry.items() if k not in ("n", "offset")} == {k: v for k, v in core_entry.items() if k not in ("n", "offset")}
        # n is 2 higher in Core all window long; the median moves by up to a few readings' worth of the offsets' spread
        # (here +-0.2 C and +-1 %RH of noise per device): a quarter of the limit at the very most, and in practice less
        assert 0 <= core_entry["n"] - entry["n"] <= 2
        assert abs(core_entry["offset"] - entry["offset"]) < tb.PAIR_DRIFT_LIMITS[field] / 4
    assert differing, "the start-up difference is real: the test should see it"
    assert [r for r in records if r[0] >= join + 242 and r[3] is not None]  # and entries exist after it ended
