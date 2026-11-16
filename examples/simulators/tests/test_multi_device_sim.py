"""Tests for multi-device zones in the fake greenhouse (docs/design/multi-device-zones-slice3.md, 3.1-3.3, 3.7).

Rule 0 (no `devices` key means every byte as before) is proven by the older suites and the baseline diff; these
tests cover the new paths. Run with the Core venv.
"""

import copy
import http.client
import json
import math
import statistics
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "examples" / "simulators"
sys.path.insert(0, str(SIM_DIR))

import fake_greenhouse as fg
import sim_helpers

A, B = "greenhouse-a", "greenhouse-b"
CLIMATE = {"device_id": "climate-1", "sensors": ["air_temperature_c", "humidity_pct"]}
SUBSTRATE = {"device_id": "substrate-1", "sensors": ["ec_ms_cm", "ph", "soil_moisture_pct", "substrate_temperature_c"]}
SPLIT = {A: [CLIMATE, SUBSTRATE]}


def sim_for(devices=None, steps=None, seed=11, **kwargs):
    scenario = {"steps": steps or []}
    if devices is not None:
        scenario["devices"] = devices
    return fg.Simulation(seed=seed, clock=sim_helpers.make_clock(), scenario=scenario, **kwargs)


def run(sim, ticks):
    """Every Reading, in order."""
    return [r for _ in range(ticks) for r in sim.step()]


def rows_of(readings, zone=None, device=None):
    return [r.truth for r in readings if (zone is None or r.truth["zone_id"] == zone)
            and (device is None or r.truth["device_id"] == device)]


def pair_scenario():
    return fg.load_scenario(SIM_DIR / "scenarios" / "slow_drift.json")


# --- Layout and step validation ---------------------------------------------------------------------------------

def layout(*devices, zone=A):
    return {zone: [copy.deepcopy(d) for d in devices]}


def dev(device_id="d1", sensors=("air_temperature_c",), **extra):
    return {"device_id": device_id, "sensors": list(sensors), **extra}


ALL_A = fg.DEFAULT_ZONES[0].sensors
REST_A = [f for f in ALL_A if f not in ("air_temperature_c", "humidity_pct")]

BAD_LAYOUTS = [
    ("not an object", ["x"], "must be an object"),
    ("zone list not a list", {A: "x"}, "must be a list"),
    ("device not an object", {A: ["x"]}, "must be an object"),
    ("unknown zone", {"nope": [dev(sensors=ALL_A)]}, "unknown zone"),
    ("empty list", {A: []}, "is empty"),
    ("nine devices", {A: [dev(f"d{i}", ALL_A) for i in range(9)]}, "at most 8"),
    ("typo key", layout(dev("d1", ALL_A, offset={"ph": 1})), "unknown device keys"),
    ("missing device_id", {A: [{"sensors": list(ALL_A)}]}, "device_id"),
    ("slash in id", layout(dev("a/b", ALL_A)), "device_id"),
    ("plus in id", layout(dev("a+b", ALL_A)), "device_id"),
    ("hash in id", layout(dev("a#b", ALL_A)), "device_id"),
    ("dot id", layout(dev(".", ALL_A)), "device_id"),
    ("dotdot id", layout(dev("..", ALL_A)), "device_id"),
    ("empty id", layout(dev("", ALL_A)), "device_id"),
    ("id too long", layout(dev("x" * 65, ALL_A)), "device_id"),
    ("duplicate id", layout(dev("d1", ("air_temperature_c", "humidity_pct")), dev("d1", REST_A)), "used twice"),
    ("sensors empty", layout(dev("d1", ())), "non-empty list"),
    ("sensors not a list", {A: [{"device_id": "d1", "sensors": "ph"}]}, "non-empty list"),
    ("unknown sensor", layout(dev("d1", ("nope",))), "not a sensor of zone"),
    ("sensor the zone lacks", layout(dev("d1", ("soil_moisture_pct",)), zone=B), "not a sensor of zone"),
    ("probe twice", layout(dev("d1", ("ph", "ph"))), "listed twice"),
    ("probe twice via alias", layout(dev("d1", ("soil_moisture_pct", "substrate_moisture_pct"))), "listed twice"),
    ("zone probes uncovered", layout(dev("d1", ("air_temperature_c", "humidity_pct"))), "no device carries"),
    ("offset key is the alias", layout(dev("d1", ("air_temperature_c", "humidity_pct")),
                                       dev("d2", REST_A, offsets={"substrate_moisture_pct": 1})), "canonical"),
    ("offset on a probe it lacks", layout(dev("d1", ("air_temperature_c", "humidity_pct"), offsets={"ph": 1}),
                                          dev("d2", REST_A)), "does not carry"),
    ("offset not a number", layout(dev("d1", ("air_temperature_c", "humidity_pct"), offsets={"humidity_pct": "x"}),
                                   dev("d2", REST_A)), "finite number"),
    ("offset a bool", layout(dev("d1", ("air_temperature_c", "humidity_pct"), offsets={"humidity_pct": True}),
                             dev("d2", REST_A)), "finite number"),
    ("offset infinite", layout(dev("d1", ("air_temperature_c", "humidity_pct"),
                                   offsets={"humidity_pct": float("inf")}), dev("d2", REST_A)), "finite number"),
    ("wander nan", layout(dev("d1", ("air_temperature_c", "humidity_pct"), wander={"humidity_pct": float("nan")}),
                          dev("d2", REST_A)), "finite number"),
    ("wander negative", layout(dev("d1", ("air_temperature_c", "humidity_pct"), wander={"humidity_pct": -1}),
                               dev("d2", REST_A)), "must not be negative"),
    ("offsets not an object", layout(dev("d1", ("air_temperature_c", "humidity_pct"), offsets=[1]),
                                     dev("d2", REST_A)), "must be an object"),
    ("one device with offsets", layout(dev("d1", ALL_A, offsets={"ph": 0.1})), "one device"),
    ("one device with wander", layout(dev("d1", ALL_A, wander={"ph": 0.1})), "one device"),
    ("one device with the alias", layout(dev("d1", [f if f != "soil_moisture_pct" else "substrate_moisture_pct"
                                                    for f in ALL_A])), "one device"),
]


@pytest.mark.parametrize("devices,message", [(d, m) for _, d, m in BAD_LAYOUTS], ids=[n for n, _, _ in BAD_LAYOUTS])
def test_bad_layouts_are_refused_at_construction(devices, message):
    with pytest.raises(ValueError, match=message):
        sim_for(devices)


def test_a_null_devices_key_is_refused_not_read_as_absent():
    with pytest.raises(ValueError, match="devices must be an object"):
        fg.Simulation(seed=1, clock=sim_helpers.make_clock(), scenario={"steps": [], "devices": None})


@pytest.mark.parametrize("zone", [["greenhouse-a"], {"id": A}, 7, True])
def test_a_step_with_an_unhashable_or_non_string_zone_is_a_value_error_when_devices_exist(zone):
    step = {"at_tick": 1, "start": "stuck", "zone": zone, "field": "ph"}
    with pytest.raises(ValueError, match="zone must be a string"):
        sim_for(SPLIT, steps=[step])


def test_a_hydroponic_zone_may_have_two_devices_and_eight_is_the_limit():
    sim_for({B: [dev("w1", ("air_temperature_c", "humidity_pct")), dev("w2", ("ec_ms_cm", "ph"))]})
    sim_for({A: [dev(f"d{i}", (f,)) for i, f in enumerate(ALL_A)] + [dev("extra1", ("ph",)), dev("extra2", ("ph",))]})


