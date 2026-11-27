"""Slow-drift pair check, Core side (docs/design/slow-drift-pair-check.md Design 1-3): `pair_reference` on rows,
the store's three zone queries, and what Core's outcome feed sends. Readings are built from integer steps
(value = base + k * step), never by adding repeatedly."""
import copy
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
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

AIR = "air_temperature_c"
SOIL, SUBSTRATE = "soil_moisture_pct", "substrate_moisture_pct"
WINDOW = 7200
BASE = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)


def at(i, step=30):
    return BASE + timedelta(seconds=step * i)


def wiggle(i, base, scale=0.1):
    """A small steady wobble (never flat, steps far under every fast-change limit)."""
    return base + (i % 5) * scale


def rows(device, count, base, field=AIR, step=30, vetoed=(), start=0):
    return [{"device_id": device, "timestamp": at(i, step), field: wiggle(i, base), "vetoed_fields": list(vetoed)}
            for i in range(start, count)]


def current_at(i, base, device="own", field=AIR, step=30, value=None):
    return {"device_id": device, "timestamp": at(i, step), field: wiggle(i, base) if value is None else value}


def pair(own, partners, current, field=AIR, start=None, window=WINDOW, lapse=None):
    return tb.pair_reference(own, partners, field, start, current, window, lapse)


def basic(count=14, own_base=20.0, partner_base=18.0, **kwargs):
    """Own `count` readings before the current one (index `count`), one partner aligned on the same clock."""
    return pair(rows("own", count, own_base), rows("p1", count + 1, partner_base),
                current_at(count, own_base), **kwargs)


# --- the pure function ---------------------------------------------------------------------------------------------

def test_the_constants_are_the_designs():
    assert tb.PAIR_FIELDS == (AIR, "humidity_pct", SOIL, SUBSTRATE)
    assert (tb.PAIR_MIN_N, tb.PAIR_MAX_PARTNERS, tb.PAIR_INTERVALS) == (12, 8, 12)
    assert (tb.PAIR_AGE_INTERVALS, tb.PAIR_MAX_AGE_MIN_S, tb.PAIR_MAX_AGE_MAX_S, tb.PAIR_MAX_CADENCE_S) == (2.5, 60, 750, 300)
    assert tb.PAIR_DRIFT_LIMITS == {AIR: 3.0, "humidity_pct": 10.0, SOIL: 8.0, SUBSTRATE: 8.0}
    assert tb.PAIR_FAST_STEP == {name: limit / 3 for name, limit in tb.PAIR_DRIFT_LIMITS.items()}
    assert tb.PAIR_FAST_STEP[AIR] == 1.0


def test_a_pair_entry_has_the_designed_keys_and_values():
    entry = basic()
    # own 20 + (i%5)*0.1 minus the partner reading one step earlier, 18 + ((i-1)%5)*0.1: +0.1 except -0.4 at i=5, 10
    assert entry == {"offset": 2.1, "n": 13, "partner_value": round(wiggle(13, 18.0), 6), "partners": 1,
                     "partner_device": "p1", "device": "own"}


def test_pair_min_n_is_12_offsets():
    assert basic(count=12) is None  # readings 1..11 have a partner: 11 offsets
    assert basic(count=13)["n"] == 12


def test_a_calibration_restart_needs_12_new_offsets_not_11():
    start = at(3) + timedelta(seconds=15)  # partner readings from index 4 on count, so own readings from index 5 on
    assert basic(count=16, start=start) is None  # own 5..15 against partner 4..14: 11 offsets
    entry = basic(count=17, start=start)
    assert entry is not None and entry["n"] == 12


def test_the_window_bound_is_the_window_start_inclusive():
    own, partners = rows("own", 20, 20.0), rows("p1", 21, 18.0)
    now = current_at(20, 20.0)
    assert pair(own, partners, now, window=11 * 30) is None  # own readings 9..19 are 11 offsets
    assert pair(own, partners, now, window=12 * 30)["n"] == 12  # own readings 8..19


def test_lapse_drops_the_pair_when_the_newest_offset_is_too_old():
    own = rows("own", 14, 20.0) + [{**row, "vetoed_fields": [AIR]} for row in rows("own", 20, 20.0, start=14)]
    partners, now = rows("p1", 21, 18.0), current_at(20, 20.0)
    assert pair(own, partners, now, lapse=210) is not None  # the newest unvetoed own reading is 7 intervals back: 210 s
    assert pair(own, partners, now, lapse=209) is None
    assert pair(own, partners, now) is not None  # no lapse by default


@pytest.mark.parametrize("step, expected", [(300, True), (301, False)])
def test_a_cadence_of_300_s_is_paired_and_301_s_is_not(step, expected):
    own, partners = rows("own", 14, 20.0, step=step), rows("p1", 15, 18.0, step=step)
    entry = pair(own, partners, current_at(14, 20.0, step=step))
    assert (entry is not None) is expected


def test_partner_age_follows_the_own_cadence_two_and_a_half_intervals():
    # 30 s: 75 s. A partner one interval behind the own readings (30 s) is kept, a partner 90 s behind is not.
    own = rows("own", 14, 20.0)
    assert pair(own, rows("p1", 14, 18.0), current_at(14, 20.0)) is not None  # the newest partner reading is 30 s old
    assert pair(own, rows("p1", 12, 18.0), current_at(14, 20.0)) is None  # 90 s old


def test_a_partner_missing_one_packet_keeps_the_pair_missing_three_intervals_drops_it():
    own, now = rows("own", 13, 20.0), current_at(13, 20.0)
    one_missing = [r for r in rows("p1", 13, 18.0) if r["timestamp"] != at(12)]  # latest earlier reading: index 11, 60 s old
    assert pair(own, one_missing, now) is not None
    three_intervals = rows("p1", 11, 18.0)  # latest earlier reading: index 10, 90 s old
    assert pair(own, three_intervals, now) is None


