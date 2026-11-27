"""The pair check in the in-process engine (docs/design/slow-drift-pair-check.md Design 2 and 3, "Two-device in-process
test"). Run with the model-router venv. Core's side of the same rows is services/core/tests/test_pair_check.py and
services/core/tests/test_pair_inprocess_equality.py.

Readings are hand-built from integer arithmetic (value = base + i * step, never added up), so the limit is crossed on a
known reading. Both devices see the same slow variation (a triangle wave of +-0.5 C over 120 readings), because a stream
whose window values are all identical is "flat" and not judged, plus a constant offset per device and no noise.
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

import inprocess_pomona as engine
import score_fake_greenhouse as score

AIR = "air_temperature_c"
BASE = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
CLEAN = 240  # 2 hours of clean readings at 30 s
DRIFT_START = CLEAN  # the drift's first reading (no change yet) is reading 240; 0.05 C per reading from there
PAIR_TEXT = f"pair check: {AIR} on climate-1 is "


def wave(i):
    """The shared slow variation: a triangle of +-0.5 C over 120 readings (integer arithmetic, one division). Its step
    (0.0167 C per reading) is under the drift's (0.05) and over the router's flatline span (0.05 C in 6 readings), and
    it is falling while the drift crosses the limit (reading 300), so the drifting probe crosses before its partner."""
    phase = (i + 30) % 120
    height = phase if phase <= 60 else 120 - phase
    return 20 + (height - 30) / 60


def stamp(i):
    return (BASE + timedelta(seconds=30 * i)).isoformat().replace("+00:00", "Z")


def packet(device, i, value, zone="a", **extra):
    return {"farm_id": "farm", "zone_id": zone, "device_id": device, "timestamp": stamp(i), "crop": "tomato",
            "growth_stage": "flowering", "system_type": "greenhouse_substrate", AIR: value, **extra}


def readings(ticks, drift=None, ramp=None, quiet_from=None):
    """Both devices' packets, device 1 first in each tick. Device 2 sits 0.4 C above device 1.
    `drift`: first tick of a -0.1 C/min drift on device 1. `ramp`: (first tick, ticks up, ticks down): a heat ramp of
    +2.5 C per 5 minutes on both devices, then back down at the same rate. `quiet_from`: device 2 sends nothing from there."""
    out = []
    for i in range(ticks):
        shared = wave(i)
        if ramp is not None:
            first, up, down = ramp
            shared += (min(max(i - first, 0), up) - min(max(i - first - up, 0), down)) / 4  # 0.25 C per reading
        value1 = shared - (max(i - drift, 0) / 20 if drift is not None else 0)  # 0.05 C per reading
        out.append(packet("climate-1", i, value1))
        if quiet_from is None or i < quiet_from:
            out.append(packet("climate-2", i, shared + 0.4))
    return out


@pytest.fixture
def pomona():
    with engine.InProcessPomona(score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()),
                                score.alert_defaults()) as value:
        yield value


def run(pomona, packets, **kwargs):
    return [pomona.observe(p, **kwargs) for p in packets]


def tick_of(result):
    return round((result["sample_time"] - BASE).total_seconds() / 30)


def flagged(got, device="climate-1"):
    """The ticks at which the device's reading carried the pair check's flag."""
    return [tick_of(g) for g in got if g["device_id"] == device and AIR in g["vetoed_fields"]
            and "baseline_drift_possible" in g["labels"]]


def test_a_drift_on_one_of_two_probes_is_flagged_after_thirty_minutes_with_the_pair_text(pomona):
    got = run(pomona, readings(CLEAN + 100, drift=DRIFT_START), include_result=True)
    clean = [g for g in got[1:] if tick_of(g) < DRIFT_START]  # the zone's first packet is judged alone: "missing" labels
    assert not [g for g in clean if g["labels"]] and not [e for g in clean for e in g["alert_events"]]
    ticks = flagged(got)
    assert ticks, "the drift was never flagged"
    minutes = (ticks[0] - DRIFT_START) * 0.5
    assert 30 <= minutes <= 33.5
    # only the drifting probe is flagged: once its readings are vetoed they stop being partners
    assert flagged(got, "climate-2") == []
    raised = [(e["rule_id"], e["device_id"], e.get("detail")) for g in got for e in g["alert_events"] if e["event"] == "raised"]
    assert [(rule, device) for rule, device, _ in raised] == [("sensor_check", "climate-1")]
    assert raised[0][2].startswith(PAIR_TEXT)
    assert "calibrate only the one that was wrong" in raised[0][2]
    assert {(s["rule_id"], s["device_id"]) for s in pomona.states()} == {("sensor_check", "climate-1")}


def test_the_pair_entry_is_in_the_pipeline_input_only_in_a_paired_zone_once_it_has_12_offsets(pomona):
    seen = []
    for p in readings(40):
        pomona.observe(p, capture=lambda item, p=p: seen.append((p["device_id"], item["stream_baseline"])))
    first = [i for i, (device, ref) in enumerate(seen) if ref and "pair" in ref[AIR]]
    assert first and seen[first[0]][0] == "climate-1"
    entry = seen[first[0]][1][AIR]["pair"]
    assert entry["partner_device"] == "climate-2" and entry["device"] == "climate-1" and entry["partners"] == 1
    assert entry["n"] == 12 and entry["offset"] == pytest.approx(-0.4, abs=0.05)
    assert not [1 for _, ref in seen[:first[0]] if ref and "pair" in ref.get(AIR, {})]


def test_a_shared_heat_ramp_flags_neither_probe(pomona):
    # +2.5 C per 5 minutes for 20 minutes on both probes (a 10 C swing), then back down at the same rate
    got = run(pomona, readings(CLEAN + 140, ramp=(CLEAN + 20, 40, 40)))
    assert [g for g in got[1:] if g["sensor_check_labels"] or g["vetoed_fields"]] == []
    assert not [e for g in got for e in g["alert_events"] if e["rule_id"] in ("sensor_check", "sensor_flatline")]


def test_the_drift_is_still_flagged_while_a_heat_ramp_moves_both_probes(pomona):
    got = run(pomona, readings(CLEAN + 120, drift=DRIFT_START, ramp=(CLEAN + 10, 40, 40)))
    ticks = flagged(got)
    # a shared fall of 0.25 C per reading reaches a probe before its partner's earlier reading: up to 0.25 C, 5 readings
    assert ticks and 27.5 <= (ticks[0] - DRIFT_START) * 0.5 <= 33.5
    assert flagged(got, "climate-2") == []


def test_an_alert_already_raised_stays_raised_when_the_partner_goes_quiet_until_its_clear_window_passes(pomona):
    clear_s = pomona.defaults[1]
    got = run(pomona, readings(CLEAN + 100, drift=DRIFT_START))
    raised_tick = next(tick_of(g) for g in got if any(e["event"] == "raised" for e in g["alert_events"]))
    assert {(s["rule_id"], s["device_id"]) for s in pomona.states() if s["rule_id"] == "sensor_check"} == {("sensor_check", "climate-1")}
    # a fresh engine runs the same readings, but climate-2 goes quiet right after the raising tick
    with engine.InProcessPomona(pomona.rules, pomona.defaults) as other:
        quiet = readings(CLEAN + 160, drift=DRIFT_START, quiet_from=raised_tick + 1)
        flags, last_flag, recovered, held = [], None, None, 0
        for p in quiet:
            got = other.observe(p)
            if got["device_id"] != "climate-1":
                continue
            if "baseline_drift_possible" in got["labels"]:
                flags.append(tick_of(got))
                last_flag = got["sample_time"]
            if tick_of(got) <= raised_tick:
                continue
            open_now = {(s["rule_id"], s["device_id"]) for s in other.states() if s["rule_id"] == "sensor_check"}
            if any(e["event"] == "recovered" for e in got["alert_events"]):
                recovered = got["sample_time"]
                break
            assert open_now == {("sensor_check", "climate-1")}  # stays raised
            held += 1
    # the partner's last readings are fresh for 75 s, so flags stop within 3 readings of the quiet start...
    assert flags and flags[-1] <= raised_tick + 3
    # ...and the card then stays until the clear window has passed since the last flagged reading
    assert held >= (clear_s // 30) - 3 and recovered is not None
    assert (recovered - last_flag).total_seconds() >= clear_s


def tick_of_packet(p):
    return round((engine.parse_ts(p["timestamp"]) - BASE).total_seconds() / 30)


# --- off, and single-device zones ----------------------------------------------------------------------------------

def single_device(ticks):
    return [p for p in readings(ticks, drift=DRIFT_START) if p["device_id"] == "climate-1"]


def play(packets, **options):
    """Whole `observe(include_result=True)` outputs (less the pipeline's random id), the `pair` flags of every
    pipeline input, and the engine's pair buffer."""
    rules, defaults = score.parse_rules((score.AUTOMATION_APP / "rules.yaml").read_text()), score.alert_defaults()
    seen = []
    with engine.InProcessPomona(rules, defaults, **options) as pomona:
        out = [pomona.observe(p, include_result=True, capture=lambda item: seen.append(
            {field: "pair" in entry for field, entry in (item["stream_baseline"] or {}).items()})) for p in packets]
        for item in out:
            item["pipeline"].pop("pipeline_id", None)
        return out, seen, pomona._pairs._zones


def test_pair_check_off_and_a_single_device_zone_run_no_pair_code():
    # a single-device zone: the same whole outputs with the pair path on and off, and no buffer is ever made
    single = single_device(CLEAN + 100)
    on, seen_on, zones_on = play(single)
    off, seen_off, zones_off = play(single, pair_check=False)
    assert on == off and zones_on == {} and zones_off == {}
    assert not [1 for item in seen_on + seen_off for flag in item.values() if flag]
    # a two-device zone with pair_check=False: no pair entry, no buffer, no flag (the drift stays missed as before)
    both = readings(CLEAN + 100, drift=DRIFT_START)
    got, seen, zones = play(both, pair_check=False)
    assert zones == {} and not [1 for item in seen for flag in item.values() if flag]
    assert [g for g in got[1:] if g["sensor_check_labels"]] == []
    # the same zone with the pair check on differs only where the check acts: nothing before the drift's flag
    got_on, seen_on, zones_on = play(both)
    assert zones_on and [1 for item in seen_on for flag in item.values() if flag]
    first = next(i for i, g in enumerate(got_on) if g["labels"] and i > 0)
    assert got_on[:first] == got[:first]


def test_a_zone_with_two_devices_but_one_pair_device_runs_no_pair_path(pomona):
    """A pH-only device beside the air probe: the zone is multi-device, but only one device carries a pair field."""
    packets = []
    for i in range(30):
        packets.append(packet("climate-1", i, wave(i)))
        packets.append({**packet("ph-1", i, None), "ph": 6.0 + (i % 3) / 10})
    run(pomona, packets)
    assert pomona._pairs._zones == {}


def test_a_single_device_run_is_not_touched_by_a_later_second_zone(pomona):
    run(pomona, [packet("climate-1", i, wave(i), zone="a") for i in range(30)])
    run(pomona, [p for i in range(30) for p in (packet("x-1", i, wave(i), zone="b"), packet("x-2", i, wave(i) + 1, zone="b"))])
    assert set(pomona._pairs._zones) == {("farm", "b")}


# --- the buffer -----------------------------------------------------------------------------------------------------

def test_the_buffer_keeps_rows_within_the_window_and_its_row_cap_and_hands_over_per_device_lists():
    buffer = engine.PairBuffer(keep_s=600, max_rows=50)
    zone = ("farm", "z")
    for i in range(100):
        for device in ("d1", "d2"):
            buffer.add(zone, {"device_id": device, "timestamp": BASE + timedelta(seconds=30 * i), AIR: 1.0, "vetoed_fields": []})
    own = buffer.rows(zone, "d1")
    assert len(own) + len(buffer.rows(zone, "d2")) <= 50
    assert [r["timestamp"] for r in own] == sorted(r["timestamp"] for r in own)
    assert {r["device_id"] for r in buffer.partner_rows(zone, "d1")} == {"d2"}
    assert max(r["timestamp"] for r in own) == BASE + timedelta(seconds=30 * 99)
    small = engine.PairBuffer(keep_s=600)
    for i in range(100):
        small.add(zone, {"device_id": "d1", "timestamp": BASE + timedelta(seconds=30 * i), AIR: 1.0, "vetoed_fields": []})
    kept = small.rows(zone, "d1")
    assert kept[-1]["timestamp"] - kept[0]["timestamp"] == timedelta(seconds=600)  # newest minus keep_s, inclusive
    late = {"device_id": "d1", "timestamp": kept[3]["timestamp"] + timedelta(seconds=1), AIR: 2.0, "vetoed_fields": []}
    small.add(zone, late)
    assert small.rows(zone, "d1")[4] is late  # a late row goes in its place
    assert PAIR_CAP == 4000


PAIR_CAP = engine.PAIR_BUFFER_MAX_ROWS


def test_the_buffer_series_equal_series_built_from_its_rows_through_every_add(pomona):
    """In order, late, with the same sample time again, vetoed, a field missing and the other name, under the row cap and
    the window: the buffer's series always are what `pair_reference` would build from its rows."""
    import random
    baseline = pomona._baseline
    fields = baseline.PAIR_FIELDS
    zone = ("farm", "z")

    def built(rows, field):
        latest = {}
        for row in rows:
            entry = baseline.pair_row_entry(row, field)
            if entry is not None:
                latest[row["timestamp"]] = entry
        ordered = sorted(latest.items())
        return ([t for t, _ in ordered], [t.timestamp() for t, _ in ordered], [e[0] for _, e in ordered],
                [e[1] for _, e in ordered])

    for seed in range(6):
        rng = random.Random(seed)
        buffer = engine.PairBuffer(keep_s=rng.choice([300, 900]), max_rows=rng.choice([40, 400]), fields=fields,
                                   entry=baseline.pair_row_entry)
        for i in range(200):
            row = {"device_id": rng.choice(["d1", "d2", "d3"]), "vetoed_fields": []}
            tick = i - rng.choice([0, 0, 0, 0, 0, 1, 3, 8, 40])  # sometimes a late row
            row["timestamp"] = BASE + timedelta(seconds=30 * max(tick, 0) + rng.choice([0, 0, 5]))
            for field in rng.sample(fields, rng.randrange(0, 3)):
                row[field] = 20.0 + rng.random()
            if rng.random() < 0.1:
                row["vetoed_fields"] = [rng.choice(fields)]
            if not any(field in row for field in fields):
                row[AIR] = 20.0
            buffer.add(zone, row)
            if rng.random() < 0.15:
                buffer.add(zone, {**row, AIR: 21.5})  # the same sample time again
            for device in ("d1", "d2", "d3"):
                kept = buffer.rows(zone, device)
                for field in fields:
                    expected = built(kept, field)
                    got = buffer.series(zone, device, field)
                    assert got == expected if expected[0] else got == ([], [], [], []), (seed, i, device, field)
            assert set(buffer.partner_series(zone, "d1", AIR)) <= {"d2", "d3"}


def test_a_calibration_of_either_probe_restarts_the_pair_until_12_new_offsets_exist(pomona):
    entries = {}
    for p in readings(100):
        if p["device_id"] == "climate-1" and tick_of_packet(p) == 61:  # a meter check of climate-2, just before reading 61
            pomona.calibrate("a", AIR, BASE + timedelta(seconds=30 * 61 - 15), device_id="climate-2")
        pomona.observe(p, capture=lambda item, p=p: entries.__setitem__(
            (p["device_id"], tick_of_packet(p)), ((item["stream_baseline"] or {}).get(AIR) or {}).get("pair")))
    had = lambda device, lo, hi: [t for t in range(lo, hi) if entries.get((device, t))]  # noqa: E731
    assert had("climate-1", 13, 61) and had("climate-2", 13, 61)  # paired before the calibration
    # the pair counts from reading 61 on: climate-1's offsets are readings 62.. against climate-2's 61.., so its
    # 12th is reading 73 and the entry comes at reading 74; climate-2's offsets start at 62 too, and its entry at 74
    assert had("climate-1", 61, 74) == [] and had("climate-2", 61, 74) == []
    assert entries[("climate-1", 74)]["n"] == 12 and entries[("climate-2", 74)]["n"] == 12
