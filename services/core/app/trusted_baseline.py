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

Shared by Core's outcome feed and the fake-greenhouse scorer (which loads this file by path), so both
compute the reference exactly the same way.
"""

from __future__ import annotations

import math
import statistics
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


def _stats(rows: Iterable[tuple], window_s: float, min_n: int, start_at: Optional[datetime],
           now: Optional[datetime] = None, max_age_s: Optional[float] = None,
           norm_steps: int = 0) -> Optional[Dict[str, Any]]:
    """`rows` are (sample time, value, vetoed), NEWEST FIRST, and are read lazily: the walk stops once the
    identical run, the window and (with `norm_steps`) the readings before the run are all settled, so it
    costs the window plus the current run (a long fault costs its length), not the whole history."""
    newest = changed_at = anchor = None
    run_open, window_open, norm_open = True, True, norm_steps > 0
    values: List[float] = []
    before: List[tuple] = []  # trusted (time, value) rows before the current run, for the norm
    for stamp, value, vetoed in rows:
        if newest is None:
            newest, changed_at = value, stamp
        elif run_open:
            if abs(value - newest) <= IDENTICAL_EPSILON:
                changed_at = stamp
            else:
                run_open = False
        if window_open:
            if start_at is not None and stamp < start_at:
                window_open = False  # earlier readings are before the calibration (rows are in time order)
            elif not vetoed:
                if anchor is None:
                    anchor = stamp
                elif (anchor - stamp).total_seconds() > window_s:
                    window_open = False
                if window_open:
                    values.append(value)
        if norm_open and not run_open:
            if start_at is not None and stamp < start_at:
                norm_open = False
            elif not vetoed:
                before.append((stamp, value))
                norm_open = len(before) <= norm_steps
        if not run_open and not window_open and not norm_open:
            break
    if newest is None:
        return None
    if start_at is not None:
        changed_at = max(changed_at, start_at)
    if len(values) < min_n or (max_age_s is not None and now is not None and (now - anchor).total_seconds() > max_age_s):
        return None
    ordered = sorted(values)
    spread = ordered[int(0.9 * (len(ordered) - 1))] - ordered[int(0.1 * (len(ordered) - 1))]
    return {"median": statistics.median(values), "n": len(values), "window_s": window_s,
            "spread": round(spread, 6), "last_change_at": changed_at.isoformat(),
            "last_value": values[0], "last_at": anchor.isoformat(), **_norm(before)}


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


def stream_baseline(prior: List[Dict[str, Any]], calibrations: List[Dict[str, Any]], now: Any,
                    window_s: float = DEFAULT_WINDOW_S, min_n: int = DEFAULT_MIN_N,
                    max_age_s: Optional[float] = None) -> Dict[str, Dict[str, Any]]:
    """`{field: trusted_stats}` for every field that has stats.

    `prior` are the stream's stored readings sampled before the current one, oldest first (in sample-time
    order; Core sorts them): each a dict with
    `timestamp`, the sensor fields, and `vetoed_fields` (what the pipeline vetoed; absent means none, as
    for readings stored before trust was recorded). `calibrations` are dicts with `measurement` and
    `performed_at`; ones after `now` do not apply.
    """
    limit = parse_time(now)
    latest: Dict[str, datetime] = {}
    for item in calibrations:
        stamp = parse_time(item.get("performed_at"))
        if stamp is None or (limit is not None and stamp > limit):
            continue  # a calibration recorded after this reading does not apply to it
        for field in MEASUREMENT_FIELDS.get(item.get("measurement"), ()):
            if field not in latest or stamp > latest[field]:
                latest[field] = stamp
    out: Dict[str, Dict[str, Any]] = {}
    for field in BASELINE_FIELDS:
        alias = ALIASES.get(field)

        def newest_first(field=field, alias=alias):
            for packet in reversed(prior):  # lazily: only as far back as the walk needs
                stamp = parse_time(packet.get("timestamp"))
                value = _number(packet.get(field))
                if stamp is None or value is None or (limit is not None and stamp > limit):
                    continue
                vetoed = packet.get("vetoed_fields") or ()
                yield stamp, value, field in vetoed or alias in vetoed

        stats = _stats(newest_first(), window_s, min_n, latest.get(field), limit, max_age_s,
                       NORM_STEPS if field in NORM_FIELDS else 0)
        if stats is not None:
            out[field] = stats
    return out