BAD_STEPS = [
    ("device not in zone", {"at_tick": 1, "start": "stuck", "zone": A, "device": "nope", "field": "ph"},
     "has no device"),
    ("device lacks the field", {"at_tick": 1, "start": "stuck", "zone": A, "device": "climate-1", "field": "ph"},
     "does not carry"),
    ("no device carries the field", {"at_tick": 1, "start": "stuck", "zone": A, "field": "water_temperature_c"},
     "does not carry"),
    ("default field on the wrong device", {"at_tick": 1, "start": "jump", "zone": A, "device": "climate-1"},
     "does not carry 'ph'"),
    ("event with a device", {"at_tick": 1, "start": "heat_spike", "zone": A, "device": "climate-1"}, "takes no device"),
    ("event stop with a device", {"at_tick": 1, "stop": "heat_spike", "zone": A, "device": "climate-1"},
     "takes no device"),
    ("stop names an unknown device", {"at_tick": 1, "stop": "stuck", "zone": A, "device": "nope"}, "has no device"),
    ("calibrate on the wrong device", {"at_tick": 1, "calibrate": "ph", "zone": A, "device": "climate-1"},
     "does not carry"),
    ("device is not a string", {"at_tick": 1, "start": "stuck", "zone": A, "device": 3, "field": "ph"}, "has no device"),
]


@pytest.mark.parametrize("step,message", [(s, m) for _, s, m in BAD_STEPS], ids=[n for n, _, _ in BAD_STEPS])
def test_steps_on_listed_zones_are_checked_against_the_layout(step, message):
    with pytest.raises(ValueError, match=message):
        sim_for(SPLIT, [step])


def test_steps_elsewhere_keep_their_late_failure():
    # zone B is not listed: its steps are checked only when their tick runs
    sim = sim_for(SPLIT, [{"at_tick": 1, "start": "stuck", "zone": B, "device": "nope", "field": "ph"}])
    with pytest.raises(ValueError, match="has no device"):
        run(sim, 2)
    # without a `devices` key nothing is checked early, and a step past the last tick never fails
    late = [{"at_tick": 99, "start": "stuck", "zone": A, "device": "nope", "field": "ph"}]
    run(sim_for(None, late), 3)


def test_a_null_field_counts_as_absent_so_the_default_field_decides():
    with pytest.raises(ValueError, match="does not carry 'ph'"):
        sim_for(SPLIT, [{"at_tick": 1, "start": "jump", "zone": A, "device": "climate-1", "field": None}])
    sim_for(SPLIT, [{"at_tick": 1, "start": "jump", "zone": A, "device": "substrate-1", "field": None}])


def test_device_on_a_one_device_zone_must_be_its_only_device():
    sim = sim_for(None, [{"at_tick": 1, "start": "stuck", "zone": A, "device": "fake-substrate-01", "field": "ph"}])
    run(sim, 3)
    assert [f.device_id for f in sim.zones[A].faults] == ["fake-substrate-01"]
    with pytest.raises(ValueError, match="has no device"):
        run(sim_for(None, [{"at_tick": 1, "start": "stuck", "zone": A, "device": "other", "field": "ph"}]), 3)
    one = sim_for(None)
    one.queue_start("stuck", A, "ph", device="fake-substrate-01")
    with pytest.raises(ValueError, match="has no device"):
        one.queue_start("stuck", A, "ph", device="other")
    listed = sim_for({A: [dev("only", ALL_A)]}, [{"at_tick": 1, "start": "stuck", "zone": A, "device": "only", "field": "ph"}])
    run(listed, 2)
    with pytest.raises(ValueError, match="has no device"):
        sim_for({A: [dev("only", ALL_A)]}, [{"at_tick": 1, "start": "stuck", "zone": A, "device": "x", "field": "ph"}])


def test_without_a_devices_key_zones_are_todays_and_sessions_have_no_devices_key():
    sim = sim_for(None)
    assert [len(z.devices) for z in sim.zones.values()] == [1, 1]
    assert [z.devices[0].device_id for z in sim.zones.values()] == ["fake-substrate-01", "fake-hydro-01"]
    assert [z.devices[0].sensors for z in sim.zones.values()] == [z.cfg.sensors for z in sim.zones.values()]
    run(sim, 3)
    assert "devices" not in sim.session_scenario()
    multi = sim_for(SPLIT)
    run(multi, 3)
    session = json.loads(json.dumps(multi.session_scenario()))
    assert session["devices"] == SPLIT
    replay = fg.Simulation(seed=session["seed"], clock=sim_helpers.make_clock(), scenario=session)
    assert [len(z.devices) for z in replay.zones.values()] == [2, 1]


def test_a_layout_may_name_a_one_device_zone_with_another_id_and_the_alias_needs_a_partner():
    sim = sim_for({A: [dev("only", ALL_A)]})
    rows = rows_of(run(sim, 2), A)
    assert [r["device_id"] for r in rows] == ["only", "only"] and "sensors" not in rows[0]
    assert sim.zones[A].devices[0].boot_id != sim_for(None).zones[A].devices[0].boot_id


# --- Readings: first-carrier noise, partners, offsets and wander -----------------------------------------------

READING_FIELDS = ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph", "soil_moisture_pct",
                  "substrate_temperature_c", "substrate_moisture_pct")


def test_a_split_zone_sends_the_one_device_values_field_by_field():
    one = run(sim_for(None, seed=5), 200)
    split = run(sim_for(SPLIT, seed=5), 200)
    one_a, split_a = rows_of(one, A), rows_of(split, A)
    assert len(split_a) == 2 * len(one_a)
    for tick, whole in enumerate(one_a):
        first, second = split_a[2 * tick], split_a[2 * tick + 1]
        assert (first["device_id"], second["device_id"]) == ("climate-1", "substrate-1")
        assert first["true"] == second["true"] == whole["true"]
        merged = {k: v for part in (first["sent"], second["sent"]) for k, v in part.items() if k in READING_FIELDS}
        assert merged == {k: v for k, v in whole["sent"].items() if k in READING_FIELDS}
        for k in ("crop", "growth_stage", "system_type", "weather", "zone_area_m2", "crop_kc", "npk_target",
                  "timestamp", "sequence", "farm_id", "zone_id", "source", "schema_version"):
            assert first["sent"][k] == second["sent"][k] == whole["sent"][k]
        assert first["sent"]["boot_id"] != second["sent"]["boot_id"]
    assert [json.dumps(t) for t in rows_of(one, B)] == [json.dumps(t) for t in rows_of(split, B)]


def test_the_zone_still_draws_every_field_and_a_later_device_draws_all_six_each_tick():
    sim = sim_for(SPLIT, seed=3)
    run(sim, 10)
    zone = sim.zones[A]
    probe = fg.random.Random(f"3:{A}:sensor")
    for _ in range(10 * len(fg.SENSOR_ORDER)):
        probe.gauss(0.0, 1.0)
    assert zone.sensor_rng.getstate() == probe.getstate()
    own = fg.random.Random(f"3:{A}:substrate-1:sensor")
    for _ in range(10 * len(fg.SENSOR_ORDER)):
        own.gauss(0.0, 1.0)
    assert zone.devices[1].sensor_rng.getstate() == own.getstate()
    assert zone.devices[0].sensor_rng is None  # the first device uses the zone's draws