def test_a_partner_reading_at_the_same_sample_time_is_not_used():
    own = rows("own", 14, 20.0)
    partners = rows("p1", 14, 18.0) + [{"device_id": "p1", "timestamp": at(14), AIR: 99.0, "vetoed_fields": []}]
    entry = pair(own, partners, current_at(14, 20.0))
    assert entry["partner_value"] == round(wiggle(13, 18.0), 6)  # index 13, not the same-time 99.0
    only_same_time = [{"device_id": "p1", "timestamp": at(14), AIR: 99.0, "vetoed_fields": []}]
    assert pair(own, only_same_time, current_at(14, 20.0)) is None


def test_a_vetoed_partner_reading_is_not_used():
    own, now = rows("own", 14, 20.0), current_at(14, 20.0)
    partners = rows("p1", 15, 18.0)
    partners[13]["vetoed_fields"] = [AIR]  # the reading just before the current one
    entry = pair(own, partners, now)
    assert entry["partner_value"] == round(wiggle(12, 18.0), 6)  # one interval further back, still fresh enough
    assert pair(own, rows("p1", 15, 18.0, vetoed=[AIR]), now) is None  # every partner reading vetoed
    assert pair(own, rows("p1", 15, 18.0, vetoed=["humidity_pct"]), now) is not None  # another field's veto is not this one's


def test_a_flat_partner_is_skipped_and_a_flat_own_stream_is_not_judged():
    own, now = rows("own", 14, 20.0), current_at(14, 20.0)
    flat = [{"device_id": "p1", "timestamp": at(i), AIR: 18.0, "vetoed_fields": []} for i in range(15)]
    assert pair(own, flat, now) is None
    entry = pair(own, [*flat, *rows("p2", 15, 18.0)], now)
    assert (entry["partners"], entry["partner_device"]) == (1, "p2")
    short = flat[:11] + [{**flat[11], AIR: 18.5}, *flat[12:]]  # not flat in the window
    assert pair(own, short, now) is not None
    flat_own = [{"device_id": "own", "timestamp": at(i), AIR: 20.0, "vetoed_fields": []} for i in range(14)]
    assert pair(flat_own, rows("p1", 15, 18.0), {"device_id": "own", "timestamp": at(14), AIR: 20.0}) is None


def test_flat_needs_pair_min_n_readings_in_the_window():
    window = 12 * 30  # own readings 8..19 are the window of the reading at index 20
    own, now = rows("own", 20, 20.0), current_at(20, 20.0)
    p2 = rows("p2", 21, 19.0)

    def flat(skip=()):
        return [{"device_id": "p1", "timestamp": at(i), AIR: 18.0, "vetoed_fields": []} for i in range(7, 20) if i not in skip]

    twelve = pair(own, [*flat(), *p2], now, window=window)  # 8..19 identical: 12 readings, flat
    assert (twelve["partners"], twelve["partner_device"]) == (1, "p2")
    eleven = pair(own, [*flat(skip=(12,)), *p2], now, window=window)  # 11 identical readings in the window: not flat
    assert eleven["partners"] == 2 and eleven["n"] == 12


def test_the_alias_pair_matches_both_ways():
    for own_name, partner_name in ((SOIL, SUBSTRATE), (SUBSTRATE, SOIL)):
        entry = pair(rows("own", 14, 40.0, field=own_name), rows("p1", 15, 38.0, field=partner_name),
                     current_at(14, 40.0, field=own_name), field=own_name)
        assert entry is not None and entry["partner_device"] == "p1"
        assert entry["partner_value"] == round(wiggle(13, 38.0), 6)


def test_a_device_sending_both_moisture_names_is_judged_once_under_the_first_name():
    own = [{**row, SUBSTRATE: row[SOIL]} for row in rows("own", 14, 40.0, field=SOIL)]
    partners = rows("p1", 15, 38.0, field=SUBSTRATE)
    now = {"device_id": "own", "timestamp": at(14), SOIL: wiggle(14, 40.0), SUBSTRATE: wiggle(14, 40.0)}
    assert pair(own, partners, now, field=SOIL) is not None
    assert pair(own, partners, now, field=SUBSTRATE) is None
    only_substrate = {"device_id": "own", "timestamp": at(14), SUBSTRATE: wiggle(14, 40.0)}
    assert pair([{**r, SOIL: None} for r in own], partners, only_substrate, field=SUBSTRATE) is not None
    as_partner = [{**r, SOIL: r[SUBSTRATE] + 5.0} for r in partners]  # its value under the own reading's name wins
    assert pair(own, as_partner, now, field=SOIL)["partner_value"] == round(wiggle(13, 38.0) + 5.0, 6)


def test_a_partner_veto_under_the_other_moisture_name_counts():
    own, now = rows("own", 14, 40.0, field=SOIL), current_at(14, 40.0, field=SOIL)
    partners = rows("p1", 15, 38.0, field=SUBSTRATE, vetoed=[SOIL])
    assert pair(own, partners, now, field=SOIL) is None


def test_three_devices_median_of_an_even_count_is_the_mean_of_the_middle_two():
    own, now = rows("own", 14, 20.0), current_at(14, 20.0)
    two = [*rows("p1", 15, 18.0), *rows("p2", 15, 19.0)]
    entry = pair(own, two, now)
    assert entry["partners"] == 2 and entry["partner_device"] is None
    assert entry["partner_value"] == round((wiggle(13, 18.0) + wiggle(13, 19.0)) / 2, 6)
    three = [*two, *rows("p3", 15, 25.0)]
    assert pair(own, three, now)["partner_value"] == round(wiggle(13, 19.0), 6)  # the middle one of three
    four = [*three, *rows("p4", 15, 30.0)]
    assert pair(own, four, now)["partner_value"] == round((wiggle(13, 19.0) + wiggle(13, 25.0)) / 2, 6)


