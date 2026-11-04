"""Sensor quality reasoner routing helpers.

This exposes the sensor-quality contract before local LoRA inference is wired.
The deterministic path is intentionally conservative: it blocks downstream
confidence when required fields are missing, implausible, stale, or conflicting.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
from typing import Any, Dict, List, Optional


FIELD_LABELS = {
    "ph": "missing_ph",
    "ec_ms_cm": "missing_ec",
    "air_temperature_c": "missing_temperature",
    "water_temperature_c": "missing_temperature",
    "substrate_temperature_c": "missing_temperature",
    "humidity_pct": "missing_humidity",
    "substrate_moisture_pct": "missing_moisture",
    "soil_moisture_pct": "missing_moisture",
}

# Exact stuck/flatline applies to fields that normally show small sample-to-sample
# change. Quantized probes (pH/EC) are excluded here so legitimate plateaus stay quiet;
# apply_persistent_checks judges them against their own history instead (ADAPTIVE_STUCK_*).
STUCK_FIELDS = (
    "air_temperature_c",
    "water_temperature_c",
    "substrate_temperature_c",
    "humidity_pct",
    "substrate_moisture_pct",
    "soil_moisture_pct",
)
# Chemical probes: compare recent value to the stream startup baseline.
BASELINE_DRIFT_FIELDS = ("ph", "ec_ms_cm")
STUCK_WINDOW = 3
# Flatline is a softer hint than stuck, so it uses a longer window: slow signals
# at 5-minute steps often stay within epsilon for 3 samples while healthy.
FLATLINE_WINDOW = 6
STUCK_EPSILON = 1e-9
BASELINE_DRIFT_THRESHOLDS = {"ph": 0.35, "ec_ms_cm": 0.4}
# Readings outside these bounds are flagged impossible and never serve as a drift baseline.
# The baseline is the median of the first plausible readings in the window, so one
# outlier at the start cannot make every later reading look drifted.
BASELINE_SAMPLES = 3
PLAUSIBLE_RANGES = {"ph": (3.0, 11.0), "ec_ms_cm": (0.0, 12.0)}
# Water volumes and substrate have thermal mass: a DS18B20 can legitimately hold one
# 0.0625 C step for hours (real aquaponic pond at 5-minute samples: 99th percentile
# 2.25 h, longest 4.75 h). A freeze on these fields must also last this long.
#
# Moisture probes report in 0.1 % steps with noise of several steps, so a run of identical readings happens by
# chance; at 30 s sampling the plain 3-sample rule would call a 5-sample run (2.5 min) a freeze. A freeze must
# also span 2 minutes: nothing changes at 1-minute or slower sampling (3 samples already span 2 minutes), and
# at 30 s the card needs 7 identical readings instead of 5 (fake greenhouse, seeds 1-80: 2 chance cards, 0 after).
STUCK_MIN_DURATION = {
    "water_temperature_c": timedelta(hours=3),
    "substrate_temperature_c": timedelta(hours=3),
    "substrate_moisture_pct": timedelta(minutes=2),
    "soil_moisture_pct": timedelta(minutes=2),
}
# Persistent stuck check, only when Core supplies a trusted per-stream reference (`stream_baseline`): a field
# whose value has not changed for longer than its limit is stuck, however much earlier variation it showed.
# The 11-packet check above stops flagging once the frozen run fills its whole window. The limits come from
# the real logs (datasets/raw, make real-replay): the share of readings that would exceed them there was
# kept under 0.15 %, the same ballpark as the existing stuck-value guards.
#   air temperature 45 min: real 0.1 C-resolution probes repeat for 20-30 min on up to 1.7 % of readings
#                           (nights at the heating set-point); 45 min leaves 0.15 %, 60 min 0.04 %.
#   humidity 30 min:        real runs are shorter (0.1 % beyond 30 min).
#   substrate temperature 6 h, water temperature 3 h: thermal mass. Real slab probes hold one 0.1 C value
#                           for up to 9 h (3 h would flag 0.1-1.3 % of readings); a real pond holds one
#                           0.0625 C step up to 6 h (3 h: 0.2 %), as STUCK_MIN_DURATION already says.
# pH and EC have no fixed limit: a drain or tank probe only changes when water flows past it, and real logs sit
# on one value for hours as a matter of course (80 % of readings are beyond 20 min). They get the adaptive
# check below instead. Moisture is left out: a hydroponic zone sends a constant placeholder and slab moisture
# can sit still overnight.
PERSISTENT_STUCK_LIMITS = {
    "air_temperature_c": timedelta(minutes=45),
    "humidity_pct": timedelta(minutes=30),
    "substrate_temperature_c": timedelta(hours=6),
    "water_temperature_c": STUCK_MIN_DURATION["water_temperature_c"],
}
# Adaptive stuck check for pH and EC (needs Core's `change_share` / `change_steps` / `longest_run_s`, which
# describe how the probe behaved in its last 200 trusted readings before the current identical run). A probe
# that normally moves every sample (the simulator's pH and EC, the Pomona cress logger's pH) and then freezes is
# stuck; a drain probe that holds one value for hours is not, however long the hold. So the check applies only to
# a stream that changed in at least 70 % of its trusted steps (and has 15 of them), and the freeze must be longer than
# 5 minutes AND 4 times the longest hold that stream showed. Real logs (make real-replay, 5-minute samples): every
# drain probe changes in 3 to 18 % of its steps and is never checked; the pond EC (77 %) rests up to an hour
# and is the only stream near the line. Share of real readings flagged: under 0.02 %, the same with the floor at 15
# minutes (the floor only matters for a probe whose longest hold is under 75 seconds; it is one real 5-minute
# sample, so a pair of equal readings never counts). The first freeze's trusted minutes count as a hold of their own
# for the next 200 readings, so a second freeze soon after needs 4 times as long as the first took to be flagged.
ADAPTIVE_STUCK_FIELDS = ("ph", "ec_ms_cm")
ADAPTIVE_STUCK_FLOOR = timedelta(minutes=5)
ADAPTIVE_STUCK_RUN_FACTOR = 4.0
ADAPTIVE_STUCK_MIN_STEPS = 15
ADAPTIVE_STUCK_MIN_CHANGE_SHARE = 0.7
# The identical run must also hold this many readings (the last ones, counted from the packets the router sees). At a slow
# sample rate one pair of equal 2-decimal readings is already more than the time floor (10 or 15 minutes apart) and
# probes that change on nearly every sample repeat by chance now and then; a freeze is at least 3 readings in a row.
ADAPTIVE_STUCK_MIN_RUN = 3
# Sudden step (needs Core's `last_value` / `last_at`: the newest trusted reading). A field cannot move by more than
# max(smallest allowance, speed x minutes since that reading). A flagged reading is vetoed, so the reference stays put
# and a step is flagged until the allowance has grown to cover it, then the new level is accepted. The allowances come
# from the real logs (make real-replay, 5-minute samples; share of real readings flagged, worst compartment):
#   air temperature 3 C, 1 C/min: a heat spike ramps about 0.5 C per minute and stays well inside. 0.054 % (the
#       Reference compartment holds 17 C glitches), 0.002 % elsewhere.
#   humidity 12 %RH, 4 %RH/min (20 %RH between 5-minute samples): real 5-minute steps reach 8 to 15 %RH in 0.1 % of
#       readings and 15 to 20 in 0.01 %; only glitches and the odd 25 %RH step go beyond. 0.021 % (Reference).
#   substrate moisture 8 %, 2 %/min (10 % between 5-minute samples): the largest real 5-minute step is 4.3 to 7.1 %
#       (an irrigation pulse), apart from one 79 % glitch. 0.017 % (Digilog: the glitch is held until the allowance
#       covers it).
#   substrate temperature 1.5 C, 0.3 C/min: a slab has thermal mass; the largest real 5-minute step is 0.4 to 0.8 C
#       apart from one 2.4 C glitch. 0.006 % (Digilog).
# A smaller offset than the allowance (a humidity shift of 10 %RH, a moisture shift of 5 %) cannot be told from a
# real change in one sample and is not caught here.
STEP_LIMITS = {
    "air_temperature_c": (3.0, 1.0, "C", "a second thermometer"),
    "humidity_pct": (12.0, 4.0, "%RH", "a second hygrometer"),
    "soil_moisture_pct": (8.0, 2.0, "%", "a hand-held moisture meter"),
    "substrate_moisture_pct": (8.0, 2.0, "%", "a hand-held moisture meter"),
    "substrate_temperature_c": (1.5, 0.3, "C", "a second thermometer"),
}
STEP_FIELDS = tuple(STEP_LIMITS)
# A rise in substrate moisture from a trusted level below this is not judged by speed: a slab that dry (the water-level
# card fires below 10 %) is rewetted by one irrigation, which the fake greenhouse's dry zone shows as +40 % in one
# sample. The real logs never get that dry (lowest 54 %, apart from one 0 % glitch), so they say nothing about how
# fast a dry slab rewets and the exemption costs them nothing. A fall, and a rise from any wetter level, keep the
# allowance.
STEP_REWET_BELOW_PCT = {"soil_moisture_pct": 15.0, "substrate_moisture_pct": 15.0}
STEP_MIN_C, STEP_MAX_RATE_C_PER_MIN = STEP_LIMITS["air_temperature_c"][:2]
# Noise on a continuous probe: the median step over the last 12 readings, when the window has not simply moved in one
# direction (a ramp is not noise). Real 5-minute logs set the limit (the share of real windows at or above it stays
# under 0.15 %); a legitimate swing is spread over more samples when they come faster, so the limit shrinks with the
# square root of the sample interval, down to a floor above what a healthy probe's windows reach (fake greenhouse,
# normal runs of seeds 1 to 80: the largest window median step is humidity 2.5 %RH, air 0.32 C, pH 0.06, moisture
# 1.5 %, substrate temperature 0.31 C). No real log is sampled faster than 5 minutes, so the scaling is untested there.
# Share of real 12-reading windows at or above the 5-minute limit (worst compartment):
#   humidity 10 %RH 0.084 %, air 2 C 0.029 %, pH 0.5 0.13 % (AICU; the pond pH is noisy by nature, see
#   noisy_signal_possible above), moisture 1.0 % 0.009 %, substrate temperature 0.4 C 0 %.
# EC is not here: the Automatoes drain EC really jumps (1.0 % of its windows have a median step of 0.4 mS/cm or
# more, 0.29 % of 2 mS/cm), so no limit that real data allows is below what a noisy simulator probe shows.
NOISE_STEP_LIMIT_5MIN = {"humidity_pct": 10.0, "air_temperature_c": 2.0, "ph": 0.5,
                         "soil_moisture_pct": 1.0, "substrate_moisture_pct": 1.0, "substrate_temperature_c": 0.4}
NOISE_STEP_FLOOR = {"humidity_pct": 3.0, "air_temperature_c": 0.4, "ph": 0.1,
                    "soil_moisture_pct": 2.5, "substrate_moisture_pct": 2.5, "substrate_temperature_c": 0.5}
NOISE_REFERENCE_INTERVAL_S = 300.0
NOISE_WINDOW = 12
NOISE_MAX_NET_SHARE = 0.5
# A pH/EC probe whose typical step between samples is as large as the drift threshold
# is too noisy to judge drift (e.g. an unshielded PH-4502C swinging ~1.6 pH in 5 min;
# commercial greenhouse drain sensors stay at <= 0.1).
NOISE_MIN_SAMPLES = 6
FLATLINE_EPSILON = {
    "air_temperature_c": 0.05,
    "water_temperature_c": 0.05,
    "substrate_temperature_c": 0.05,
    "humidity_pct": 0.25,
    "substrate_moisture_pct": 0.25,
    "soil_moisture_pct": 0.25,
}


def add_unique(items: List[str], value: str) -> None:
    if value not in items:
        items.append(value)


def numeric(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
            return parsed if math.isfinite(parsed) else None
        except ValueError:
            return None
    return None


def parse_timestamp(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    try:
        return parsed.astimezone(timezone.utc)
    except OverflowError:  # e.g. 0001-01-01T00:00:00+01:00 falls before year 1 in UTC
        return None


def stale_timestamp(sensor: Dict[str, Any], now: Optional[datetime]) -> bool:
    timestamp = parse_timestamp(sensor.get("timestamp"))
    if not timestamp or not now:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    age_seconds = (now.astimezone(timezone.utc) - timestamp).total_seconds()
    return age_seconds > 60 * 60


def _series_values(history: List[Dict[str, Any]], sensor: Dict[str, Any], field: str) -> List[float]:
    values: List[float] = []
    for packet in [*history, sensor]:
        if not isinstance(packet, dict):
            continue
        parsed = numeric(packet.get(field))
        if parsed is not None:
            values.append(parsed)
    return values


def _series_points(history: List[Dict[str, Any]], sensor: Dict[str, Any], field: str) -> List[tuple]:
    """(value, packet) pairs for packets with a numeric reading, oldest first."""
    points = []
    for packet in [*history, sensor]:
        if not isinstance(packet, dict):
            continue
        parsed = numeric(packet.get(field))
        if parsed is not None:
            points.append((parsed, packet))
    return points


def _trailing_run(values: List[float]) -> int:
    run = 0
    for value in reversed(values):
        if run and abs(value - values[-1]) > STUCK_EPSILON:
            break
        run += 1
    return run


def _longest_run(values: List[float]) -> int:
    longest = current = 0
    for index, value in enumerate(values):
        current = current + 1 if index and abs(value - values[index - 1]) <= STUCK_EPSILON else 1
        longest = max(longest, current)
    return longest


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    return ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2


def apply_temporal_checks(
    sensor: Dict[str, Any],
    history: List[Dict[str, Any]],
    labels: List[str],
    suspect_fields: List[str],
    checks: List[str],
) -> None:
    """Stuck / flatline / startup-baseline drift using prior packets (oldest first)."""
    if not history:
        return

    for field in STUCK_FIELDS:
        points = _series_points(history, sensor, field)
        values = [value for value, _ in points]
        # Stuck: the latest value has repeated at least STUCK_WINDOW times and at least
        # twice as long as any earlier repeat in the history. Continuous sensors are
        # flagged after 3 identical samples; quantized probes (e.g. DS18B20 0.0625 C
        # steps) that legitimately repeat 2-3 times need a correspondingly longer freeze.
        run = _trailing_run(values)
        earlier = values[:len(values) - run]
        long_enough = True
        if field in STUCK_MIN_DURATION and run:
            first = parse_timestamp(points[-run][1].get("timestamp"))
            last = parse_timestamp(points[-1][1].get("timestamp"))
            long_enough = first is not None and last is not None and last - first >= STUCK_MIN_DURATION[field]
        if (len(earlier) >= 2 and max(earlier) - min(earlier) > STUCK_EPSILON
                and run >= max(STUCK_WINDOW, 2 * _longest_run(earlier)) and long_enough):
            add_unique(labels, "stuck_value")
            add_unique(suspect_fields, field)
            checks.append(f"inspect {field}: identical readings across {run} fresh samples")
            continue
        # Flatline: the last FLATLINE_WINDOW samples moved less in total than the
        # sensor normally moves in a single step.
        epsilon = FLATLINE_EPSILON.get(field, 0.0)
        if len(values) >= FLATLINE_WINDOW + 2:
            prior = values[:-FLATLINE_WINDOW]
            window = values[-FLATLINE_WINDOW:]
            prior_step = _median([abs(b - a) for a, b in zip(prior, prior[1:])])
            span = max(window) - min(window)
            if prior_step >= epsilon and STUCK_EPSILON < span <= epsilon:
                add_unique(labels, "flatline_possible")
                add_unique(suspect_fields, field)
                checks.append(f"inspect {field}: near-zero variance may indicate a stuck or clipped probe")

    for field in BASELINE_DRIFT_FIELDS:
        threshold = BASELINE_DRIFT_THRESHOLDS[field]
        values = _series_values(history, sensor, field)
        if (len(values) >= NOISE_MIN_SAMPLES
                and _median([abs(b - a) for a, b in zip(values, values[1:])]) >= threshold):
            # Drift cannot be told apart from noise this large; report the noise instead.
            add_unique(labels, "noisy_signal_possible")
            add_unique(suspect_fields, field)
            checks.append(
                f"inspect {field}: readings jump between samples; check probe shielding, grounding and averaging"
            )
            continue
        low, high = PLAUSIBLE_RANGES[field]
        plausible = [value for value in (numeric(packet.get(field)) for packet in history if isinstance(packet, dict))
                     if value is not None and low <= value <= high][:BASELINE_SAMPLES]
        current = numeric(sensor.get(field))
        if len(plausible) < BASELINE_SAMPLES or current is None:
            continue
        baseline = _median(plausible)
        if abs(current - baseline) < threshold:
            continue
        # Require a short sustained walk away from startup, not a single spike.
        recent = _series_values(history[-(STUCK_WINDOW - 1):], sensor, field)
        if len(recent) < STUCK_WINDOW:
            continue
        if all(abs(value - baseline) >= threshold * 0.5 for value in recent):
            add_unique(labels, "baseline_drift_possible")
            add_unique(suspect_fields, field)
            checks.append(
                f"recalibrate or verify {field}: reading drifted from stream startup baseline"
            )


# A persistent drift must also be far outside how far the probe normally wanders (`spread`, the 10th to 90th
# percentile range of its trusted window). Real drain pH and EC swing with every irrigation; without this,
# 1 to 3 % of real readings sit 0.35 / 0.4 from their 2 h median and each one would start a flag.
DRIFT_SPREAD_FACTOR = 3.0
# A slow drift (pH 0.02 per minute) is trusted until it is a threshold away, and those readings widen the window's
# `spread` until 3 x spread hides the drift for good. So a pH stream that normally changes every sample (the same
# habit test as the adaptive stuck check: its spread is just its noise) is judged against `spread_lag`, the spread
# of the readings older than half an hour, which a drift in progress has not reached. Streams with a lower change
# share (every real drain probe) keep the full spread: it also covers their irrigation swings, and the lagged
# one flagged 2.2 to 2.3 % of the real drain EC readings (with the 2 h lapse) against 1.7 to 1.9 % without it.
# EC always keeps the full spread: its level really moves with the crop (a drying substrate concentrates the
# solution, the fake greenhouse's dry zone raises EC by 0.4 or more), and a probe that changes every sample would
# get a false "check the probe" card around every such event. A slow EC drift is therefore not caught.
LAGGED_SPREAD_FIELDS = ("ph",)
CALIBRATION_HINT = "if a meter agrees with the reading, it is real: record a calibration for this probe to accept it"


def apply_persistent_checks(
    sensor: Dict[str, Any],
    history: List[Dict[str, Any]],
    stream_baseline: Any,
    labels: List[str],
    suspect_fields: List[str],
    checks: List[str],
) -> None:
    """Judge the reading against Core's sticky trusted reference for its stream (see Core's trusted_baseline.py).

    The reference is the median of the readings in which the field was not vetoed, so a step or a frozen
    probe stays flagged for as long as it lasts instead of becoming the new normal after one history window.
    A calibration recorded for the probe re-anchors it. Malformed entries are ignored.
    """
    if not isinstance(stream_baseline, dict):
        return
    sampled = parse_timestamp(sensor.get("timestamp"))
    previous_packet = next((p for p in reversed(history) if isinstance(p, dict)), {})
    for field, stats in stream_baseline.items():
        current = numeric(sensor.get(field))
        if not isinstance(stats, dict) or current is None:
            continue
        median = numeric(stats.get("median"))
        threshold = BASELINE_DRIFT_THRESHOLDS.get(field)
        low, high = PLAUSIBLE_RANGES.get(field, (-math.inf, math.inf))
        spread = numeric(stats.get("spread")) or 0.0
        lagged_spread = numeric(stats.get("spread_lag"))
        if (field in LAGGED_SPREAD_FIELDS and lagged_spread is not None and lagged_spread >= 0
                and is_steady_stream(stats)):
            spread = lagged_spread  # a drift in progress has not reached it yet (see the note above CALIBRATION_HINT)
        if threshold is not None:
            threshold = max(threshold, DRIFT_SPREAD_FACTOR * spread)
        if median is not None and threshold is not None and low <= current <= high and abs(current - median) >= threshold:
            add_unique(labels, "baseline_drift_possible")
            add_unique(suspect_fields, field)
            checks.append(f"verify {field} with a meter: {current:g} differs from the trusted level {median:g}; "
                          + CALIBRATION_HINT)
        limit = PERSISTENT_STUCK_LIMITS.get(field)
        habit = ""
        adaptive = limit is None and field in ADAPTIVE_STUCK_FIELDS
        if adaptive:
            limit = adaptive_stuck_limit(stats)
            habit = f", though this probe normally changes on {numeric(stats.get('change_share')) or 0:.0%} of its readings"
        changed_at = parse_timestamp(stats.get("last_change_at"))
        previous = numeric(previous_packet.get(field))
        if (limit is not None and sampled is not None and changed_at is not None and previous is not None
                and abs(current - previous) <= STUCK_EPSILON and sampled - changed_at > limit
                and (not adaptive or _trailing_run([v for v, _ in _series_points(history, sensor, field)]) >= ADAPTIVE_STUCK_MIN_RUN)):
            add_unique(labels, "stuck_value")
            add_unique(suspect_fields, field)
            checks.append(f"inspect {field}: the same value for {(sampled - changed_at) // timedelta(minutes=1)} minutes"
                          + habit + "; " + CALIBRATION_HINT)
        if field in STEP_FIELDS:
            apply_step_check(field, current, sampled, stats, labels, suspect_fields, checks)
        if field in NOISE_STEP_LIMIT_5MIN:
            apply_noise_check(field, sensor, history, labels, suspect_fields, checks)


def is_steady_stream(stats: Dict[str, Any]) -> bool:
    """The stream changed in at least 70 % of its last trusted steps (and has 15 of them): it moves every sample."""
    share = numeric(stats.get("change_share"))
    steps = numeric(stats.get("change_steps"))
    return (share is not None and steps is not None and steps >= ADAPTIVE_STUCK_MIN_STEPS
            and share >= ADAPTIVE_STUCK_MIN_CHANGE_SHARE)


def adaptive_stuck_limit(stats: Dict[str, Any]) -> Optional[timedelta]:
    """How long this stream may repeat one value before it counts as stuck, or None when it is not judged.

    Only a stream that changes in nearly every trusted step is judged (a probe that really holds values for hours
    has a low change share and is left alone); the limit is the larger of the floor and 4 times its longest hold.
    """
    share = numeric(stats.get("change_share"))
    steps = numeric(stats.get("change_steps"))
    longest = numeric(stats.get("longest_run_s"))
    if (share is None or steps is None or longest is None or longest < 0
            or steps < ADAPTIVE_STUCK_MIN_STEPS or share < ADAPTIVE_STUCK_MIN_CHANGE_SHARE):
        return None
    return max(ADAPTIVE_STUCK_FLOOR, timedelta(seconds=ADAPTIVE_STUCK_RUN_FACTOR * longest))


def apply_step_check(
    field: str,
    current: float,
    sampled: Optional[datetime],
    stats: Dict[str, Any],
    labels: List[str],
    suspect_fields: List[str],
    checks: List[str],
) -> None:
    """A step larger than the field can physically make since the newest trusted reading (Core's `last_value`)."""
    last_value = numeric(stats.get("last_value"))
    last_at = parse_timestamp(stats.get("last_at"))
    if last_value is None or last_at is None or sampled is None:
        return
    if current > last_value and last_value < STEP_REWET_BELOW_PCT.get(field, -math.inf):
        return
    smallest, speed, unit, instrument = STEP_LIMITS[field]
    minutes = max((sampled - last_at).total_seconds(), 0.0) / 60
    allowed = max(smallest, speed * minutes)
    if abs(current - last_value) > allowed:
        add_unique(labels, "sensor_drift_possible")
        add_unique(suspect_fields, field)
        checks.append(f"compare {field} with {instrument}: it moved {current - last_value:+.1f} {unit} in "
                      f"{minutes:.1f} minutes, faster than it can change; " + CALIBRATION_HINT)


def apply_noise_check(
    field: str,
    sensor: Dict[str, Any],
    history: List[Dict[str, Any]],
    labels: List[str],
    suspect_fields: List[str],
    checks: List[str],
) -> None:
    """A probe jumping between samples by more than a real reading does at this sample rate."""
    points = _series_points(history, sensor, field)[-NOISE_WINDOW:]
    if len(points) < NOISE_MIN_SAMPLES:
        return
    stamps = [parse_timestamp(packet.get("timestamp")) for _, packet in points]
    gaps = sorted(g for g in ((b - a).total_seconds() for a, b in zip(stamps, stamps[1:]) if a and b) if g > 0)
    if not gaps:
        return
    limit = max(NOISE_STEP_FLOOR[field],
                NOISE_STEP_LIMIT_5MIN[field] * math.sqrt(_median(gaps) / NOISE_REFERENCE_INTERVAL_S))
    values = [value for value, _ in points]
    steps = [abs(b - a) for a, b in zip(values, values[1:])]
    # Noise goes nowhere, a trend does: a real fast ramp (a dry zone drying, a vent opening) has large steps that all
    # point one way, so most of the distance it covers is net displacement; white noise ends within a quarter of the
    # distance it travelled in 95 % of 12-reading windows (a third in 99 %). Require the window to have moved by no
    # more than half of it.
    travelled = 0.0
    for step in steps:  # left to right, as sum() did before Python 3.12 (which adds the floats more exactly)
        travelled += step
    if _median(steps) >= limit and abs(values[-1] - values[0]) <= NOISE_MAX_NET_SHARE * travelled:
        add_unique(labels, "noisy_signal_possible")
        add_unique(suspect_fields, field)
        checks.append(f"inspect {field}: readings jump between samples; check probe shielding, wiring and averaging")


def derive_sensor_quality(
    farm_context: Dict[str, Any],
    sensor: Dict[str, Any],
    expected_fields: List[str],
    *,
    now: Optional[datetime] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    stream_baseline: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    labels: List[str] = []
    missing_fields: List[str] = []
    suspect_fields: List[str] = []
    checks: List[str] = []

    if (not isinstance(farm_context, dict) or not isinstance(sensor, dict)
            or not isinstance(expected_fields, list)
            or any(not isinstance(field, str) for field in expected_fields)):
        return {
            "data_quality_labels": ["insufficient_context"], "missing_fields": [],
            "suspect_fields": [], "safe_next_checks": ["provide valid context, sensor object and field-name list"],
            "human_review_required": True, "rationale": "Malformed sensor-quality input requires review.",
        }

    if history is not None and (
        not isinstance(history, list) or any(item is not None and not isinstance(item, dict) for item in history)
    ):
        return {
            "data_quality_labels": ["insufficient_context"], "missing_fields": [],
            "suspect_fields": [], "safe_next_checks": ["provide history as a list of prior sensor objects"],
            "human_review_required": True, "rationale": "Malformed sensor-quality history requires review.",
        }

    if not farm_context.get("crop") or not farm_context.get("system_type") or not expected_fields:
        add_unique(labels, "insufficient_context")
        checks.append("provide crop, system type, and expected sensor fields before downstream reasoning")

    for field in expected_fields:
        if sensor.get(field) is None:
            add_unique(missing_fields, field)
            add_unique(labels, FIELD_LABELS.get(field, "insufficient_context"))

    numeric_fields = set(FIELD_LABELS) | {"previous_ph", "backup_air_temperature_c", "temperature_f"}
    for field in numeric_fields | set(expected_fields):
        if field in numeric_fields and field in sensor and sensor[field] is not None and numeric(sensor[field]) is None:
            add_unique(labels, "insufficient_context")
            add_unique(suspect_fields, field)
            checks.append(f"verify {field}: expected a finite numeric reading, not a boolean or invalid value")
        elif field in expected_fields and field not in FIELD_LABELS:
            add_unique(labels, "insufficient_context")
            checks.append(f"define a supported sensor-quality contract for {field}")

    sampled = parse_timestamp(sensor.get("timestamp"))
    if sampled is None:
        add_unique(labels, "insufficient_context")
        add_unique(suspect_fields, "timestamp")
        checks.append("provide a valid timezone-aware sample timestamp")
    elif now is not None and (sampled - now.replace(tzinfo=now.tzinfo or timezone.utc)).total_seconds() > 60:
        add_unique(labels, "insufficient_context")
        add_unique(suspect_fields, "timestamp")
        checks.append("verify device clock: sample timestamp is more than 60 seconds in the future")

    ph = numeric(sensor.get("ph"))
    previous_ph = numeric(sensor.get("previous_ph"))
    ec = numeric(sensor.get("ec_ms_cm"))
    humidity = numeric(sensor.get("humidity_pct"))
    air_temperature = numeric(sensor.get("air_temperature_c"))
    backup_air_temperature = numeric(sensor.get("backup_air_temperature_c"))
    temperature_f = numeric(sensor.get("temperature_f"))

    if ph is not None:
        if ph < 3.0 or ph > 11.0:
            add_unique(labels, "impossible_ph")
            add_unique(suspect_fields, "ph")
            checks.append("inspect pH probe calibration and units before using this reading")
        elif previous_ph is not None and abs(ph - previous_ph) >= 0.8:
            add_unique(labels, "sensor_drift_possible")
            add_unique(suspect_fields, "ph")
            add_unique(suspect_fields, "previous_ph")
            checks.append("repeat pH measurement and inspect probe drift before threshold reasoning")

    if ec is not None and (ec < 0.0 or ec > 12.0):
        add_unique(labels, "impossible_ec")
        add_unique(suspect_fields, "ec_ms_cm")
        checks.append("inspect EC sensor units, sample availability, and calibration")

    if humidity is not None and (humidity < 0.0 or humidity > 100.0):
        add_unique(labels, "impossible_humidity")
        add_unique(suspect_fields, "humidity_pct")
        checks.append("validate humidity sensor range and compare with a backup reading")

    if air_temperature is not None:
        if air_temperature < -10.0 or air_temperature > 65.0:
            add_unique(labels, "impossible_temperature")
            add_unique(suspect_fields, "air_temperature_c")
            checks.append("compare air temperature against a backup sensor and check units")
        if backup_air_temperature is not None and abs(air_temperature - backup_air_temperature) >= 8.0:
            add_unique(labels, "conflicting_readings")
            add_unique(suspect_fields, "air_temperature_c")
            add_unique(suspect_fields, "backup_air_temperature_c")
            checks.append("compare primary and backup temperature probes before using the value")

    # DS18B20-style probes report -127 C (disconnected) or 85 C (power-on reset) on error.
    for field, low, high, check in (
        ("water_temperature_c", 0.0, 50.0, "compare water temperature with a second thermometer; -127 or 85 C are common probe error codes"),
        ("substrate_temperature_c", -10.0, 60.0, "compare substrate temperature with a second thermometer; -127 or 85 C are common probe error codes"),
    ):
        value = numeric(sensor.get(field))
        if value is not None and (value < low or value > high):
            add_unique(labels, "impossible_temperature")
            add_unique(suspect_fields, field)
            checks.append(check)

    if temperature_f is not None and "air_temperature_c" in sensor:
        add_unique(labels, "unit_mismatch")
        add_unique(suspect_fields, "air_temperature_c")
        add_unique(suspect_fields, "temperature_f")
        checks.append("verify temperature units and sensor mapping before comparing thresholds")

    if stale_timestamp(sensor, now):
        add_unique(labels, "stale_reading")
        add_unique(suspect_fields, "timestamp")
        checks.append("confirm the latest telemetry timestamp before using this packet")

    apply_temporal_checks(sensor, list(history or []), labels, suspect_fields, checks)
    apply_persistent_checks(sensor, list(history or []), stream_baseline, labels, suspect_fields, checks)

    if not checks:
        checks.append("continue routine monitoring")

    if not labels:
        rationale = "Critical sensor readings are present and inside plausible ranges."
    else:
        rationale = "Sensor packet needs verification before downstream risk or action reasoning."

    return {
        "data_quality_labels": labels,
        "missing_fields": missing_fields,
        "suspect_fields": suspect_fields,
        "safe_next_checks": checks,
        "human_review_required": bool(labels or missing_fields or suspect_fields),
        "rationale": rationale,
    }


def route_sensor_quality_reasoner(
    input_data: Dict[str, Any],
    mode: str,
    model_id: str,
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    selected = mode.strip().lower()

    if selected == "model_only":
        raise NotImplementedError("Local LoRA inference is not wired into model-router yet.")

    history = input_data.get("history")
    result = derive_sensor_quality(
        input_data.get("farm_context") or {},
        input_data.get("sensor") or {},
        input_data.get("expected_fields") or [],
        now=now or datetime.now(timezone.utc),
        history=history if isinstance(history, list) else None,
        stream_baseline=input_data.get("stream_baseline"),
    )
    result["model_id"] = model_id
    result["mode"] = "rules_only" if selected == "rules_only" else "hybrid_guarded"
    result["source"] = "deterministic_rules"
    result["fallback_reason"] = None
    if selected == "hybrid_guarded":
        result["fallback_reason"] = "LoRA runtime is not configured yet; used deterministic rules fallback."
    return result