def test_a_partner_differs_by_its_own_noise_offset_and_wander():
    scenario = pair_scenario()
    sim = fg.Simulation(seed=scenario["seed"], clock=sim_helpers.make_clock(), scenario={"devices": scenario["devices"]})
    readings = run(sim, 120)
    one, two = (rows_of(readings, A, d) for d in ("climate-1", "climate-2"))
    assert len(one) == len(two) == 120
    diffs = [b["sent"]["air_temperature_c"] - a["sent"]["air_temperature_c"] for a, b in zip(one, two)]
    assert len(set(diffs)) > 20  # not a constant: each probe has its own noise (and a wander)
    assert 0.0 < statistics.mean(diffs) < 0.8  # about the 0.4 offset
    for a, b in zip(one, two):
        assert a["true"] == b["true"]  # the zone's truth is shared
        assert "device_offset" not in a and set(b["device_offset"]) == {"air_temperature_c", "humidity_pct"}
        assert abs(b["device_offset"]["air_temperature_c"] - 0.4) <= 0.3 + 1e-9
        assert abs(b["device_offset"]["humidity_pct"] + 1.5) <= 1.0 + 1e-9
    moisture = {d: rows_of(readings, A, d) for d in ("substrate-1", "substrate-2")}
    first_alias = moisture["substrate-2"][0]["sent"]
    assert "substrate_moisture_pct" in first_alias and "soil_moisture_pct" not in first_alias


def test_wander_has_the_stated_spread_stays_inside_its_bound_and_tick_zero_draws_nothing():
    bound = 1.0
    devices = {A: [CLIMATE, dict(SUBSTRATE, sensors=SUBSTRATE["sensors"][:3] + ["substrate_temperature_c"]),
                   {"device_id": "climate-2", "sensors": ["air_temperature_c", "humidity_pct"],
                    "wander": {"humidity_pct": bound}}]}
    sim = sim_for(devices, seed=9, zones=(fg.DEFAULT_ZONES[0],))
    device = sim.zones[A].devices[2]
    fresh = fg.random.Random(f"9:{A}:climate-2:wander").getstate()
    sim.step()  # tick 0
    assert device.walk == {"humidity_pct": 0.0} and device.wander_rng.getstate() == fresh
    assert device.device_offset() == {"humidity_pct": 0.0}
    walk = []
    for _ in range(20_000):
        sim.step()
        walk.append(device.walk["humidity_pct"])
    assert max(abs(x) for x in walk) <= bound
    assert 0.3 * bound <= statistics.pstdev(walk) <= 0.5 * bound
    # one draw per listed field per tick from tick 1: the stream sits 20,000 draws further on
    own = fg.random.Random(f"9:{A}:climate-2:wander")
    for _ in range(20_000):
        own.gauss(0.0, 1.0)
    assert device.wander_rng.getstate() == own.getstate()


def test_wander_draws_follow_sensor_order_one_per_listed_field():
    devices = {A: [CLIMATE, dict(SUBSTRATE, wander={"substrate_temperature_c": 0.5, "ec_ms_cm": 0.2})]}
    sim = sim_for(devices, seed=4)
    run(sim, 3)
    device = sim.zones[A].devices[1]
    rng = fg.random.Random(f"4:{A}:substrate-1:wander")
    walks = {"ec_ms_cm": 0.0, "substrate_temperature_c": 0.0}
    bounds = {"ec_ms_cm": 0.2, "substrate_temperature_c": 0.5}
    dt_h = 30.0 / 3600.0
    for _ in range(2):  # ticks 1 and 2
        for field in fg.SENSOR_ORDER:
            if field in walks:
                walks[field] = fg.ou(walks[field], 0.5, 0.4 * bounds[field], rng.gauss(0.0, 1.0), dt_h, bounds[field])
    assert device.walk == pytest.approx(walks)


def test_starting_a_fault_on_one_device_changes_no_other_value_and_no_later_draw():
    steps = [{"at_tick": 40, "start": "stuck", "zone": A, "device": "climate-1", "field": "humidity_pct"},
             {"at_tick": 60, "start": "noisy", "zone": A, "device": "climate-2", "field": "air_temperature_c"}]
    scenario = pair_scenario()
    quiet = fg.Simulation(seed=23, clock=sim_helpers.make_clock(), scenario={"devices": scenario["devices"]})
    faulty = fg.Simulation(seed=23, clock=sim_helpers.make_clock(),
                           scenario={"devices": scenario["devices"], "steps": steps})
    base, hit = run(quiet, 120), run(faulty, 120)
    for a, b in zip(base, hit):
        key = (a.truth["zone_id"], a.truth["device_id"])
        assert key == (b.truth["zone_id"], b.truth["device_id"])
        if key == (A, "climate-1"):
            changed = {k for k in a.event if a.event[k] != b.event[k]}
            assert changed <= {"humidity_pct"}
        elif key == (A, "climate-2"):
            changed = {k for k in a.event if a.event[k] != b.event[k]}
            assert changed <= {"air_temperature_c"}
        else:
            assert a.event == b.event
        assert a.truth["true"] == b.truth["true"]
    for zone_a, zone_b in zip(quiet.zones.values(), faulty.zones.values()):
        assert zone_a.sensor_rng.getstate() == zone_b.sensor_rng.getstate()
        for da, db in zip(zone_a.devices, zone_b.devices):
            assert (da.sensor_rng is None) == (db.sensor_rng is None)
            if da.sensor_rng:
                assert da.sensor_rng.getstate() == db.sensor_rng.getstate()


# --- Faults, recovery, sequences, boot ids ----------------------------------------------------------------------

def test_a_fault_lives_on_one_device_with_its_own_recovery_tail_and_sequence():
    steps = [{"at_tick": 5, "start": "jump", "zone": A, "field": "ph", "params": {"offset": 1.5}},
             {"at_tick": 10, "stop": "jump", "zone": A}]
    rows = rows_of(run(sim_for(SPLIT, steps), 30), A)
    climate, substrate = ([r for r in rows if r["device_id"] == d] for d in ("climate-1", "substrate-1"))
    assert all(not r["active_faults"] and r["expect"]["kind"] == "normal" and not r["expect"]["recovering_from"]
               for r in climate)
    assert [r["tick"] for r in substrate if r["active_faults"]] == [5, 6, 7, 8, 9]
    assert all(r["active_faults"][0].keys() == {"name", "field", "started_at", "started_tick", "source"}
               for r in substrate if r["active_faults"])
    assert [r["expect"]["forbid_domain_cards_from"] for r in substrate if r["active_faults"]] == [["ph"]] * 5
    tail = [r["tick"] for r in substrate if r["expect"]["recovering_from"]]
    assert tail == list(range(10, 10 + fg.RECOVERY_SAMPLES))
    assert [r["sequence"] for r in climate] == list(range(30)) and [r["sequence"] for r in substrate] == list(range(30))


def test_a_whole_device_dropout_stops_only_that_device():
    steps = [{"at_tick": 4, "start": "dropout", "zone": A, "device": "climate-1"},
             {"at_tick": 8, "stop": "dropout", "zone": A, "device": "climate-1"}]
    readings = run(sim_for(SPLIT, steps), 12)
    climate, substrate = rows_of(readings, A, "climate-1"), rows_of(readings, A, "substrate-1")
    assert [r["published"] for r in climate] == [t not in (4, 5, 6, 7) for t in range(12)]
    assert all(r["published"] for r in substrate) and all(r["published"] for r in rows_of(readings, B))
    assert [r["sequence"] for r in climate if r["published"]] == list(range(8))  # no sequence is spent while silent
    assert climate[4]["reason"] == "dropout" and climate[4]["expect"]["kind"] == "not_published"
    assert substrate[4]["reason"] is None and substrate[4]["expect"]["kind"] == "normal"
    assert [r for r in readings if r.event is None and r.truth["device_id"] != "climate-1"] == []