def test_at_most_eight_partners_the_first_by_device_id_that_have_a_reading():
    own, now = rows("own", 40, 20.0), current_at(40, 20.0)
    partners = [row for n in range(10) for row in rows(f"p{n}", 41, 10.0 + n)]
    partners += rows("p0x", 5, 500.0)  # sorts between p0 and p1 but is silent now: never takes a slot
    entry = pair(own, partners, now)
    assert entry["partners"] == 8 and entry["n"] == 33  # offsets 7..39 are against p0..p7 (p0x served 1..6)
    # p0..p7 give 10..17 (+ the same wobble): the median of eight is the mean of the 4th and 5th
    assert entry["partner_value"] == round((wiggle(39, 13.0) + wiggle(39, 14.0)) / 2, 6)


def test_a_partner_going_quiet_changes_the_set_and_old_set_offsets_are_not_used():
    own, now = rows("own", 40, 20.0), current_at(40, 20.0)
    quiet = [*rows("p1", 41, 18.0), *rows("p2", 15, 19.0)]  # p2's last reading is index 14
    entry = pair(own, quiet, now)
    # (p1, p2) gives offsets for own 1..16 only (p2 14 is 60 s old at 16, 90 s at 17); (p1,) for 17..39: 23 offsets
    assert (entry["partners"], entry["partner_device"], entry["n"]) == (1, "p1", 23)
    short = pair(rows("own", 20, 20.0), [*rows("p1", 21, 18.0), *rows("p2", 15, 19.0)], current_at(20, 20.0))
    assert short is None  # only (p1,) offsets 17..19 are against the new set: too few
    both = pair(own, [*rows("p1", 41, 18.0), *rows("p2", 41, 19.0)], now)
    assert both["n"] == 39 and both["partners"] == 2


def test_the_partner_set_comes_back_with_the_partner_and_starts_collecting_afresh():
    own, now = rows("own", 40, 20.0), current_at(40, 20.0)
    p2 = [r for r in rows("p2", 40, 19.0) if not 10 <= (r["timestamp"] - BASE).total_seconds() / 30 < 25]
    entry = pair(own, [*rows("p1", 40, 18.0), *p2], now)
    # (p1, p2) offsets: own 1..11 (p2 reading 9 is 60 s old at 11) and 26..39; own 12..25 are against (p1,) alone
    assert entry["partners"] == 2 and entry["n"] == 25


@pytest.mark.parametrize("step_s", [30, 300])
def test_a_shared_step_of_one_and_a_half_limits_flags_neither_device(step_s):
    """Both devices jump by 1.5x the limit on the same tick (aligned clocks): the reading with the step is not judged
    on either device, and the next reading is judged with a normal offset."""
    jump = 1.5 * tb.PAIR_DRIFT_LIMITS[AIR]

    def series(device, base, upto, first=0):
        return [{"device_id": device, "timestamp": at(i, step_s), AIR: wiggle(i, base) + (jump if i >= 13 else 0.0),
                 "vetoed_fields": []} for i in range(first, upto)]

    for own_device, own_base, other, other_base in (("a", 20.0, "b", 18.0), ("b", 18.0, "a", 20.0)):
        at_step = pair(series(own_device, own_base, 13), series(other, other_base, 13),
                       {"device_id": own_device, "timestamp": at(13, step_s), AIR: wiggle(13, own_base) + jump})
        assert at_step is None
        after = pair(series(own_device, own_base, 14), series(other, other_base, 14),
                     {"device_id": own_device, "timestamp": at(14, step_s), AIR: wiggle(14, own_base) + jump})
        assert after is not None
        moved = (wiggle(14, own_base) + jump - after["partner_value"]) - after["offset"]
        assert abs(moved) < tb.PAIR_DRIFT_LIMITS[AIR] / 3  # the shared step is not a move of the difference


def test_an_own_step_just_under_the_fast_limit_is_judged_and_one_at_it_is_not():
    own = rows("own", 13, 20.0) + [{"device_id": "own", "timestamp": at(13), AIR: 20.0, "vetoed_fields": []}]
    partners = rows("p1", 15, 18.0)
    just_under = {"device_id": "own", "timestamp": at(14), AIR: 20.0 + 0.999}
    assert abs(just_under[AIR] - 20.0) < tb.PAIR_FAST_STEP[AIR]
    assert pair(own, partners, just_under) is not None
    at_limit = {"device_id": "own", "timestamp": at(14), AIR: 21.0}
    assert pair(own, partners, at_limit) is None
    down = {"device_id": "own", "timestamp": at(14), AIR: 19.0}
    assert pair(own, partners, down) is None  # a fall counts the same


def test_the_fast_step_is_measured_against_the_previous_stored_reading_even_when_vetoed():
    own = rows("own", 13, 20.0) + [{"device_id": "own", "timestamp": at(13), AIR: 20.0, "vetoed_fields": [AIR]}]
    assert pair(own, rows("p1", 15, 18.0), {"device_id": "own", "timestamp": at(14), AIR: 21.0}) is None


def test_the_fast_step_is_a_third_of_each_limit():
    for field, limit in tb.PAIR_DRIFT_LIMITS.items():
        step = limit / 3
        own = rows("own", 13, 40.0, field=field) + [{"device_id": "own", "timestamp": at(13), field: 40.0, "vetoed_fields": []}]
        partners = rows("p1", 15, 38.0, field=field)
        at_limit = 40.0 + step
        if at_limit - 40.0 < step:
            at_limit = math.nextafter(at_limit, math.inf)  # float rounding must not put "at the limit" just under it
        assert pair(own, partners, {"device_id": "own", "timestamp": at(14), field: 40.0 + step * 0.99}, field=field) is not None
        assert pair(own, partners, {"device_id": "own", "timestamp": at(14), field: at_limit}, field=field) is None


