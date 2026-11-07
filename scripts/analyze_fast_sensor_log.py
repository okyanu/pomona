#!/usr/bin/env python3
"""Check Pomona's 30-second sensor limits on a real fast log (standard library only).

The log is "Identifying Uncertainties In Air Temperature Data Of An Indoor Farming System" (University of Florida,
Mendeley Data, CC BY 4.0, https://data.mendeley.com/datasets/rmvgvkg8vn): a lettuce growth chamber with four
recirculating nutrient-solution loops (pH and EC probes) and air temperature and humidity at four positions, logged
every 10 seconds for 3 months. It has no fault labels. Download it, unpack it, and pass the folder holding the daily
`*.txt` files (the `*.csv` files are a separate 5-second reference sensor and are not read).

    python3 scripts/analyze_fast_sensor_log.py PATH/TO/DATASET_FOLDER

It prints two tables, about 2 minutes on a laptop (it is not part of any make target; docs/FAST_SAMPLING_NOISE_DESIGN.md
and docs/SENSOR_TEMPORAL_CHECKS.md describe what they mean):

  1. air temperature, humidity and pH at 30 seconds (every third row): the real step size, the allowances and noise
     limits Pomona uses at 30 seconds, and how many 12-reading windows they would flag;
  2. EC at 10, 30, 60 and 90 seconds, every starting offset of each subsampling: the largest window median step per
     probe and how many windows reach the fixed EC noise limit (0.20 mS/cm).

A window is 12 readings (11 steps). It is flagged when its median step is at or above the limit and the window has not
simply moved one way (its net movement is at most half of the distance it travelled): the same rule as
`apply_noise_check` in services/model-router/app/sensor_quality.py. The limits below mirror that file; they are copied
here because this script uses no Pomona code. A stream is cut into separate runs wherever two neighbouring readings are
more than 1.5 sampling intervals apart, and readings that are missing or not finite are dropped.
"""
import csv
import glob
import math
import os
import sys
from array import array
from datetime import datetime, timedelta

WINDOW = 12
NET_SHARE = 0.5
EC_LIMIT = 0.20  # mS/cm, NOISE_FIXED_LIMIT["ec_ms_cm"][0]
# (label, columns, step allowance or None, 5-minute noise limit, floor): sensor_quality.py STEP_LIMITS / NOISE_*
FIELDS = (
    ("Air temperature (C)", ("temp_sensor", "temp_upper", "temp_intake", "temp_outflow"), 3.0, 2.0, 0.4),
    ("Humidity (%RH)", ("hum_sensor", "hum_upper", "hum_intake", "hum_outflow"), 12.0, 10.0, 3.0),
    ("pH", ("pH_LNS_1", "pH_LNS_2", "pH_LNS_3", "pH_LNS_4"), None, 0.5, 0.1),
)
EC_COLUMNS = ("EC_LNS_1", "EC_LNS_2", "EC_LNS_3", "EC_LNS_4")
EC_RATES = ((10, 1), (30, 3), (60, 6), (90, 9))  # (seconds, every how many 10-second rows)
NOISE_REFERENCE_INTERVAL_S = 300.0
EPOCH = datetime(1970, 1, 1)


def median(values):
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def quantile(ordered, share):
    return ordered[min(len(ordered) - 1, int(share * len(ordered)))]


def load(folder):
    """All daily `*.txt` files of the folder: (seconds since 1970 as an array, {column: array of floats, nan if missing})."""
    wanted = {c for _, cols, *_ in FIELDS for c in cols} | set(EC_COLUMNS)
    pairs = []  # (time, {column: text})
    for path in sorted(glob.glob(os.path.join(folder, "[0-9]*.txt"))):
        with open(path, newline="") as handle:
            reader = csv.reader(handle)
            header = [h.strip() for h in next(reader, [])]
            index = {name: i for i, name in enumerate(header) if name in wanted}
            for row in reader:
                if len(row) < len(header):
                    continue
                try:
                    stamp = (datetime.strptime(row[0].strip(), "%Y-%m-%d %H:%M:%S") - EPOCH).total_seconds()
                except ValueError:
                    continue  # a header repeated inside a file, or a broken line
                pairs.append((stamp, {name: row[i] for name, i in index.items()}))
    if not pairs:
        sys.exit(f"no readable rows in {folder}/[0-9]*.txt")
    pairs.sort(key=lambda p: p[0])
    times = array("d", (p[0] for p in pairs))
    columns = {}
    for name in sorted(wanted):
        values = array("d")
        for _, cells in pairs:
            try:
                value = float(cells[name])
            except (KeyError, ValueError):
                value = math.nan
            values.append(value if math.isfinite(value) else math.nan)
        columns[name] = values
    return times, columns


def runs(times, every, phase):
    """Index ranges (start, stop) of the readings phase, phase + every, ... that form unbroken runs."""
    limit = 1.5 * every * 10.0
    out, start, last = [], phase, len(times)
    for i in range(phase, last - every, every):
        if times[i + every] - times[i] > limit:
            out.append((start, i + 1))
            start = i + every
    out.append((start, last))
    return out