def test_dead_clock_on_one_device_only_refuses_its_packets():
    steps = [{"at_tick": 3, "start": "dead_clock", "zone": A, "device": "substrate-1"}]
    readings = run(sim_for(SPLIT, steps), 6)
    assert {r.event["timestamp"] for r in readings if r.truth["device_id"] == "climate-1"} != {fg.DEAD_CLOCK_TIMESTAMP}
    assert all(r.event["timestamp"] == fg.DEAD_CLOCK_TIMESTAMP for r in readings
               if r.truth["device_id"] == "substrate-1" and r.truth["tick"] >= 3)
    assert all(r.event["timestamp"] != fg.DEAD_CLOCK_TIMESTAMP for r in readings if r.truth["device_id"] == "climate-1")
    assert [r.truth["expect"]["kind"] for r in readings if r.truth["device_id"] == "substrate-1"][3:] == \
        ["rejected_by_core"] * 3


def test_boot_ids_keep_the_formula_and_differ_by_device():
    import hashlib

    sim = sim_for(SPLIT, seed=8)
    for device in sim.zones[A].devices + sim.zones[B].devices:
        want = "boot-" + hashlib.sha1(f"fake-greenhouse:8:{device.device_id}".encode()).hexdigest()[:8]
        assert device.boot_id == want
    assert sim.zones[B].devices[0].boot_id == sim_for(None, seed=8).zones[B].devices[0].boot_id
    assert len({d.boot_id for d in sim.zones[A].devices}) == 2
    events = [r.event for r in run(sim, 2) if r.truth["zone_id"] == A]
    assert {e["boot_id"] for e in events} == {d.boot_id for d in sim.zones[A].devices}


# --- Commands and steps with a device ---------------------------------------------------------------------------

def pair_sim(steps=None, seed=23):
    scenario = pair_scenario()
    return fg.Simulation(seed=seed, clock=sim_helpers.make_clock(),
                         scenario={"devices": scenario["devices"], "steps": steps or []})


def test_the_same_fault_on_two_devices_is_two_faults_and_the_same_one_twice_is_one():
    sim = pair_sim()
    sim.step()
    one = sim.start("stuck", A, "humidity_pct", device="climate-1")
    two = sim.start("stuck", A, "humidity_pct", device="climate-2")
    assert one is not two and (one.device_id, two.device_id) == ("climate-1", "climate-2")
    assert sim.start("stuck", A, "humidity_pct", device="climate-1") is one
    assert sim.start("stuck", A, "humidity_pct") is one  # no device: the first carrier, the same fault
    assert len(sim.zones[A].faults) == 2
    hidden = sim.start("stuck", A, "humidity_pct", source="hidden", device="climate-1")
    assert hidden is not one


def test_field_faults_default_to_the_first_device_carrying_the_field():
    sim = pair_sim()
    sim.step()
    assert sim.start("stuck", A, "air_temperature_c").device_id == "climate-1"
    assert sim.start("jump", A).device_id == "substrate-1"  # default field ph
    assert sim.start("stuck", A, "substrate_moisture_pct").device_id == "substrate-1"  # alias, canonical probe
    assert sim.start("stuck", A, "soil_moisture_pct", device="substrate-2").device_id == "substrate-2"
    with pytest.raises(ValueError, match="has no sensor field"):
        sim.start("stuck", A, "ph", device="climate-1")


def test_whole_device_faults_default_to_the_zones_first_device():
    sim = pair_sim()
    sim.step()
    assert sim.start("dropout", A).device_id == "substrate-1"
    assert sim.start("dead_clock", A, device="climate-2").device_id == "climate-2"


def test_events_refuse_a_device():
    sim = pair_sim()
    sim.step()
    with pytest.raises(ValueError, match="takes no device"):
        sim.start("heat_spike", A, device="climate-1")
    with pytest.raises(ValueError, match="takes no device"):
        sim.queue_start("heat_spike", A, device="climate-1")
    with pytest.raises(ValueError, match="takes no device"):
        sim.queue_stop("heat_spike", A, device="climate-1")
    assert sim.start("heat_spike", A).device_id is None


def test_stop_without_a_device_stops_every_matching_fault_and_with_one_only_its_own():
    sim = pair_sim()
    sim.step()
    sim.start("stuck", A, "humidity_pct", device="climate-1")
    sim.start("stuck", A, "humidity_pct", device="climate-2")
    assert sim.stop("stuck", A, "humidity_pct", device="climate-2") == 1
    assert [f.device_id for f in sim.zones[A].faults if not f.stopping] == ["climate-1"]
    assert sim.stop("stuck", A, "humidity_pct", device="climate-2") == 0  # already stopping
    sim.start("stuck", A, "humidity_pct", device="climate-2")
    assert sim.stop("stuck", A, "humidity_pct") == 2
    with pytest.raises(ValueError, match="has no device"):
        sim.stop("stuck", A, device="nope")


def test_calibrate_defaults_to_the_first_device_carrying_the_probe_and_rides_on_its_row():
    steps = [{"at_tick": 2, "calibrate": "soil_moisture_pct", "zone": A},
             {"at_tick": 3, "calibrate": "soil_moisture_pct", "zone": A, "device": "substrate-2"},
             {"at_tick": 4, "calibrate": "humidity_pct", "zone": A, "device": "climate-2"}]
    readings = run(pair_sim(steps), 6)
    marked = [(r["tick"], r["device_id"], [c["field"] for c in r["calibrations"]])
              for r in rows_of(readings, A) if "calibrations" in r]
    assert marked == [(2, "substrate-1", ["soil_moisture_pct"]), (3, "substrate-2", ["soil_moisture_pct"]),
                      (4, "climate-2", ["humidity_pct"])]
    posted = [(r.truth["device_id"], c["field"]) for r in readings if r.calibrations for c in r.calibrations]
    assert posted == [(d, f) for _, d, fs in marked for f in fs]
    with pytest.raises(ValueError, match="cannot be calibrated"):
        sim = pair_sim()
        sim.step()
        sim.calibrate(A, "ph", device="climate-1")


def test_a_calibration_reference_is_the_probes_own_true_value():
    steps = [{"at_tick": 20, "calibrate": "humidity_pct", "zone": A, "device": "climate-2"},
             {"at_tick": 20, "calibrate": "humidity_pct", "zone": A, "device": "climate-1"}]
    readings = run(pair_sim(steps), 22)
    by_device = {r.truth["device_id"]: r for r in readings if r.calibrations and r.truth["zone_id"] == A}
    plain, hung = by_device["climate-1"], by_device["climate-2"]
    true = plain.truth["true"]["humidity_pct"]
    assert plain.calibrations[0]["reference"] == true  # no offset: the zone's own value
    offset = hung.truth["device_offset"]["humidity_pct"]
    assert hung.calibrations[0]["reference"] == pytest.approx(true + offset, abs=1e-4)
    assert hung.calibrations[0]["reference"] != true
    for reading in (plain, hung):  # a meter next to the probe differs from the raw reading by noise only
        calibration = reading.calibrations[0]
        assert abs(calibration["raw"] - calibration["reference"]) <= 5 * fg.NOISE["humidity_pct"] + fg.STEP["humidity_pct"]