def test_offsets_are_not_filtered_by_the_fast_step():
    # a one-reading shared step inside the window still gives an offset (the median ignores it)
    own = [{**row, AIR: row[AIR] + (6.0 if row["timestamp"] == at(6) else 0.0)} for row in rows("own", 14, 20.0)]
    entry = pair(own, rows("p1", 15, 18.0), current_at(14, 20.0))
    assert entry["n"] == 13 and entry["offset"] == 2.1


def test_a_dropped_or_future_row_is_not_history_and_unreadable_times_are_skipped():
    own = rows("own", 14, 20.0) + [{"device_id": "own", "timestamp": "not a time", AIR: 1.0}]
    partners = rows("p1", 15, 18.0) + [{"device_id": "p1", "timestamp": at(40), AIR: 1.0, "vetoed_fields": []}]
    assert basic()["n"] == pair(own, partners, current_at(14, 20.0))["n"]


def test_iso_text_timestamps_are_accepted():
    own = [{**r, "timestamp": r["timestamp"].isoformat().replace("+00:00", "Z")} for r in rows("own", 14, 20.0)]
    partners = [{**r, "timestamp": r["timestamp"].isoformat()} for r in rows("p1", 15, 18.0)]
    now = {**current_at(14, 20.0), "timestamp": at(14).isoformat()}
    assert pair(own, partners, now) == pair(rows("own", 14, 20.0), rows("p1", 15, 18.0), current_at(14, 20.0))


def test_duplicate_sample_times_of_one_partner_last_row_wins_and_the_input_is_not_changed():
    own, now = rows("own", 14, 20.0), current_at(14, 20.0)
    partners = rows("p1", 15, 18.0)
    older = copy.deepcopy(partners[13])
    older[AIR] = 77.0
    entry = pair(own, [*partners[:13], older, partners[13], partners[14]], now)
    assert entry["partner_value"] == round(wiggle(13, 18.0), 6)
    flipped = pair(own, [*partners[:13], partners[13], older, partners[14]], now)
    assert flipped["partner_value"] == 77.0
    before = copy.deepcopy((own, partners))
    pair(own, partners, now)
    assert (own, partners) == before


def test_no_other_device_or_only_the_own_device_gives_nothing():
    own, now = rows("own", 14, 20.0), current_at(14, 20.0)
    assert pair(own, [], now) is None
    assert pair(own, rows("own", 15, 18.0), now) is None  # the own device is never its own partner
    assert pair(own, rows("p1", 15, 18.0), {**now, AIR: None}) is None
    assert pair(own, rows("p1", 15, 18.0), now, field="substrate_temperature_c") is None


def test_pair_start_time_compares_parsed_times_and_covers_both_moisture_names():
    now = datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc)
    calibrations = [{"measurement": AIR, "performed_at": "2026-06-01T12:30:00+02:00"},  # 10:30 UTC, but sorts last as text
                    {"measurement": AIR, "performed_at": "2026-06-01T10:15:00+00:00"},
                    {"measurement": AIR, "performed_at": "2026-06-01T11:30:00+00:00"},  # after the reading: not applied
                    {"measurement": SOIL, "performed_at": "2026-06-01T09:00:00Z"},
                    {"measurement": "ph", "performed_at": "2026-06-01T10:59:00Z"}]
    assert tb.pair_start_time(calibrations, AIR, now) == datetime(2026, 6, 1, 10, 30, tzinfo=timezone.utc)
    assert tb.pair_start_time(calibrations, SOIL, now) == tb.pair_start_time(calibrations, SUBSTRATE, now)
    assert tb.pair_start_time(calibrations, "humidity_pct", now) is None
    assert tb.pair_start_time([], AIR, now) is None


def test_the_pair_check_costs_little_over_a_full_window_of_rows():
    import time
    own, partners = rows("own", 240, 20.0), [*rows("p1", 300, 18.0), *rows("p2", 300, 19.0)]
    now = current_at(240, 20.0)
    started = time.perf_counter()
    for _ in range(20):
        assert pair(own, partners, now) is not None
    assert (time.perf_counter() - started) / 20 < 0.05  # well under 50 ms per call (about 3 ms on a laptop)


# --- the store ------------------------------------------------------------------------------------------------------

DAY = timedelta(days=1)
T0 = datetime.now(timezone.utc).replace(microsecond=0) - 20 * DAY


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
    monkeypatch.setattr(event_store, "_db_path", tmp_path / "pair.db")
    SensorEventStore(db_path=event_store._db_path)


def stamp(i, step=30):
    return T0 + timedelta(seconds=step * i)


def packet(device, i, zone="a", **fields):
    fields = fields or {AIR: 20.0}  # a packet needs a reading
    return SensorEvent.model_validate({"device_id": device, "farm_id": "farm", "zone_id": zone,
                                       "timestamp": stamp(i).isoformat(), **fields})


def store_packet(clock, device, i, zone="a", received=None, judge=None, **fields):
    """Store a live full packet; `judge` (a list of vetoed fields) also records its trust row."""
    clock.now = received or stamp(i)
    event = packet(device, i, zone, **fields)
    assert event_store.add(event)
    if judge is not None:
        event_store.add_trust(event, "trusted", judge)
    return event


