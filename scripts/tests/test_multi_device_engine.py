"""Multi-device zones, slice 1, in the in-process engine (docs/design/multi-device-zones.md 1.2, 1.3, 1.11).

Run with the model-router venv. The Core side of the same scenarios is services/core/tests/test_multi_device_feed.py.
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "examples" / "simulators"))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import fake_greenhouse as fg
import inprocess_pomona as engine
import score_fake_greenhouse as score

BASE = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
TICKS = 240  # 2 hours at 30 s
SEED = 2  # a normal run of this seed raises nothing in zone A over the first 2 hours


def zone_a_readings(ticks=TICKS, seed=SEED):
    """The fake greenhouse's substrate zone, normal operation: one full packet per tick."""
    state = {"n": 0}

    def clock():
        value = BASE + timedelta(seconds=30 * state["n"])
        state["n"] += 1
        return value

    sim = fg.Simulation(seed=seed, clock=clock)
    return [r.event for _ in range(ticks) for r in sim.step() if r.truth["zone_id"] == "greenhouse-a" and r.event]


def split(event, offset=None, drop=()):
    """The packet as two devices send it: climate-1 (air, humidity), substrate-1 (pH, EC, moisture).
    `offset`: substrate-1 also carries air temperature, that much above climate-1's. `drop`: fields substrate-1 lacks."""
    common = {k: event[k] for k in ("farm_id", "zone_id", "crop", "growth_stage", "system_type", "timestamp", "schema_version")}
    climate = {**common, "device_id": "climate-1", "air_temperature_c": event["air_temperature_c"],
               "humidity_pct": event["humidity_pct"]}
    substrate = {**common, "device_id": "substrate-1", "ph": event["ph"], "ec_ms_cm": event["ec_ms_cm"],
                 "soil_moisture_pct": event["soil_moisture_pct"], "substrate_moisture_pct": event["substrate_moisture_pct"]}
    if offset is not None:
        substrate["air_temperature_c"] = round(event["air_temperature_c"] + offset, 2)
    for name in drop:
        substrate.pop(name, None)
    return [climate, substrate]


@pytest.fixture(scope="module")
def readings():
    return zone_a_readings()


@pytest.fixture
def pomona():
    with engine.InProcessPomona(score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()),
                                score.alert_defaults()) as value:
        yield value


def run(pomona, packets):
    """Observe every packet; returns the per-packet results. The zone's very first packet is judged alone."""
    return [pomona.observe(packet) for packet in packets]


def test_two_devices_give_no_missing_labels_alerts_or_flags(pomona, readings):
    got = run(pomona, [p for event in readings for p in split(event)])
    assert len(got) == 2 * TICKS and all(g["accepted"] for g in got)
    judged = got[1:]  # the very first packet is judged before the zone has a second device
    assert [g["labels"] for g in judged if g["labels"]] == []
    assert all(g["trust"] == "trusted" and not g["vetoed_fields"] for g in judged)
    assert pomona.states() == []
    assert not [e for g in got for e in g["alert_events"]]


def test_the_same_with_a_constant_offset_between_two_air_probes(pomona, readings):
    got = run(pomona, [p for event in readings for p in split(event, offset=1.5)])
    judged = got[1:]
    assert [g["labels"] for g in judged if g["labels"]] == []  # no noise flag: each device has its own history
    assert pomona.states() == []


def test_a_zone_wide_history_would_have_flagged_the_offset(readings):
    """The check above has teeth: with both devices' packets in one history the offset reads as noise."""

    class ZoneWide(dict):  # the old key: (farm, zone)
        def setdefault(self, key, default):
            return super().setdefault(key[:2], default)

        def get(self, key, default=None):
            return super().get(key[:2], default)

    with engine.InProcessPomona(score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()),
                                score.alert_defaults()) as zone_wide:
        zone_wide._history = ZoneWide()
        got = [zone_wide.observe(p) for event in readings for p in split(event, offset=1.5)]
    assert any("noisy_signal_possible" in g["labels"] for g in got[1:])


def test_ec_disappearing_from_the_substrate_device_alerts_that_device_only(pomona, readings):
    packets = []
    for tick, event in enumerate(readings):
        packets += split(event, drop=("ec_ms_cm",) if tick >= 180 else ())
    got = run(pomona, packets)
    assert [g["labels"] for g in got[1:2 * 180] if g["labels"]] == []
    after = [g for g in got[2 * 180:] if g["device_id"] == "substrate-1"]
    assert all("missing_ec" in g["labels"] and g["vetoed_fields"] == ["ec_ms_cm"] for g in after)
    assert not [g for g in got[2 * 180:] if g["device_id"] == "climate-1" and g["labels"]]
    raised = [e for g in got for e in g["alert_events"] if e["event"] == "raised"]
    assert [(e["rule_id"], e["device_id"]) for e in raised] == [("sensor_check", "substrate-1")]
    assert {(s["rule_id"], s["device_id"]) for s in pomona.states()} == {("sensor_check", "substrate-1")}


def test_device_fields_are_passed_only_in_a_multi_device_zone(pomona, readings, monkeypatch):
    asked = []
    pipeline = pomona._pipeline
    real = pipeline.evaluate_pipeline

    async def spy(*args, **kwargs):
        asked.append(kwargs.get("device_fields", "absent"))
        return await real(*args, **kwargs)

    monkeypatch.setattr(pipeline, "evaluate_pipeline", spy)
    run(pomona, readings[:5])  # one device (the simulator's own) in the zone
    assert asked == ["absent"] * 5
    run(pomona, split(readings[5]))  # two more devices: the zone is multi-device from then on
    assert asked[5:] == [["air_temperature_c", "humidity_pct"], ["ec_ms_cm", "ph", "soil_moisture_pct", "substrate_moisture_pct"]]


def test_history_is_per_device(pomona, readings):
    run(pomona, [p for event in readings[:15] for p in split(event)])
    assert {key: len(value) for key, value in pomona._history.items()} == {
        ("demo-farm", "greenhouse-a", "climate-1"): 11, ("demo-farm", "greenhouse-a", "substrate-1"): 11}
    assert {p["device_id"] for value in pomona._history.values() for p in value} == {"climate-1", "substrate-1"}


def test_the_partner_window_is_seven_days_on_sample_time(pomona, readings):
    first, second = split(readings[0])
    pomona.observe(second)
    later = lambda days: {**first, "timestamp": (BASE + timedelta(days=days)).isoformat().replace("+00:00", "Z")}  # noqa: E731
    assert pomona._record_and_device_fields(("demo-farm", "greenhouse-a", "climate-1"), engine.core_packet(later(6)),
                                            BASE + timedelta(days=6)) == ["air_temperature_c", "humidity_pct"]
    pomona._device_fields.pop(("demo-farm", "greenhouse-a", "climate-1"))
    assert pomona._record_and_device_fields(("demo-farm", "greenhouse-a", "climate-1"), engine.core_packet(later(8)),
                                            BASE + timedelta(days=8)) is None