def test_stop_all_records_the_device_in_multi_device_zones_only():
    sim = pair_sim()
    sim.step()
    sim.queue_start("stuck", A, "humidity_pct", device="climate-2")
    sim.queue_start("noisy", B, "humidity_pct", {"factor": 5})
    sim.queue_start("heat_spike", A)
    sim.queue_start("dropout", A)
    sim.step()
    sim.queue_stop_all()
    sim.step()
    by_name = {s["stop"]: s for s in sim.recorded if "stop" in s}
    assert by_name["stuck"]["device"] == "climate-2" and by_name["dropout"]["device"] == "substrate-1"
    assert "device" not in by_name["heat_spike"] and "device" not in by_name["noisy"]
    starts = {s["start"]: s for s in sim.recorded if "start" in s}
    assert starts["stuck"]["device"] == "climate-2" and starts["dropout"]["device"] == "substrate-1"
    assert "device" not in starts["heat_spike"] and "device" not in starts["noisy"]


def test_a_recorded_multi_device_session_replays_to_the_same_truth_log():
    script = {
        3: lambda s: s.queue_start("stuck", A, "humidity_pct", device="climate-2"),
        5: lambda s: s.queue_start("stuck", A, "humidity_pct", device="climate-1"),
        6: lambda s: s.queue_hidden(),
        7: lambda s: s.queue_calibrate(A, "soil_moisture_pct", device="substrate-2"),
        9: lambda s: s.queue_start("drift", A, "soil_moisture_pct", {"rate_per_min": -2}),
        12: lambda s: s.queue_stop("stuck", A, "humidity_pct", device="climate-2"),
        14: lambda s: s.queue_stop_hidden(1),
        20: lambda s: s.queue_stop_all(),
    }
    live = pair_sim()
    live_rows = []
    for tick in range(30):
        if tick in script:
            script[tick](live)
        live_rows += [r.truth for r in live.step()]
    session = json.loads(json.dumps(live.session_scenario()))
    assert session["devices"] == pair_scenario()["devices"]
    assert any(step.get("device") for step in session["steps"])
    replay = fg.Simulation(seed=23, clock=sim_helpers.make_clock(), scenario=session)
    replay_rows = [r.truth for _ in range(30) for r in replay.step()]
    assert [json.dumps(t) for t in live_rows] == [json.dumps(t) for t in replay_rows]


def test_a_hidden_stop_records_the_device_it_stopped():
    sim = pair_sim()
    hidden_id = sim.queue_hidden()
    sim.step()
    entry = sim.hidden_log[hidden_id - 1]
    sim.queue_stop_hidden(hidden_id)
    sim.step()
    stop = [s for s in sim.recorded if "stop" in s and s["source"] == "hidden"]
    assert stop and stop[0].get("device") == entry.get("device")


def test_hidden_random_in_a_multi_device_zone_names_a_device():
    sim = pair_sim(seed=3)
    ids = [sim.queue_hidden() for _ in range(12)]
    assert ids == list(range(1, 13))
    log = sim.hidden_log
    carriers = {z: {d.device_id: set(d.sensors) for d in sim.zones[z].devices} for z in sim.zones}
    for entry in log:
        zone = sim.zones[entry["zone"]]
        if zone.multi and fg.REGISTRY[entry["name"]].kind == "real_event":
            assert entry["device"] is None  # events change the zone's truth: no device
        elif zone.multi:
            assert entry["device"] in carriers[entry["zone"]]
            if entry["name"] in ("jump", "spike"):
                assert "ph" in carriers[entry["zone"]][entry["device"]]
            if entry["field"] and entry["name"] in ("stuck", "noisy"):
                assert entry["field"] in carriers[entry["zone"]][entry["device"]]
        else:
            assert "device" not in entry
    assert len({(e["name"], e["zone"], e.get("device")) for e in log}) == len(log)  # the triple is never taken twice
    sim.step()
    for _ in range(2):
        sim.step()
    started = {i.hidden_id: i for z in sim.zones.values() for i in z.faults + z.events if i.hidden_id}
    assert started
    state = sim.state()
    assert all("name" not in h for h in state["hidden"])  # still anonymous
    sim.reveal()
    revealed = sim.state()["hidden"]
    assert all(("device" in h) == sim.zones[h["zone"]].multi for h in revealed)
    assert all("device" in e for e in sim.reveal() if sim.zones[e["zone"]].multi)
    for h in revealed:
        if sim.zones[h["zone"]].multi:
            assert h["device"] == started[h["id"]].device_id


def test_a_single_device_layout_draws_hidden_random_as_before():
    plain = sim_for(None, seed=6)
    named = sim_for({A: [dev("fake-substrate-01", ALL_A)]}, seed=6)
    for sim in (plain, named):
        for _ in range(8):
            sim.queue_hidden()
    assert plain.hidden_log == named.hidden_log
    assert all("device" not in e for e in plain.hidden_log)


def test_hidden_random_without_devices_matches_the_pre_slice_algorithm_draw_for_draw():
    # Pinned from `git show 3013bc3:examples/simulators/fake_greenhouse.py` (the code before multi-device zones).
    sim = sim_for(None, seed=11)
    for _ in range(5):
        sim.queue_hidden()
    assert [(e["name"], e["zone"], e["field"]) for e in sim.hidden_log] == [
        ("humid_night", A, None), ("spike", B, "ph"), ("plausible_offset", B, "ec_ms_cm"),
        ("drift", B, "ec_ms_cm"), ("noisy", A, "ph")]


def test_hidden_random_can_run_out_of_triples():
    sim = sim_for({B: [dev("w1", ("air_temperature_c", "humidity_pct")), dev("w2", ("ec_ms_cm", "ph"))]},
                  zones=(fg.DEFAULT_ZONES[1],))
    with pytest.raises(ValueError, match="already running hidden"):
        for _ in range(200):
            sim.queue_hidden()


# --- Zone properties -------------------------------------------------------------------------------------------

def test_zone_properties_for_one_and_multi_device_zones():
    one = sim_for(None).zones
    a, b = one[A], one[B]
    assert a.cfg is fg.DEFAULT_ZONES[0] and a.events == [] and a.faults == []
    assert [d.device_id for d in a.devices] == ["fake-substrate-01"]
    assert (a.placeholder_fields, b.placeholder_fields) == ([], ["soil_moisture_pct"])
    assert a.calibratable == ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct", "soil_moisture_pct"]
    assert b.calibratable == ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct"]
    assert a.boot_id == a.devices[0].boot_id and a.sequence == 0 and a.last_sent == {} and a.silent_fields() == []

    multi = sim_for(SPLIT)
    zone = multi.zones[A]
    assert [d.device_id for d in zone.devices] == ["climate-1", "substrate-1"]
    assert zone.placeholder_fields == []
    assert zone.calibratable == a.calibratable  # CALIBRATABLE order, union over devices
    run(multi, 3)
    assert zone.sequence == 3 and zone.boot_id == zone.devices[0].boot_id
    assert zone.last_sent == zone.devices[0].last_sent and set(zone.last_sent) == {"air_temperature_c", "humidity_pct"}
    multi.start("stuck", A, "humidity_pct")
    multi.start("probe_dropout", A, "ec_ms_cm")
    multi.start("probe_dropout", A, "soil_moisture_pct")
    multi.start("heat_spike", A)
    assert [(f.name, f.device_id) for f in zone.faults] == [
        ("stuck", "climate-1"), ("probe_dropout", "substrate-1"), ("probe_dropout", "substrate-1")]
    assert zone.silent_fields() == ["ec_ms_cm", "soil_moisture_pct", "substrate_moisture_pct"]
    assert len(zone.events) == 1
    hydro = sim_for({B: [dev("w1", ("air_temperature_c", "humidity_pct")), dev("w2", ("ec_ms_cm", "ph"))]})
    assert hydro.zones[B].placeholder_fields == []
    with pytest.raises(AttributeError):
        zone.faults = []  # read-only