def test_zone_pair_devices_are_the_other_devices_that_carried_the_fields(clock):
    store_packet(clock, "a1", 0, **{AIR: 20.0})
    store_packet(clock, "a2", 1, **{AIR: 20.0, "humidity_pct": 50.0})
    store_packet(clock, "a3", 2, ph=6.0)
    store_packet(clock, "z1", 3, zone="other", **{AIR: 20.0})
    event = store_packet(clock, "a1", 4, **{AIR: 20.0})
    assert event_store.zone_pair_devices(event, [AIR]) == ["a2"]
    assert event_store.zone_pair_devices(event, ["humidity_pct", AIR]) == ["a2"]
    assert event_store.zone_pair_devices(event, [SOIL]) == []
    assert event_store.zone_pair_devices(event, []) == []


def test_zone_pair_devices_use_the_event_time_and_the_retention_days_like_device_fields_for(clock):
    store_packet(clock, "a2", 0, **{AIR: 20.0})
    old = store_packet(clock, "a1", -3, received=T0 - timedelta(seconds=10), **{AIR: 20.0})  # received before a2 was first seen
    assert event_store.zone_pair_devices(old, [AIR]) == []
    clock.now = T0 + timedelta(days=settings.retention_days + 1)
    late = packet("a1", 0)
    late.received_at = clock.now  # a2 was last seen more than the retention days before this reading
    assert event_store.zone_pair_devices(late, [AIR]) == []
    assert event_store.device_fields_for(late) is None
    late.received_at = T0 + timedelta(days=settings.retention_days - 1)
    assert event_store.zone_pair_devices(late, [AIR]) == ["a2"]


def test_zone_pair_devices_are_empty_when_the_multi_device_switch_is_off(clock, monkeypatch):
    store_packet(clock, "a2", 0, **{AIR: 20.0})
    event = store_packet(clock, "a1", 1, **{AIR: 20.0})
    assert event_store.zone_pair_devices(event, [AIR]) == ["a2"]
    monkeypatch.setattr(settings, "multi_device_zones", False)
    assert event_store.zone_pair_devices(event, [AIR]) == []


def test_zone_partner_history_is_judged_rows_in_the_window_oldest_first(clock):
    for i in range(10):
        store_packet(clock, "a2", i, judge=[] if i != 4 else [AIR], **{AIR: 18.0 + i, "humidity_pct": 50.0})
    store_packet(clock, "a2", 10, **{AIR: 79.0})  # never judged
    store_packet(clock, "a2", 11, judge=[], ph=6.0)  # judged, but none of the asked fields
    store_packet(clock, "a3", 5, judge=[], **{AIR: 7.0})  # another device, not asked for
    store_packet(clock, "a2", 3, zone="other", judge=[], **{AIR: 5.0})
    event = packet("a1", 8)
    history = event_store.zone_partner_history(event, ["a2"], [AIR], stamp(2))
    assert [(r["device_id"], r["timestamp"], r[AIR], r["vetoed_fields"]) for r in history] == \
        [("a2", stamp(i), 18.0 + i, [AIR] if i == 4 else []) for i in range(2, 8)]  # [since, the event's time)
    assert all(r["timestamp"].tzinfo is not None and "humidity_pct" not in r for r in history)
    both = event_store.zone_partner_history(event, ["a2", "a3"], [AIR], stamp(2))
    assert {r["device_id"] for r in both} == {"a2", "a3"}
    assert event_store.zone_partner_history(event, [], [AIR], stamp(2)) == []


def test_zone_partner_history_orders_duplicate_sample_times_newest_stored_last(clock):
    store_packet(clock, "a2", 5, judge=[], **{AIR: 18.0})
    clock.now = stamp(5) + timedelta(seconds=1)
    again = packet("a2", 5, **{AIR: 19.0})  # a different payload at the same sample time
    assert event_store.add(again)
    history = event_store.zone_partner_history(packet("a1", 8), ["a2"], [AIR], stamp(0))
    assert [r[AIR] for r in history] == [18.0, 19.0]


def test_zone_partner_history_caps_the_rows_per_partner_at_the_scan_limit(clock, monkeypatch):
    monkeypatch.setattr(settings, "trust_baseline_scan_limit", 10)
    for i in range(30):
        store_packet(clock, "a2", i, judge=[], **{AIR: 18.0 + i})
        store_packet(clock, "a3", i, judge=[], **{AIR: 30.0 + i})
    history = event_store.zone_partner_history(packet("a1", 40), ["a2", "a3"], [AIR], stamp(0))
    for device in ("a2", "a3"):
        assert [r["timestamp"] for r in history if r["device_id"] == device] == [stamp(i) for i in range(20, 30)]


def test_zone_partner_history_uses_the_sample_time_index(clock):
    store_packet(clock, "a2", 0, judge=[], **{AIR: 18.0})
    with event_store._connect() as db:
        plan = " ".join(str(tuple(r)) for r in db.execute(
            """EXPLAIN QUERY PLAN SELECT e.payload FROM sensor_events e WHERE e.farm_id=? AND e.zone_id=? AND e.device_id=?
            AND e.sample_epoch >= ? AND e.sample_epoch < ? ORDER BY e.sample_epoch DESC, e.id DESC LIMIT ?""",
            ("farm", "a", "a2", 0.0, 1.0, 10)))
    assert "USING INDEX sensor_events_sample_" in plan  # per-device (farm, zone, device, sample_epoch) or the zone-wide one


def calibrate(clock, device, measurement, performed_at, zone="a"):
    clock.now = max(clock.now, performed_at)
    return event_store.add_calibration(CalibrationEvent.model_validate({
        "device_id": device, "farm_id": "farm", "zone_id": zone, "sensor_id": f"{device}-s", "measurement": measurement,
        "method": "reference_meter", "points": [{"reference": 20.0, "raw": 20.5}], "performed_at": performed_at.isoformat()}))


