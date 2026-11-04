"""Sticky trusted reference for one sensor stream. Pure and stdlib only (no pydantic, no app imports).

The model-router's temporal sensor checks only remember the last 11 packets, so a step or a frozen
probe becomes the "normal" within minutes and the flag stops while the fault is still there. Core
keeps a longer memory per stream and field instead:

  * the median of the readings in which that field was NOT vetoed (a vetoed reading never moves the
    reference, so a fault cannot teach it the wrong level),
  * and when the value last changed (the start of the current run of identical readings), counted over
    ALL stored readings, vetoed or not.

Core sends both with each evaluation as `stream_baseline`; the router flags a reading that differs from
the trusted median by the drift threshold, or a value that has not changed for too long. A calibration
for the field resets the reference: only readings from the calibration on count. Without one, a real
step stays flagged ("can't confirm") until a person confirms it, however long that takes: the window is
anchored at the newest TRUSTED reading, not at "now", so a probe broken for hours is still judged against
the readings from before it broke. A lapse (`max_age_s`) is opt-in.

Optional extras per field, so the router can judge a stream by its own habits:

  * `last_value` / `last_at`: the newest trusted reading. A sudden step is judged against it, and it stays
    put while the new level is vetoed, so a step is flagged for as long as it is physically impossible.
  * pH and EC only: how the probe normally behaves in its last `NORM_STEPS` trusted readings before the
    current identical run (`change_share`, `change_steps`, `longest_run_s`). A drain probe that holds one
    value for hours has a low share; a probe that moves every sample has a high one.
  * pH and EC only: `spread_lag`, the spread of the window's trusted readings that are older than
    `SPREAD_LAG_S`. The drift check widens its threshold with the probe's own spread, and a slow drift widens
    `spread` itself (the readings that were still inside the threshold are trusted) until it hides the drift;
    the lagged spread has not yet seen the newest half hour, so it does not. (Core sends it for both; the router
    uses it for pH only, because a real EC rise, a drying substrate concentrating the solution, would look like a
    drift to it.)

Shared by Core's outcome feed and the fake-greenhouse scorer (which loads this file by path), so both
compute the reference exactly the same way.

Two ways to the same bytes. `stream_baseline` is the reference: it walks the stored readings newest first,
once for all fields, and a field stops being walked when its run, window and norm are settled, so a late
reading costs the window plus the current run (and a whole-history scan for a field no reading carries, such
as moisture in a hydroponic zone). `StreamBaseline` keeps the same answer up to date one reading at a time for
a caller that holds the stream in memory (the in-process engine behind the scorer and the "Try to fool Pomona"
Space), so a reading costs about the same however long the stream is (CPython, hour 20 of the game, 2400
readings per stream: `stream_baseline` 1 to 2.5 ms per call, the tracker about 0.1 ms).
The tests hold the two byte for byte equal (scan-limit overflow, calibrations, vetoes, lapses and out-of-order
arrival included); change one only together with the other.
"""

from __future__ import annotations

import math
from bisect import bisect_right, insort_left
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

# Reference window, measured back from the newest trusted reading (not from "now", so a long fault does
# not erase the reference it is judged against). 2 h is long enough to span the irrigation and day-night
# swings of the normal fake greenhouse and short enough to follow real slow trends.
DEFAULT_WINDOW_S = 2 * 3600
# Trusted readings needed in the window before the reference is used: 6 is three minutes at 30 s and
# thirty minutes at 5 min, enough for a stable median without delaying the check for long after start-up.
DEFAULT_MIN_N = 6
# How long a reference outlives the last trusted reading before it lapses (the probe is then judged afresh by
# the 11-packet checks alone, and its readings count as trusted again). 0 = never: a flagged level stays "can't
# confirm" until a calibration. A lapse is opt-in (TRUST_BASELINE_MAX_AGE_S). On historical logs nobody can
# calibrate, and with no lapse one real level shift keeps a drain probe flagged for days (see make real-replay).
DEFAULT_MAX_AGE_S = 0
# Stored readings of the stream scanned back for the reference: bounds the query (about 40 hours at 30 s,
# 17 days at 5 min). Older readings fall out, so a fault older than that stops being judged.
DEFAULT_SCAN_LIMIT = 5000
IDENTICAL_EPSILON = 1e-9  # same value, as in the router's stuck check
# Trusted steps (readings minus one) before the current identical run that describe how a pH or EC probe
# normally changes. Counted in readings, not hours, so the walk stays bounded at any sample rate: 200 steps
# are 100 minutes at 30 s and 17 hours at 5 minutes. Real drain probes, which really sit still for hours,
# change in 3 to 18 % of their steps; probes that move every sample change in more than 90 %.
NORM_STEPS = 200
NORM_FIELDS = ("ph", "ec_ms_cm")
# Age (seconds, behind the newest trusted reading) a trusted reading needs before it counts for `spread_lag`.
SPREAD_LAG_S = 1800