def test_one_device_zones_keep_their_attributes_after_faults_and_recovery():
    sim = sim_for(None, [{"at_tick": 2, "start": "jump", "zone": B, "field": "ph"},
                         {"at_tick": 4, "stop": "jump", "zone": B}])
    run(sim, 5)
    zone = sim.zones[B]
    assert zone.faults == [] and zone.recovery and zone.recovery[0][0] == "jump"
    assert zone.sequence == 5 and zone.last_sent["ph"] > 0


# --- Truth rows ------------------------------------------------------------------------------------------------

TODAYS_KEYS = ["tick", "wall_timestamp", "sim_time", "sim_day", "sim_hour", "zone_id", "device_id", "published",
               "reason", "sequence", "true", "sent", "active_faults", "active_events", "placeholder_fields", "expect"]
TODAYS_EXPECT = ["kind", "expected_labels", "forbid_domain_cards_from", "detectable", "onset_step", "recovering_from"]


def test_one_row_per_device_per_tick_with_shared_truth_and_the_new_keys_in_order():
    scenario = pair_scenario()
    readings = run(fg.Simulation(seed=23, clock=sim_helpers.make_clock(), scenario=scenario), 3)
    assert [(r.truth["tick"], r.truth["zone_id"], r.truth["device_id"]) for r in readings[:6 + 0]] == [
        (0, A, "substrate-1"), (0, A, "substrate-2"), (0, A, "climate-1"), (0, A, "climate-2"),
        (0, B, "fake-hydro-01"), (1, A, "substrate-1")]
    assert len(readings) == 3 * 5
    for r in readings:
        row = r.truth
        if row["zone_id"] == B:
            assert list(row) == TODAYS_KEYS and list(row["expect"]) == TODAYS_EXPECT
            continue
        offsets = ["device_offset"] if row["device_id"] in ("substrate-2", "climate-2") else []
        assert list(row) == TODAYS_KEYS[:15] + ["sensors"] + offsets + ["expect"]
        assert list(row["expect"]) == TODAYS_EXPECT + ["device_labels"]
        assert row["sensors"] == [f for f in fg.SENSOR_ORDER if f in row["sensors"]]
    tick0 = [r.truth for r in readings if r.truth["tick"] == 0 and r.truth["zone_id"] == A]
    assert len({json.dumps(t["true"]) for t in tick0}) == 1 and len({t["sim_time"] for t in tick0}) == 1
    assert len({json.dumps(t["expect"]["expected_labels"]) for t in tick0}) == 1
    assert [t["sensors"] for t in tick0] == [
        ["ec_ms_cm", "ph", "soil_moisture_pct", "substrate_temperature_c"], ["soil_moisture_pct"],
        ["air_temperature_c", "humidity_pct"], ["air_temperature_c", "humidity_pct"]]
    rounded = {t["device_id"]: t["device_offset"] for t in tick0 if "device_offset" in t}
    assert set(rounded) == {"substrate-2", "climate-2"}
    assert rounded["substrate-2"] == {"soil_moisture_pct": 1.0}  # tick 0: no wander yet
    assert rounded["climate-2"] == {"air_temperature_c": 0.4, "humidity_pct": -1.5}
    tick2 = next(r.truth for r in readings if r.truth["tick"] == 2 and r.truth["device_id"] == "climate-2")
    assert all(v == round(v, 4) for v in tick2["device_offset"].values())


def test_one_device_zones_in_a_mixed_log_keep_todays_rows():
    base = run(sim_for(None, seed=2), 10)
    mixed = run(sim_for(SPLIT, seed=2), 10)
    assert [json.dumps(t) for t in rows_of(base, B)] == [json.dumps(t) for t in rows_of(mixed, B)]


def test_device_labels_follow_the_probes_a_device_carries():
    steps = [{"at_tick": 1, "start": "heat_spike", "zone": A, "params": {"ramp_min": 0.5, "target": 34.0}},
             {"at_tick": 1, "start": "humid_night", "zone": A, "params": {"ramp_min": 0.5}},
             {"at_tick": 1, "start": "nutrient_over_concentration", "zone": A, "params": {"ramp_min": 0.5, "target": 6.0}},
             {"at_tick": 1, "start": "dry_zone", "zone": A, "params": {"drying_pct_per_hour": 4000}}]
    devices = {A: [CLIMATE, dict(SUBSTRATE, sensors=["ec_ms_cm", "ph", "substrate_temperature_c"]),
                   {"device_id": "moisture-2", "sensors": ["substrate_moisture_pct"]}]}
    readings = run(sim_for(devices, steps, seed=5), 80)
    last = {r["device_id"]: r for r in rows_of(readings, A) if r["tick"] == 79}
    labels = last["climate-1"]["expect"]["expected_labels"]
    assert {"heat_stress", "fungal_pressure", "high_ec", "water_level_risk"} <= set(labels)
    assert last["climate-1"]["expect"]["device_labels"] == ["heat_stress", "fungal_pressure"]
    hot_substrate = last["substrate-1"]["true"]["substrate_temperature_c"] >= fg.HEAT_C  # follows the air, with a lag
    assert last["substrate-1"]["expect"]["device_labels"] == (["heat_stress"] if hot_substrate else []) + ["high_ec"]
    assert last["moisture-2"]["expect"]["device_labels"] == ["water_level_risk"]  # through the alias device
    assert all(r["expect"]["expected_labels"] == labels for r in last.values())


def test_expected_labels_with_fields_counts_only_through_those_probes():
    hot = {"air_temperature_c": 31.0, "substrate_temperature_c": 20.0, "humidity_pct": 60.0, "vpd_kpa": 1.5,
           "ec_ms_cm": 5.0, "substrate_moisture_pct": 5.0}
    assert fg.expected_labels(hot) == ["heat_stress", "high_ec", "water_level_risk"]
    assert fg.expected_labels(hot, fields=["air_temperature_c"]) == ["heat_stress"]
    assert fg.expected_labels(hot, fields=["substrate_temperature_c"]) == []
    assert fg.expected_labels(hot, fields=["ec_ms_cm", "soil_moisture_pct"]) == ["high_ec", "water_level_risk"]
    assert fg.expected_labels(hot, fields=["ph"]) == []
    damp = {"air_temperature_c": 12.0, "substrate_temperature_c": 12.0, "humidity_pct": 60.0, "vpd_kpa": 0.3,
            "ec_ms_cm": 2.0}
    assert fg.expected_labels(damp, fields=["air_temperature_c"]) == ["cold_stress"]  # low VPD needs air and humidity
    assert fg.expected_labels(damp, fields=["air_temperature_c", "humidity_pct"]) == ["cold_stress", "fungal_pressure"]
    assert fg.expected_labels(damp, fields=["substrate_temperature_c"]) == ["cold_stress"]
    assert fg.expected_labels(damp, fields=[]) == []
    assert fg.expected_labels(damp) == ["cold_stress", "fungal_pressure"]