def test_zone_calibrations_are_the_zones_newest_on_any_device_and_not_other_zones(clock):
    calibrate(clock, "a1", AIR, stamp(1))
    calibrate(clock, "a2", "humidity_pct", stamp(2))
    calibrate(clock, "z1", AIR, stamp(3), zone="other")
    items = event_store.zone_calibrations("farm", "a")
    assert sorted((i["measurement"], i["performed_at"]) for i in items) == sorted(
        [(AIR, event_store.stream_calibrations(packet("a1", 0))[0]["performed_at"]),
         ("humidity_pct", event_store.stream_calibrations(packet("a2", 0))[0]["performed_at"])])
    assert set(items[0]) == {"measurement", "performed_at"}
    assert event_store.zone_calibrations("farm", "nowhere") == []
    assert len(event_store.zone_calibrations("farm", "a", limit=1)) == 1


def test_zone_calibrations_are_capped_at_the_newest_200(clock):
    for i in range(205):
        calibrate(clock, f"d{i % 2}", AIR, T0 + timedelta(minutes=i))
    items = event_store.zone_calibrations("farm", "a")
    assert len(items) == 200
    performed = sorted(tb.parse_time(i["performed_at"]) for i in items)
    assert performed[0] == T0 + timedelta(minutes=5) and performed[-1] == T0 + timedelta(minutes=204)


def test_a_calibration_with_an_offset_time_sorts_by_its_parsed_time_through_the_store(clock):
    # the schema converts performed_at to UTC when it is stored; a legacy row can still hold an offset time
    calibrate(clock, "a1", AIR, T0 + timedelta(hours=3))
    with event_store._connect() as db:
        row = db.execute("SELECT id, payload FROM calibration_events").fetchone()
        payload = json.loads(row["payload"])
        payload["performed_at"] = (T0 + timedelta(hours=3)).astimezone(timezone(timedelta(hours=2))).isoformat()
        db.execute("UPDATE calibration_events SET payload=? WHERE id=?", (json.dumps(payload), row["id"]))
    calibrate(clock, "a2", AIR, T0 + timedelta(hours=2, minutes=30))
    items = event_store.zone_calibrations("farm", "a")
    start = tb.pair_start_time(items, AIR, T0 + timedelta(hours=4))
    assert start == T0 + timedelta(hours=3)  # 05:00+02:00 is later than 02:30Z, whatever the text order


# --- the feed -------------------------------------------------------------------------------------------------------

@pytest.fixture
def zone(clock, monkeypatch):
    """A feed with a recording router: every evaluation body is kept; `veto` is a {(device, index): [fields]} map of
    what the router vetoes. `send` stores one live packet at tick i and judges it (unless told not to)."""
    monkeypatch.setattr(settings, "model_router_url", "http://router.test")
    monkeypatch.setattr(settings, "automation_engine_url", "http://automation.test")
    harness = SimpleNamespace(bodies=[], veto={}, feed=OutcomeFeed(event_store, queue_size=5))

    def post(base_url, path, body):
        if path != "/v1/pipeline/evaluate":
            return {}
        harness.bodies.append(body)
        index = round((SensorEvent.model_validate(body["sensor"]).timestamp - T0).total_seconds() / 30)
        return {"trust_gate": {"trust_verdict": "trusted", "vetoed_fields": harness.veto.get((body["sensor"]["device_id"], index), [])}}

    def send(device, i, judge=True, **fields):
        clock.now = stamp(i)
        event = packet(device, i, **fields)
        assert event_store.add(event)
        if judge:
            harness.feed._process(event)
            return harness.bodies[-1]
        return None

    monkeypatch.setattr(feed_module, "_post", post)
    harness.send = send
    return harness


def two_devices(zone, ticks, a_base=20.0, b_base=18.0, field=AIR, b_field=None, judge_b=True, start=0):
    last = None
    for i in range(start, ticks):
        last = zone.send("A", i, **{field: wiggle(i, a_base)})
        zone.send("B", i, judge=judge_b, **{b_field or field: wiggle(i, b_base)})
    return last


def entry_of(body, field=AIR):
    return (body.get("stream_baseline") or {}).get(field)


def test_the_feed_adds_a_pair_entry_in_a_two_device_zone(zone):
    body = two_devices(zone, 14)  # A at tick 13: own offsets from ticks 1..12 against B's earlier readings
    pair_entry = entry_of(body)["pair"]
    assert pair_entry == {"offset": 2.1, "n": 12, "partner_value": round(wiggle(12, 18.0), 6), "partners": 1,
                          "partner_device": "B", "device": "A"}
    earlier = [b for b in zone.bodies if b["sensor"]["device_id"] == "A"][-2]
    assert "pair" not in entry_of(earlier)  # 11 offsets one tick before


def test_the_feeds_pair_entry_equals_the_pure_functions_for_the_stored_rows(zone):
    two_devices(zone, 20)
    event = packet("A", 20, **{AIR: wiggle(20, 20.0)})
    event.received_at = stamp(20)
    expected = tb.pair_reference(event_store.stream_history(event, 5000),
                                 event_store.zone_partner_history(event, ["B"], [AIR], stamp(0)), AIR, None,
                                 {"device_id": "A", "timestamp": event.timestamp, AIR: event.air_temperature_c}, WINDOW)
    zone.send("A", 20, **{AIR: wiggle(20, 20.0)})
    assert entry_of(zone.bodies[-1])["pair"] == expected and expected["n"] == 19


def test_a_partner_reading_without_a_trust_row_is_not_used(zone):
    body = two_devices(zone, 14, judge_b=False)
    assert "pair" not in entry_of(body)  # B's readings are stored but none was judged