# Fields the router can check against a reference, and the calibration `measurement` that resets each.
BASELINE_FIELDS = ("ph", "ec_ms_cm", "air_temperature_c", "humidity_pct", "soil_moisture_pct",
                   "substrate_moisture_pct", "substrate_temperature_c")
MEASUREMENT_FIELDS = {
    "ph": ("ph",),
    "ec_ms_cm": ("ec_ms_cm",),
    "air_temperature_c": ("air_temperature_c",),
    "humidity_pct": ("humidity_pct",),
    "soil_moisture_pct": ("soil_moisture_pct", "substrate_moisture_pct"),
}
# One moisture probe is published under two names; a veto on either is a veto on both.
ALIASES = {"soil_moisture_pct": "substrate_moisture_pct", "substrate_moisture_pct": "soil_moisture_pct"}


def parse_time(value: Any) -> Optional[datetime]:
    """An aware UTC datetime from a datetime or an ISO string (Z or offset), else None."""
    if isinstance(value, datetime):
        if value.tzinfo is timezone.utc:
            return value
    elif isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) if math.isfinite(value) else None


def _norm(before: List[tuple]) -> Dict[str, Any]:
    """How a probe normally changes, from its trusted (sample time, value) rows NEWEST FIRST: the share of steps
    in which the value differs and the longest span (seconds) one value was held. Empty with fewer than 2 rows."""
    if len(before) < 2:
        return {}
    changes, longest = 0, 0.0
    group_newest, (last_stamp, last_value) = before[0][0], before[0]
    for stamp, value in before[1:]:
        if abs(value - last_value) > IDENTICAL_EPSILON:
            changes += 1
            longest = max(longest, (group_newest - last_stamp).total_seconds())
            group_newest = stamp
        last_stamp, last_value = stamp, value
    longest = max(longest, (group_newest - last_stamp).total_seconds())
    steps = len(before) - 1
    return {"change_share": round(changes / steps, 4), "change_steps": steps, "longest_run_s": longest}


def _percentile_range(ordered: List[float]) -> float:
    """10th to 90th percentile range of values SORTED (at least one)."""
    count = len(ordered)
    return ordered[int(0.9 * (count - 1))] - ordered[int(0.1 * (count - 1))]


def _lagged(old: List[float], min_n: int) -> Dict[str, Any]:
    """`spread_lag` from the window's trusted values older than SPREAD_LAG_S, SORTED; empty with fewer than `min_n`."""
    return {"spread_lag": round(_percentile_range(old), 6)} if old and len(old) >= min_n else {}


def _summary(ordered: List[float], window_s: float, changed_at: datetime, last_value: float, anchor: datetime,
             before: List[tuple], lagged: Dict[str, Any]) -> Dict[str, Any]:
    """The reported reference from the window's values SORTED, the start of the identical run, the newest trusted
    reading (`last_value` at `anchor`), the norm rows and `spread_lag`. Shared by every way of walking the history."""
    count = len(ordered)
    spread = _percentile_range(ordered)
    middle = count // 2  # what statistics.median gives: the middle value, or the mean of the two middle ones
    return {"median": ordered[middle] if count % 2 else (ordered[middle - 1] + ordered[middle]) / 2,
            "n": count, "window_s": window_s, "spread": round(spread, 6), "last_change_at": changed_at.isoformat(),
            "last_value": last_value, "last_at": anchor.isoformat(), **_norm(before), **lagged}