# --- Packets ---------------------------------------------------------------------------------------------------

def test_the_alias_device_sends_the_alias_only_and_a_soil_device_sends_both():
    readings = run(pair_sim(), 3)
    both = next(r.event for r in readings if r.truth["device_id"] == "substrate-1")
    alias = next(r.event for r in readings if r.truth["device_id"] == "substrate-2")
    assert both["soil_moisture_pct"] == both["substrate_moisture_pct"]
    assert "soil_moisture_pct" not in alias and "substrate_moisture_pct" in alias
    assert [k for k in alias if k in READING_FIELDS] == ["substrate_moisture_pct"]
    assert alias["system_type"] == both["system_type"] and alias["weather"] == both["weather"]
    probe_dropout = pair_sim([{"at_tick": 1, "start": "probe_dropout", "zone": A, "device": "substrate-2",
                               "field": "soil_moisture_pct"}])
    events = [r for r in run(probe_dropout, 3) if r.truth["device_id"] == "substrate-2"]
    assert "substrate_moisture_pct" in events[0].event and "substrate_moisture_pct" not in events[1].event
    assert events[1].truth["expect"]["silent_fields"] == ["soil_moisture_pct"]


def test_a_multi_device_hydroponic_zone_sends_no_placeholder():
    devices = {B: [dev("w1", ("air_temperature_c", "humidity_pct")), dev("w2", ("ec_ms_cm", "ph"))]}
    readings = run(sim_for(devices), 3)
    rows = rows_of(readings, B)
    assert [r["device_id"] for r in rows[:2]] == ["w1", "w2"]
    assert all(r["placeholder_fields"] == [] for r in rows)
    for r in readings:
        if r.truth["zone_id"] == B:
            assert "soil_moisture_pct" not in r.event
            assert set(r.event) >= {"device_id", "zone_id", "timestamp", "sequence", "boot_id", "crop"}
    w1 = next(r.event for r in readings if r.truth["device_id"] == "w1")
    assert "ec_ms_cm" not in w1 and "air_temperature_c" in w1
    one = rows_of(run(sim_for(None), 1), B)[0]
    assert one["placeholder_fields"] == ["soil_moisture_pct"]  # a one-device zone keeps its placeholder


def test_every_packet_of_a_substrate_zone_carries_the_same_context_and_topics_name_the_device():
    readings = run(sim_for(SPLIT), 2)
    a_events = [r for r in readings if r.truth["zone_id"] == A]
    assert [r.topic for r in a_events[:2]] == ["pomona/demo-farm/greenhouse-a/sensor/climate-1/state",
                                              "pomona/demo-farm/greenhouse-a/sensor/substrate-1/state"]
    for key in ("crop", "growth_stage", "system_type", "weather", "zone_area_m2", "crop_kc", "npk_target"):
        assert a_events[0].event[key] == a_events[1].event[key]
    assert a_events[0].event["timestamp"] == a_events[1].event["timestamp"]


def test_packets_validate_against_cores_sensor_event_schema():
    sys.path.insert(0, str(ROOT / "services" / "core"))
    from app.schemas import SensorEvent

    for r in run(pair_sim(), 5):
        SensorEvent.model_validate(r.event)


# --- Scenario files --------------------------------------------------------------------------------------------

def test_multi_device_scenario_is_demo_with_zone_a_split():
    demo = fg.load_scenario(SIM_DIR / "scenarios" / "demo.json")
    multi = fg.load_scenario(SIM_DIR / "scenarios" / "multi_device.json")
    assert {k: v for k, v in multi.items() if k != "devices"} == demo
    assert [d["device_id"] for d in multi["devices"][A]] == ["climate-1", "substrate-1"]
    assert B not in multi["devices"]
    one = run(fg.Simulation(seed=demo["seed"], clock=sim_helpers.make_clock(), scenario=demo), 60)
    two = run(fg.Simulation(seed=multi["seed"], clock=sim_helpers.make_clock(), scenario=multi), 60)
    assert [json.dumps(t) for t in rows_of(one, B)] == [json.dumps(t) for t in rows_of(two, B)]
    for whole, first, second in zip(rows_of(one, A), rows_of(two, A)[::2], rows_of(two, A)[1::2]):
        assert whole["true"] == first["true"] == second["true"]
        merged = {k: v for part in (first["sent"], second["sent"]) for k, v in part.items() if k in READING_FIELDS}
        assert merged == {k: v for k, v in whole["sent"].items() if k in READING_FIELDS}


def test_slow_drift_scenario_layout_and_margins():
    scenario = pair_scenario()
    assert scenario["seed"] == 23 and scenario["duration_ticks"] == 1000
    sim = fg.Simulation(seed=23, clock=sim_helpers.make_clock(), scenario=scenario)
    zone = sim.zones[A]
    assert [d.device_id for d in zone.devices] == ["substrate-1", "substrate-2", "climate-1", "climate-2"]
    assert zone.devices[1].alias_only and zone.devices[1].offsets == {"soil_moisture_pct": 1.0}
    assert zone.devices[3].wander == {"air_temperature_c": 0.3, "humidity_pct": 1.0}
    assert len(sim.zones[B].devices) == 1
    assert min(s["at_tick"] for s in scenario["steps"]) == 240  # the first two hours are clean
    rows = [r.truth for _ in range(1000) for r in sim.step()]
    windows = [(240, 320, A, "climate-1", "air_temperature_c", 18.0), (240, 320, B, "fake-hydro-01", "air_temperature_c", 18.0),
               (560, 640, A, "substrate-2", "substrate_moisture_pct", 20.0)]
    for start, end, zone_id, device, field, floor in windows:
        sel = [r for r in rows if r["zone_id"] == zone_id and r["device_id"] == device and start <= r["tick"] <= end]
        assert min(r["sent"][field] for r in sel) >= floor
        assert not any(r["expect"]["expected_labels"] for r in sel)
    window = [r for r in rows if 400 <= r["tick"] <= 480 and r["zone_id"] == A]
    assert not any(r["expect"]["expected_labels"] for r in window)
    assert not any(r["expect"]["expected_labels"] for r in rows if r["tick"] < 780)


# --- Catalog, state and the control endpoints ------------------------------------------------------------------