def test_one_unjudged_partner_reading_is_skipped_and_the_next_reading_uses_it(zone):
    for i in range(14):
        zone.send("A", i, **{AIR: wiggle(i, 20.0)})
        zone.send("B", i, judge=(i != 12), **{AIR: wiggle(i, 18.0)})
    body = zone.send("A", 14, **{AIR: wiggle(14, 20.0)})
    assert entry_of(body)["pair"]["partner_value"] == round(wiggle(13, 18.0), 6)
    # the reading at tick 13: B's tick 12 was unjudged, so its partner was B at tick 11
    at_13 = [b for b in zone.bodies if b["sensor"]["device_id"] == "A"][13]
    assert entry_of(at_13)["pair"]["partner_value"] == round(wiggle(11, 18.0), 6)


def test_a_vetoed_partner_reading_is_not_used(zone):
    zone.veto[("B", 12)] = [AIR]
    for i in range(14):
        zone.send("A", i, **{AIR: wiggle(i, 20.0)})
        zone.send("B", i, **{AIR: wiggle(i, 18.0)})
    at_13 = [b for b in zone.bodies if b["sensor"]["device_id"] == "A"][13]
    assert entry_of(at_13)["pair"]["partner_value"] == round(wiggle(11, 18.0), 6)


def test_the_alias_pair_matches_through_the_feed(zone):
    body = two_devices(zone, 14, a_base=40.0, b_base=38.0, field=SOIL, b_field=SUBSTRATE)
    assert entry_of(body, SOIL)["pair"]["partner_device"] == "B"
    b_body = [b for b in zone.bodies if b["sensor"]["device_id"] == "B"][-1]
    assert entry_of(b_body, SUBSTRATE)["pair"]["partner_device"] == "A"


@pytest.mark.parametrize("calibrated, other", [("A", "B"), ("B", "A")])
def test_calibrating_either_probe_restarts_the_pair_and_not_the_others_own_reference(zone, clock, calibrated, other):
    two_devices(zone, 14)
    calibrate(clock, calibrated, AIR, stamp(13) + timedelta(seconds=15))
    bodies = {"A": zone.send("A", 14, **{AIR: wiggle(14, 20.0)}), "B": zone.send("B", 14, **{AIR: wiggle(14, 18.0)})}
    assert AIR not in bodies[calibrated].get("stream_baseline", {})  # its own reference restarts: no readings after the calibration
    assert entry_of(bodies[other])["n"] == 14 and "pair" not in entry_of(bodies[other])  # the other keeps its own reference
    # offsets after the calibration are own readings 15..k-1 (each against the other probe's reading from 14 on)
    for i in range(15, 27):
        for device, base in (("A", 20.0), ("B", 18.0)):
            body = zone.send(device, i, **{AIR: wiggle(i, base)})
            assert "pair" not in (body.get("stream_baseline", {}).get(AIR) or {}), (device, i)  # 11 offsets at i = 26
    for device, base in (("A", 20.0), ("B", 18.0)):
        assert entry_of(zone.send(device, 27, **{AIR: wiggle(27, base)}))["pair"]["n"] == 12


def test_three_devices_a_partner_going_quiet_changes_the_set_through_the_feed(zone):
    last = None
    for i in range(40):
        last = zone.send("A", i, **{AIR: wiggle(i, 20.0)})
        zone.send("B", i, **{AIR: wiggle(i, 18.0)})
        if i <= 14:
            zone.send("C", i, **{AIR: wiggle(i, 19.0)})
    pair_entry = entry_of(last)["pair"]
    assert (pair_entry["partners"], pair_entry["partner_device"], pair_entry["n"]) == (1, "B", 22)
    at_13 = [b for b in zone.bodies if b["sensor"]["device_id"] == "A"][13]
    assert entry_of(at_13)["pair"]["partners"] == 2  # both partners while C was reporting


def run_single(zone, ticks=20):
    return [zone.send("A", i, **{AIR: wiggle(i, 20.0), "humidity_pct": wiggle(i, 60.0)}) for i in range(ticks)]