class _Walk:
    """One field's newest-first walk over its (sample time, value, vetoed) rows, one `push` per row.

    The walk stops (`open` goes False) once the identical run, the window and (with `norm_steps`) the readings
    before the run are all settled, so it costs the window plus the current run (a long fault costs its
    length), not the whole history. `_stats` drives one walk over one field's rows; `stream_baseline` drives
    one per field side by side over a single pass of the history.
    """

    __slots__ = ("field", "alias", "window_s", "start_at", "norm_steps", "newest", "changed_at", "anchor",
                 "run_open", "window_open", "norm_open", "open", "values", "stamps", "before")

    def __init__(self, field: Optional[str], window_s: float, start_at: Optional[datetime], norm_steps: int = 0) -> None:
        self.field = field
        self.alias = ALIASES.get(field)
        self.window_s = window_s
        self.start_at = start_at
        self.norm_steps = norm_steps
        self.newest = self.changed_at = self.anchor = None
        self.run_open = self.window_open = self.open = True
        self.norm_open = norm_steps > 0
        self.values: List[float] = []
        self.stamps: List[datetime] = []  # the window's sample times, as `values`, for the lagged spread
        self.before: List[tuple] = []  # trusted (time, value) rows before the current run, for the norm

    def push(self, stamp: datetime, value: float, vetoed: bool) -> bool:
        """Take the next older row. False once the walk is settled and needs no more rows."""
        start_at = self.start_at
        if self.newest is None:
            self.newest, self.changed_at = value, stamp
        elif self.run_open:
            if abs(value - self.newest) <= IDENTICAL_EPSILON:
                self.changed_at = stamp
            else:
                self.run_open = False
        if self.window_open:
            if start_at is not None and stamp < start_at:
                self.window_open = False  # earlier readings are before the calibration (rows are in time order)
            elif not vetoed:
                if self.anchor is None:
                    self.anchor = stamp
                elif (self.anchor - stamp).total_seconds() > self.window_s:
                    self.window_open = False
                if self.window_open:
                    self.values.append(value)
                    if self.norm_steps > 0:
                        self.stamps.append(stamp)
        if self.norm_open and not self.run_open:
            if start_at is not None and stamp < start_at:
                self.norm_open = False
            elif not vetoed:
                self.before.append((stamp, value))
                self.norm_open = len(self.before) <= self.norm_steps
        self.open = self.run_open or self.window_open or self.norm_open
        return self.open

    def stats(self, min_n: int, now: Optional[datetime] = None,
              max_age_s: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """The trusted reference of the rows pushed so far, or None (no rows, too few trusted, or lapsed)."""
        if self.newest is None:
            return None
        values, anchor = self.values, self.anchor
        changed_at = self.changed_at if self.start_at is None else max(self.changed_at, self.start_at)
        if len(values) < min_n or (max_age_s is not None and now is not None and (now - anchor).total_seconds() > max_age_s):
            return None
        old = sorted(v for v, s in zip(values, self.stamps) if (anchor - s).total_seconds() > SPREAD_LAG_S)
        return _summary(sorted(values), self.window_s, changed_at, values[0], anchor, self.before, _lagged(old, min_n))


def _stats(rows: Iterable[tuple], window_s: float, min_n: int, start_at: Optional[datetime],
           now: Optional[datetime] = None, max_age_s: Optional[float] = None,
           norm_steps: int = 0) -> Optional[Dict[str, Any]]:
    """`rows` are (sample time, value, vetoed), NEWEST FIRST, and are read lazily: the walk stops once the
    identical run, the window and (with `norm_steps`) the readings before the run are all settled."""
    walk = _Walk(None, window_s, start_at, norm_steps)
    for stamp, value, vetoed in rows:
        if not walk.push(stamp, value, vetoed):
            break
    return walk.stats(min_n, now, max_age_s)


def trusted_stats(readings: Iterable[Dict[str, Any]], field: str, now: Any, window_s: float = DEFAULT_WINDOW_S,
                  min_n: int = DEFAULT_MIN_N, calibrated_after: Any = None,
                  max_age_s: Optional[float] = None, norm_steps: int = 0) -> Optional[Dict[str, Any]]:
    """Trusted reference for one field, or None when there are not enough trusted readings.

    `readings` are dicts with `timestamp`, `value` (or the field's own key) and `vetoed` (bool); readings
    after `now` are ignored. The median covers the not-vetoed values within `window_s` of the newest
    trusted reading, sampled at or after `calibrated_after`. `last_change_at` is the sample time where the
    trailing run of identical values starts, over all readings (never earlier than the calibration).
    `spread` is the window's 10th-to-90th percentile range, how far the probe normally wanders.
    `last_value` / `last_at` are the newest trusted reading. With `norm_steps`, `change_share`,
    `change_steps` and `longest_run_s` describe the last `norm_steps` trusted steps before the current
    identical run. With `max_age_s` the reference lapses when the newest trusted reading is older than that.
    """
    limit = parse_time(now)
    rows = []
    for reading in readings:
        stamp = parse_time(reading.get("timestamp"))
        value = _number(reading["value"] if "value" in reading else reading.get(field))
        if stamp is None or value is None or (limit is not None and stamp > limit):
            continue
        rows.append((stamp, value, bool(reading.get("vetoed"))))
    rows.sort(key=lambda row: row[0])
    return _stats(reversed(rows), window_s, min_n, parse_time(calibrated_after), limit, max_age_s, norm_steps)


def _latest_calibrations(calibrations: List[Dict[str, Any]], limit: Optional[datetime]) -> Dict[str, datetime]:
    """The newest applicable calibration time per baseline field (one measurement can reset two fields)."""
    latest: Dict[str, datetime] = {}
    for item in calibrations:
        stamp = parse_time(item.get("performed_at"))
        if stamp is None or (limit is not None and stamp > limit):
            continue  # a calibration recorded after this reading does not apply to it
        for field in MEASUREMENT_FIELDS.get(item.get("measurement"), ()):
            if field not in latest or stamp > latest[field]:
                latest[field] = stamp
    return latest


def stream_baseline(prior: List[Dict[str, Any]], calibrations: List[Dict[str, Any]], now: Any,
                    window_s: float = DEFAULT_WINDOW_S, min_n: int = DEFAULT_MIN_N,
                    max_age_s: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """`{field: trusted_stats}` for every field that has stats.

    `prior` are the stream's stored readings sampled before the current one, oldest first (in sample-time
    order; Core sorts them): each a dict with
    `timestamp`, the sensor fields, and `vetoed_fields` (what the pipeline vetoed; absent means none, as
    for readings stored before trust was recorded). `calibrations` are dicts with `measurement` and
    `performed_at`; ones after `now` do not apply.

    One newest-first pass over `prior` serves every field: each reading's timestamp is parsed once, a field
    that no earlier reading carries costs one dict lookup per reading, and a field leaves the pass as soon as
    its identical run, window and norm are settled (the walk of `_stats`, run side by side).
    """
    limit = parse_time(now)
    latest = _latest_calibrations(calibrations, limit)
    walks = [_Walk(field, window_s, latest.get(field), NORM_STEPS if field in NORM_FIELDS else 0) for field in BASELINE_FIELDS]
    open_walks = walks
    for packet in reversed(prior):
        get = packet.get
        stamp = None
        vetoed = None
        closed = False
        for walk in open_walks:
            value = get(walk.field)
            if value is None:
                continue
            value = _number(value)
            if value is None:
                continue
            if stamp is None:
                stamp = parse_time(get("timestamp"))
                if stamp is None or (limit is not None and stamp > limit):
                    stamp = False
                else:
                    vetoed = get("vetoed_fields") or ()
            if stamp is False:
                break  # an unreadable or future sample time is no row for any field
            if not walk.push(stamp, value, walk.field in vetoed or walk.alias in vetoed):
                closed = True
        if closed:
            open_walks = [walk for walk in open_walks if walk.open]
            if not open_walks:
                break
    out: Dict[str, Dict[str, Any]] = {}
    for walk in walks:
        stats = walk.stats(min_n, limit, max_age_s)
        if stats is not None:
            out[walk.field] = stats
    return out


class _FieldState:
    """One field of a stream kept up to date reading by reading, for `StreamBaseline`.

    `rows` are the field's usable readings (entry index, sample time, value, vetoed) oldest first, from `head`
    on (older ones fell out of the scan limit). Besides them it keeps what `stream_baseline` would walk the
    history for, so a new reading costs about one row of work: where the identical run starts, and the
    window's trusted readings in time order with their values sorted. Valid while sample times never go back.
    """

    __slots__ = ("field", "alias", "window_s", "start_at", "rows", "head", "run", "window", "ranked")

    def __init__(self, field: str, window_s: float) -> None:
        self.field = field
        self.alias = ALIASES.get(field)
        self.window_s = window_s
        self.start_at: Optional[datetime] = None  # the calibration the window is anchored to
        self.rows: List[tuple] = []
        self.head = 0  # rows[head:] are retained
        self.run = 0  # index in `rows` where the identical run ending at the newest row starts
        self.window: deque = deque()  # (entry index, sample time, value) of the trusted readings in the window
        self.ranked: List[float] = []  # the window's values, sorted

    def append(self, index: int, stamp: datetime, value: float, vetoed: bool) -> None:
        rows = self.rows
        position = len(rows)
        newest = rows[-1][2] if position > self.head else None
        rows.append((index, stamp, value, vetoed))
        if newest is None or value != newest:  # the same value again extends the run, whatever it is
            run, head = position, self.head
            while run > head and abs(rows[run - 1][2] - value) <= IDENTICAL_EPSILON:
                run -= 1
            self.run = run
        if not vetoed and (self.start_at is None or stamp >= self.start_at):
            window = self.window
            window.append((index, stamp, value))
            insort_left(self.ranked, value)  # among equal values the newest first, as sorted() keeps them (0.0 and -0.0 differ)
            while (stamp - window[0][1]).total_seconds() > self.window_s:
                del self.ranked[bisect_right(self.ranked, window.popleft()[2]) - 1]  # the oldest of its equals is the last

    def trim(self, floor: int) -> None:
        """Forget readings with an entry index below `floor` (beyond the scan limit)."""
        rows, head = self.rows, self.head
        while head < len(rows) and rows[head][0] < floor:
            head += 1
        if head != self.head:
            self.head = head
            self.run = max(self.run, head)
            if head >= 4096 and head * 2 >= len(rows):  # amortised: drop the forgotten rows for real
                del rows[:head]
                self.run -= head
                self.head = 0
        window = self.window
        while window and window[0][0] < floor:
            del self.ranked[bisect_right(self.ranked, window.popleft()[2]) - 1]  # the oldest of its equals is the last

    def restart(self, start_at: Optional[datetime]) -> None:
        """A calibration changed: rebuild the window from the retained rows, only readings from `start_at` on."""
        self.start_at = start_at
        newest_first, anchor = [], None
        for index, stamp, value, vetoed in reversed(self.rows[self.head:]):
            if start_at is not None and stamp < start_at:
                break
            if vetoed:
                continue
            if anchor is None:
                anchor = stamp
            elif (anchor - stamp).total_seconds() > self.window_s:
                break
            newest_first.append((index, stamp, value))
        self.window = deque(reversed(newest_first))
        self.ranked = sorted(item[2] for item in newest_first)

    def stats(self, min_n: int, now: Optional[datetime], max_age_s: Optional[float]) -> Optional[Dict[str, Any]]:
        window = self.window
        if len(window) < min_n:  # also no rows at all, or none from the calibration on
            return None
        _, anchor, last_value = window[-1]
        if max_age_s is not None and now is not None and (now - anchor).total_seconds() > max_age_s:
            return None
        rows, start_at = self.rows, self.start_at
        changed_at = rows[self.run][1]
        if start_at is not None:
            changed_at = max(changed_at, start_at)
        before: List[tuple] = []  # trusted (time, value) rows from the one that ended the run back, newest first
        if self.field in NORM_FIELDS:
            position = self.run - 1
            while position >= self.head and len(before) <= NORM_STEPS:
                _, stamp, value, vetoed = rows[position]
                if start_at is not None and stamp < start_at:
                    break
                if not vetoed:
                    before.append((stamp, value))
                position -= 1
        old: List[float] = []
        if self.field in NORM_FIELDS:
            old = sorted(v for _, s, v in window if (anchor - s).total_seconds() > SPREAD_LAG_S)
        return _summary(self.ranked, self.window_s, changed_at, last_value, anchor, before, _lagged(old, min_n))


class StreamBaseline:
    """`stream_baseline` for one stream that grows one reading at a time, without rescanning the history.

    `add(packet)` takes each stored reading of the stream in arrival order (the dicts `stream_baseline` takes
    in `prior`); `baseline(calibrations, now)` returns exactly `stream_baseline(<the last `scan_limit` readings
    added>, calibrations, now, window_s, min_n, max_age_s)`, byte for byte (`stream_baseline` stays the
    reference; the tests compare the two). A reading costs about the same however long the stream is, where
    `stream_baseline` walks the window, the norm and the identical run again for every field, and the whole
    history for a field no reading carries.

    The fast path needs sample times that never go back and a `now` no earlier than the newest one, which is
    how Core and the in-process engine feed it. A reading that arrives out of order, or a query dated before
    one already added, falls back to `stream_baseline` on the retained readings (for the rest of the stream in
    the first case), so the answer is the same whatever the order. Not thread-safe: one caller per stream.
    """

    def __init__(self, window_s: float = DEFAULT_WINDOW_S, min_n: int = DEFAULT_MIN_N,
                 max_age_s: Optional[float] = None, scan_limit: int = DEFAULT_SCAN_LIMIT) -> None:
        if scan_limit < 1:
            raise ValueError("scan_limit must be at least 1")
        self.window_s, self.min_n, self.max_age_s, self.scan_limit = window_s, min_n, max_age_s, scan_limit
        self._entries: deque = deque(maxlen=scan_limit)  # for the fallback
        self._count = 0  # readings added so far
        self._last_stamp: Optional[datetime] = None  # newest sample time seen
        # The incremental state assumes at least one trusted reading is needed and a non-negative window.
        self._fields: Optional[Dict[str, _FieldState]] = (
            {field: _FieldState(field, window_s) for field in BASELINE_FIELDS} if min_n >= 1 and window_s >= 0 else None)

    def add(self, packet: Dict[str, Any]) -> None:
        """Append the stream's next stored reading (its `timestamp`, sensor fields and `vetoed_fields`)."""
        index = self._count
        self._count += 1
        self._entries.append(packet)
        fields = self._fields
        if fields is None:
            return
        stamp = parse_time(packet.get("timestamp"))
        if stamp is not None:
            if self._last_stamp is not None and stamp < self._last_stamp:
                self._fields = None  # out of order: the incremental state no longer describes the walk
                return
            self._last_stamp = stamp
            vetoed = packet.get("vetoed_fields") or ()
            for field, state in fields.items():
                value = packet.get(field)
                if value is None:
                    continue
                value = _number(value)
                if value is not None:
                    state.append(index, stamp, value, field in vetoed or state.alias in vetoed)
        floor = self._count - self.scan_limit
        if floor > 0:
            for state in fields.values():
                state.trim(floor)

    def baseline(self, calibrations: List[Dict[str, Any]], now: Any) -> Dict[str, Dict[str, Any]]:
        """`{field: trusted_stats}` of the readings added so far, as `stream_baseline` gives it for `now`."""
        limit = parse_time(now)
        fields = self._fields
        if fields is None or (limit is not None and self._last_stamp is not None and self._last_stamp > limit):
            return stream_baseline(list(self._entries), calibrations, now, self.window_s, self.min_n, self.max_age_s)
        latest = _latest_calibrations(calibrations, limit)
        out: Dict[str, Dict[str, Any]] = {}
        for field in BASELINE_FIELDS:
            state = fields[field]
            if latest.get(field) != state.start_at:
                state.restart(latest.get(field))
            stats = state.stats(self.min_n, limit, self.max_age_s)
            if stats is not None:
                out[field] = stats
        return out