def judge(values, limit, steps_out=None):
    """(windows, largest window median step, windows flagged at limit) for one unbroken run of readings."""
    steps = [abs(b - a) for a, b in zip(values, values[1:])]
    if steps_out is not None:
        steps_out.extend(steps)
    windows = largest = flagged = 0
    for i in range(len(values) - WINDOW + 1):
        part = steps[i:i + WINDOW - 1]
        mid = median(part)
        windows += 1
        if mid > largest:
            largest = mid
        if limit is not None and mid >= limit and abs(values[i + WINDOW - 1] - values[i]) <= NET_SHARE * sum(part):
            flagged += 1
    return windows, largest, flagged


def analyse(times, column, every, phase, limit, scale=1.0, steps_out=None):
    windows = largest = flagged = 0
    for start, stop in runs(times, every, phase):
        values = [v * scale for v in column[start:stop:every] if v == v]
        w, m, f = judge(values, limit, steps_out)
        windows, largest, flagged = windows + w, max(largest, m), flagged + f
    return windows, largest, flagged


def span(values, digits):
    low, high = min(values), max(values)
    return f"{low:.{digits}f}" if f"{low:.{digits}f}" == f"{high:.{digits}f}" else f"{low:.{digits}f}-{high:.{digits}f}"


def table(headers, rows):
    widths = [max(len(str(r[i])) for r in [headers] + rows) for i in range(len(headers))]
    for row in [headers, ["-" * w for w in widths]] + rows:
        print("| " + " | ".join(str(c).ljust(w) for c, w in zip(row, widths)) + " |")


def main(argv):
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        sys.exit(__doc__)
    times, columns = load(argv[1])
    gaps = sorted(b - a for a, b in zip(times, times[1:]))
    first, last = (EPOCH + timedelta(seconds=times[i]) for i in (0, -1))
    print(f"{len(times):,} rows, {first:%Y-%m-%d} to {last:%Y-%m-%d}; median interval {median(gaps):g} s, "
          f"{sum(1 for g in gaps if 9 <= g <= 11) / len(gaps):.1%} of steps 9-11 s, {sum(1 for g in gaps if g > 60)} gaps over a minute")

    print("\nAir, humidity, pH at 30 s (every third row, phase 0; 12-reading windows; one-way moves excluded)\n")
    rows, detail, skipped = [], [], []
    for label, cols, step_limit, limit_5min, floor in FIELDS:
        limit = max(floor, limit_5min * math.sqrt(30.0 / NOISE_REFERENCE_INTERVAL_S))
        got = {}
        for col in cols:
            steps = []
            windows, largest, flagged = analyse(times, columns[col], 3, 0, limit, steps_out=steps)
            if not steps:
                continue
            steps.sort()
            over = sum(1 for s in steps if s > step_limit) if step_limit is not None else None
            got[col] = (quantile(steps, 0.9999), largest, windows, flagged, over, max(steps))
            detail.append(f"  {col:13} windows {windows:,} flagged {flagged}; step p99.99 {got[col][0]:.3f}, max step "
                          f"{got[col][5]:.3f}" + (f", steps over {step_limit:g}: {over}" if over is not None else "")
                          + f"; largest window median {largest:.3f}")
        most = max(g[2] for g in got.values())
        main_cols = {c: g for c, g in got.items() if g[2] >= most / 2}  # a probe that logs nan most of the time is left out
        skipped += [c for c in got if c not in main_cols]
        rows.append([label, span([g[0] for g in main_cols.values()], 2), f"{step_limit:g}" if step_limit is not None else "-",
                     span([g[1] for g in main_cols.values()], 2), f"{limit:.3f}",
                     f"{sum(g[3] for g in got.values())} of {most:,}"])
    table(["Field (4 positions or probes)", "Real 30 s step, p99.99", "Jump limit", "Largest real window median",
           "Noise limit at 30 s", "Windows flagged"], rows)
    if skipped:
        print(f"(the table leaves out {', '.join(skipped)}: those columns hold readings in under half of the rows, but they are judged and listed below;\n windows flagged = flagged in any column, out of the fullest column's windows)")
    print("\nPer column:")
    print("\n".join(detail))

    print(f"\nEC at every rate and phase (all offsets of each subsampling; 12-reading windows; flagged at {EC_LIMIT:.2f} mS/cm)\n")
    rows = []
    for seconds, every in EC_RATES:
        worst, flagged, windows = [0.0] * 4, [0] * 4, 0
        for phase in range(every):
            for k, col in enumerate(EC_COLUMNS):
                w, largest, f = analyse(times, columns[col], every, phase, EC_LIMIT, scale=0.001)
                worst[k], flagged[k] = max(worst[k], largest), flagged[k] + f
                if k == 0:
                    windows += w
        rows.append([f"{seconds} s", every, ", ".join(f"{x:.3f}" for x in worst),
                     ", ".join(str(f) for f in flagged) if any(flagged) else "0"])
        print(f"  {seconds} s: {windows:,} windows per probe", file=sys.stderr)
    table(["Rate", "Phases", "Largest window median per probe (mS/cm)", f"Flagged at {EC_LIMIT:.2f}"], rows)


if __name__ == "__main__":
    main(sys.argv)