def forbid_partner_queries(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("a partner query ran")
    for name in ("zone_pair_devices", "zone_partner_history", "zone_calibrations"):
        monkeypatch.setattr(event_store, name, refuse)


def test_a_one_device_zone_sends_the_same_request_and_runs_no_partner_query(zone, monkeypatch):
    forbid_partner_queries(monkeypatch)
    bodies = run_single(zone)
    assert all("device_fields" not in b and "pair" not in json.dumps(b) for b in bodies)
    assert all(list(b) == ["scenario_id", "farm_context", "sensor", "history", "stream_baseline", "proposed_command", "actor", "mode"]
               or list(b) == ["scenario_id", "farm_context", "sensor", "history", "proposed_command", "actor", "mode"] for b in bodies)
    # the same bytes with the switch off (a fresh store, the same readings)
    event_store.clear()
    zone.bodies.clear()
    monkeypatch.setattr(settings, "pair_check", False)
    again = run_single(zone)
    assert [json.dumps(b, sort_keys=True) for b in bodies] == [json.dumps(b, sort_keys=True) for b in again]


def test_pair_check_off_gives_no_pair_entry_and_no_partner_query(zone, monkeypatch):
    monkeypatch.setattr(settings, "pair_check", False)
    forbid_partner_queries(monkeypatch)
    body = two_devices(zone, 20)
    assert "pair" not in json.dumps(zone.bodies)
    assert entry_of(body) is not None and body["device_fields"]  # the multi-device request is otherwise as before


def test_multi_device_zones_off_gives_no_pair_entry_and_no_partner_query(zone, monkeypatch):
    monkeypatch.setattr(settings, "multi_device_zones", False)
    forbid_partner_queries(monkeypatch)
    body = two_devices(zone, 20)
    assert "pair" not in json.dumps(zone.bodies) and "device_fields" not in body


def test_a_two_device_zone_with_pair_check_on_differs_from_off_only_by_the_pair_entries(zone, monkeypatch):
    two_devices(zone, 20)
    on = copy.deepcopy(zone.bodies)
    event_store.clear()
    zone.bodies.clear()
    monkeypatch.setattr(settings, "pair_check", False)
    two_devices(zone, 20)
    stripped = copy.deepcopy(on)
    for body in stripped:
        for item in (body.get("stream_baseline") or {}).values():
            item.pop("pair", None)
    assert [json.dumps(b, sort_keys=True) for b in stripped] == [json.dumps(b, sort_keys=True) for b in zone.bodies]
    assert any("pair" in json.dumps(b) for b in on)


def test_the_feed_reads_the_stream_history_once_and_does_not_query_partners_without_a_field(zone, monkeypatch):
    calls = []
    real = event_store.stream_history
    monkeypatch.setattr(event_store, "stream_history", lambda *a, **k: calls.append(1) or real(*a, **k))
    zone.send("A", 0, **{AIR: 20.0})
    assert len(calls) == 1
    # a reading with no pair field of its own: no partner query even in a multi-device zone
    zone.send("B", 0, **{AIR: 18.0})
    forbid_partner_queries(monkeypatch)
    for i in range(1, 10):
        zone.send("A", i, ph=wiggle(i, 6.0), ec_ms_cm=wiggle(i, 2.0))


# --- the fast path: pre-built series give the result the rows give ---------------------------------------------------

def series_of(items, field):
    """The series form `pair_reference` takes, built here by hand: one entry per sample time (the last row with a value
    wins), oldest first, as parallel lists."""
    latest = {}
    for row in items:
        entry = tb.pair_row_entry(row, field)
        if entry is not None:
            latest[row["timestamp"]] = entry
    ordered = sorted(latest.items())
    return ([t for t, _ in ordered], [t.timestamp() for t, _ in ordered], [e[0] for _, e in ordered],
            [e[1] for _, e in ordered])


def test_pair_row_entry_is_the_value_under_the_name_or_its_alias_and_whether_it_was_vetoed():
    assert tb.pair_row_entry({SOIL: 40.0}, SOIL) == (40.0, False)
    assert tb.pair_row_entry({SUBSTRATE: 41}, SOIL) == (41.0, False)  # under the alias
    assert tb.pair_row_entry({SOIL: 40.0, SUBSTRATE: 41.0, "vetoed_fields": [SUBSTRATE]}, SOIL) == (40.0, True)
    assert tb.pair_row_entry({SOIL: float("nan")}, SOIL) is None and tb.pair_row_entry({SOIL: True}, SOIL) is None
    assert tb.pair_row_entry({AIR: 20.0, "vetoed_fields": [AIR]}, AIR) == (20.0, True)
    assert tb.pair_row_entry({AIR: 20.0}, SOIL) is None


@pytest.mark.parametrize("seed", range(12))
def test_series_and_rows_give_the_same_pair_entry_on_random_zones(seed):
    """Random streams with a missing field, duplicate sample times, vetoed readings, jitter, the other name of the
    field, a flat partner, a late partner, later readings than the current one, a pair start and a lapse: the fast path
    (series) returns exactly what the row path returns, `None` included."""
    import random
    rng = random.Random(seed)
    judged = 0
    for case in range(100):
        field = rng.choice([AIR, SOIL, SUBSTRATE])
        other = {SOIL: SUBSTRATE, SUBSTRATE: SOIL}.get(field)
        step = rng.choice([30, 30, 30, 60, 300, 400])
        count = rng.choice([8, 20, 40, 60, 260])

        def make(device, flat=False):
            out = []
            for i in range(count + rng.choice([0, 3])):
                stamp = at(i, step) + timedelta(seconds=rng.choice([0, 0, 0, 1, -1]))
                value = 50.0 if flat else wiggle(i, 20.0 + rng.choice([0, 0, 0, 0.5]), 0.3)
                row = {"device_id": device, "timestamp": stamp, "vetoed_fields": []}
                if rng.random() < 0.9:
                    row[other if other is not None and rng.random() < 0.3 else field] = value
                if rng.random() < 0.15:
                    row["vetoed_fields"] = [field]
                out.append(row)
                if rng.random() < 0.05:
                    out.append({**row, "timestamp": stamp, "vetoed_fields": []})  # the same sample time again
            return out

        own = make("own")
        partners = make("p1") + make("p2", flat=rng.random() < 0.2) + make("p3")[: rng.choice([0, 5, 60])]
        if rng.random() < 0.5:
            rng.shuffle(partners)  # any order
        elif rng.random() < 0.5:
            partners = [r for r in partners if r["device_id"] != "p3"]
        now_index = rng.choice([count - 1, count, count + 2])
        current = {"device_id": "own", "timestamp": at(now_index, step), field: wiggle(now_index, 20.0, 0.3)}
        if other is not None and rng.random() < 0.2:
            current[other] = current[field]
        start = rng.choice([None, None, at(rng.randrange(0, count), step)])
        lapse = rng.choice([None, None, 120.0])
        by_row = tb.pair_reference(own, partners, field, start, current, WINDOW, lapse)
        devices = {}
        for row in partners:
            devices.setdefault(row["device_id"], []).append(row)
        by_series = tb.pair_reference(
            (), (), field, start, current, WINDOW, lapse, own_series=series_of(own, field),
            partner_series={device: series_of(items, field) for device, items in devices.items()})
        assert by_series == by_row, (seed, case)
        judged += by_row is not None
    assert judged >= 15  # the draw does reach a judgement


def test_series_given_with_the_own_device_among_the_partners_leaves_it_out():
    own, partner = rows("own", 20, 20.0), rows("p1", 21, 18.0)
    current = current_at(20, 20.0)
    expected = pair(own, partner, current)
    assert expected is not None
    got = tb.pair_reference((), (), AIR, None, current, WINDOW, None, own_series=series_of(own, AIR),
                            partner_series={"own": series_of(own, AIR), "p1": series_of(partner, AIR)})
    assert got == expected
