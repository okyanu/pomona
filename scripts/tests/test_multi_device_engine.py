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


# --- Slice 3 (docs/design/multi-device-zones-slice3.md 3.4): the alert `detail` in a multi-device zone -------------

def faulty(readings, ph_from=150, hot_from=100):
    """Zone A with a pH probe jumping out of range from `ph_from` and the air probe stuck at 36 C from `hot_from`:
    a sensor card on each probe and a heat condition card."""
    return [{**e, **({"ph": 15.0} if tick >= ph_from else {}), **({"air_temperature_c": 36.0} if tick >= hot_from else {})}
            for tick, e in enumerate(readings)]


def watch_monitor(pomona, monkeypatch):
    """Record every call to the alert monitor (positional args, keyword args); the call itself goes through."""
    calls = []
    real = pomona.monitor.observe

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(pomona.monitor, "observe", spy)
    return calls


def test_a_sensor_alert_in_a_two_device_zone_carries_the_check_text(pomona, readings):
    got = run(pomona, [p for event in faulty(readings) for p in split(event)])
    events = [e for g in got for e in g["alert_events"]]
    raised = {(e["rule_id"], e["device_id"]): e for e in events if e["event"] == "raised"}
    # each probe's sensor card carries the router's own check text for that probe
    assert "pH probe calibration" in raised[("sensor_check", "substrate-1")]["detail"]
    assert "air_temperature_c" in raised[("sensor_check", "climate-1")]["detail"]
    # the heat condition card does not: its label is not a data-quality label
    assert ("heat_stress_check", "climate-1") in raised and "detail" not in raised[("heat_stress_check", "climate-1")]
    states = {(s["rule_id"], s["device_id"]): s for s in pomona.states()}
    assert all(s.get("detail") for (rule, _), s in states.items() if rule == "sensor_check")
    assert not [s for (rule, _), s in states.items() if rule != "sensor_check" and "detail" in s]
    # whatever carries a detail is a sensor rule, and the text is never the routine line alone
    assert {e["rule_id"] for e in events if e.get("detail")} <= {"sensor_check", "sensor_flatline"}
    assert not [e for e in events if e.get("detail") and "routine monitoring" in e["detail"]]


def test_the_monitor_gets_the_detail_only_when_there_is_one_and_the_labels_in_a_multi_device_zone(pomona, readings, monkeypatch):
    calls = watch_monitor(pomona, monkeypatch)
    got = run(pomona, [p for event in faulty(readings) for p in split(event)])
    assert len(calls) == len(got)
    assert calls[0][1] == {}  # the zone's very first packet is judged before the zone has a second device: today's call
    assert all(len(args) == 5 for args, _ in calls)
    kwargs = [kw for _, kw in calls[1:]]
    assert all("data_quality_labels" in kw for kw in kwargs)  # every reading from the second packet on
    for args, kw in calls[1:]:  # the data-quality labels are a part of the reading's labels
        assert set(kw["data_quality_labels"]) <= set(args[4])
    assert any(kw["data_quality_labels"] for _, kw in calls[1:])
    with_text = [kw for kw in kwargs if "detail" in kw]
    assert with_text and len(with_text) < len(kwargs)  # absent when the router has nothing to say
    assert all(kw["detail"] for kw in with_text)


def test_a_single_device_zone_calls_the_monitor_as_before_and_its_events_have_no_detail(pomona, readings, monkeypatch):
    calls = watch_monitor(pomona, monkeypatch)
    got = run(pomona, faulty(readings))  # the same faults, one device (the simulator's own) in the zone
    assert all(kw == {} and len(args) == 5 for args, kw in calls) and len(calls) == len(got)
    events = [e for g in got for e in g["alert_events"]]
    assert {e["rule_id"] for e in events} >= {"sensor_check", "heat_stress_check"}
    assert not [e for e in events if "detail" in e]
    assert not [s for s in pomona.states() if "detail" in s]