@pytest.fixture
def control():
    sim = pair_sim()
    server = fg.start_control_server(sim, "127.0.0.1", 0)
    port = server.server_address[1]

    def call(method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(method, path, None if body is None else json.dumps(body), {"Content-Type": "application/json"})
        response = conn.getresponse()
        data = json.loads(response.read().decode())
        conn.close()
        return response.status, data

    yield sim, call
    server.shutdown()
    server.server_close()


def test_catalog_lists_devices_only_for_a_multi_device_zone(control):
    sim, call = control
    zones = call("GET", "/api/catalog")[1]["zones"]
    a, b = zones
    assert list(b) == ["zone_id", "device_id", "system_type", "sensors", "calibratable"] and b["device_id"] == "fake-hydro-01"
    assert list(a) == ["zone_id", "device_id", "system_type", "sensors", "calibratable", "devices"]
    assert a["device_id"] == "substrate-1" and a["sensors"] == list(fg.DEFAULT_ZONES[0].sensors)
    assert [d["device_id"] for d in a["devices"]] == ["substrate-1", "substrate-2", "climate-1", "climate-2"]
    assert a["devices"][1] == {"device_id": "substrate-2", "sensors": ["soil_moisture_pct"],
                               "calibratable": ["soil_moisture_pct"]}
    assert a["devices"][3]["sensors"] == ["air_temperature_c", "humidity_pct"]
    injections = {i["name"]: i for i in call("GET", "/api/catalog")[1]["injections"]}
    assert injections["stuck"]["zones"] == [A, B] and injections["dry_zone"]["zones"] == [A]


def test_state_keeps_its_keys_and_adds_devices_for_a_multi_device_zone(control):
    sim, call = control
    for _ in range(3):
        sim.step()
    zones = call("GET", "/api/state")[1]["zones"]
    a, b = zones
    assert list(b) == ["zone_id", "device_id", "system_type", "sequence", "published", "last_sent", "injections"]
    assert list(a) == ["zone_id", "device_id", "system_type", "sequence", "published", "last_sent", "injections",
                       "devices"]
    assert a["device_id"] == "substrate-1" and a["sequence"] == 2 and a["last_sent"]["device_id"] == "substrate-1"
    assert [d["device_id"] for d in a["devices"]] == ["substrate-1", "substrate-2", "climate-1", "climate-2"]
    for d in a["devices"]:
        assert set(d) == {"device_id", "sensors", "sequence", "published", "last_sent", "injections"}
        assert d["sequence"] == 2 and d["published"] is True and d["last_sent"]["device_id"] == d["device_id"]
    assert a["devices"][2]["sensors"] == ["air_temperature_c", "humidity_pct"]


def test_endpoints_take_a_device_and_queue_it(control):
    sim, call = control
    sim.step()
    assert call("POST", "/api/start", {"name": "stuck", "zone": A, "field": "humidity_pct", "device": "climate-2"})[0] == 200
    assert call("POST", "/api/start", {"name": "heat_spike", "zone": A})[0] == 200
    state = call("GET", "/api/state")[1]
    assert state["pending"][0] == {"op": "start", "name": "stuck", "zone": A, "field": "humidity_pct",
                                   "device": "climate-2"}
    assert "device" not in state["pending"][1]
    sim.step()
    a = call("GET", "/api/state")[1]["zones"][0]
    assert a["injections"] == [
        {"name": "stuck", "field": "humidity_pct", "started_tick": 1, "stopping": False, "source": "manual",
         "device": "climate-2"},
        {"name": "heat_spike", "field": None, "started_tick": 1, "stopping": False, "source": "manual"}]
    assert [len(d["injections"]) for d in a["devices"]] == [0, 0, 0, 1]
    assert call("POST", "/api/calibrate", {"zone": A, "field": "humidity_pct", "device": "climate-1"})[0] == 200
    assert call("POST", "/api/stop", {"name": "stuck", "zone": A, "field": "humidity_pct", "device": "climate-2"})[0] == 200
    sim.step()
    assert [s for s in sim.recorded if "calibrate" in s] == [
        {"at_tick": 2, "calibrate": "humidity_pct", "zone": A, "device": "climate-1", "source": "manual"}]
    stop = next(s for s in sim.recorded if "stop" in s)
    assert stop["device"] == "climate-2" and stop["field"] == "humidity_pct"
    assert call("GET", "/api/scenario")[1]["devices"] == pair_scenario()["devices"]


def test_endpoints_answer_400_from_the_queue_checks(control):
    sim, call = control
    sim.step()
    bad = [
        ("/api/start", {"name": "stuck", "zone": A, "field": "ph", "device": "climate-1"}, "has no sensor field"),
        ("/api/start", {"name": "stuck", "zone": A, "field": "ph", "device": "nope"}, "has no device"),
        ("/api/start", {"name": "stuck", "zone": A, "field": "ph", "device": 3}, "device must be a string"),
        ("/api/start", {"name": "heat_spike", "zone": A, "device": "climate-1"}, "takes no device"),
        ("/api/start", {"name": "stuck", "zone": B, "field": "ph", "device": "climate-1"}, "has no device"),
        ("/api/start", {"name": "stuck", "zone": B, "field": "ph", "device": "substrate-1"}, "has no device"),
        ("/api/stop", {"name": "stuck", "zone": A, "device": "nope"}, "has no device"),
        ("/api/stop", {"name": "heat_spike", "zone": A, "device": "climate-1"}, "takes no device"),
        ("/api/calibrate", {"zone": A, "field": "ph", "device": "climate-1"}, "cannot be calibrated"),
        ("/api/calibrate", {"zone": A, "field": "ph", "device": "nope"}, "has no device"),
    ]
    for path, body, message in bad:
        status, data = call("POST", path, body)
        assert status == 400 and message in data["error"], (path, body, data)
    assert call("GET", "/api/state")[1]["queued"] == 0  # nothing reached the queue
    ok = call("POST", "/api/start", {"name": "stuck", "zone": B, "field": "ph", "device": "fake-hydro-01"})
    assert ok[0] == 200


def test_summary_line_names_the_device_only_for_multi_device_rows():
    readings = run(pair_sim([{"at_tick": 1, "start": "dropout", "zone": A, "device": "climate-2"}]), 2)
    lines = [fg.summary_line(r) for r in readings]
    by_device = {(r.truth["tick"], r.truth["device_id"]): line for r, line in zip(readings, lines)}
    assert by_device[(0, "climate-1")].startswith("tick 0 greenhouse-a device=climate-1 seq=0 ")
    assert by_device[(1, "climate-2")].startswith("tick 1 greenhouse-a device=climate-2 not published (dropout)")
    assert by_device[(0, "fake-hydro-01")].startswith("tick 0 greenhouse-b seq=0 ")
    assert all("device=" not in line for line in lines if "greenhouse-b" in line)


def test_control_page_has_device_selectors_and_still_takes_the_old_path():
    html = (SIM_DIR / "control_page.html").read_text()
    assert "zone.devices" in html and "deviceSelect" in html and "calDevice" in html
    assert "device:" in html  # start, stop and calibrate carry it
    assert "://" not in html and "<script src" not in html


def test_run_publishes_calibrations_per_device(tmp_path):
    posted = []

    class Recorder:
        def publish(self, topic, payload):
            return {"status": 201}

        def calibrate(self, farm_id, zone_id, device_id, calibration):
            posted.append((zone_id, device_id, calibration["field"]))
            return {"status": 201}

    sim = pair_sim([{"at_tick": 1, "calibrate": "humidity_pct", "zone": A, "device": "climate-2"}])
    with open(tmp_path / "t.jsonl", "w") as handle:
        fg.run(sim, Recorder(), handle, 3, None, log=open(tmp_path / "log.txt", "w"))
    assert posted == [(A, "climate-2", "humidity_pct")]
    rows = [json.loads(line) for line in (tmp_path / "t.jsonl").read_text().splitlines()]
    assert len(rows) == 15 and rows[5]["device_id"] == "substrate-1"


def test_the_noise_of_a_partner_has_the_probes_own_sigma():
    devices = {A: [CLIMATE, dict(SUBSTRATE), {"device_id": "climate-2", "sensors": ["air_temperature_c", "humidity_pct"]}]}
    readings = run(sim_for(devices, seed=13, zones=(fg.DEFAULT_ZONES[0],)), 600)
    one, two = (rows_of(readings, A, d) for d in ("climate-1", "climate-2"))
    diffs = [b["sent"]["humidity_pct"] - a["sent"]["humidity_pct"] for a, b in zip(one, two)]
    assert abs(statistics.mean(diffs)) < 0.15
    assert math.isclose(statistics.pstdev(diffs), math.sqrt(2) * fg.NOISE["humidity_pct"], rel_tol=0.15)
