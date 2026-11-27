#!/usr/bin/env python3
"""Evidence for the slow-drift pair check (docs/design/slow-drift-pair-check.md, Design 5).

  analyze_pair_drift.py <UF folder> <AGC2 extracted folder> [--json PATH]

Standard library only; not part of any make target. It prints the doc's evidence tables again so a reader can check
them, and runs the real pair rule (`pair_reference` in services/core/app/trusted_baseline.py, loaded by path, never
copied) over the AGC2 slab probes at the full 5-minute interval.

  UF hydroponic chamber (Mendeley rmvgvkg8vn): needs the owner's yes to download, so it is a stub here. The folder
      is checked; if it is missing the script says so and goes on. The doc's UF numbers stand as measured for v2.
  AGC2 cherry-tomato greenhouse, per compartment (GrodanSens.csv, 5 min): substrate moisture of slab 1 and slab 2.
      1. The doc's v2 tables: one probe against its own trailing 2 h median, slab 1 minus slab 2 (same row, lag 0)
         against its own trailing 2 h median, flagged readings (|difference - trailing median| >= 8 %, flagged
         readings kept out of the median), cards (3 flagged readings in a row).
      2. The real rule: both slabs as two devices of one zone through `pair_reference`, each device judged when it
         reads, a flagged reading vetoed so it leaves the offsets and the partner role, no other check, no
         calibration, window 7200 s, no lapse. Three clock cases (see SCENARIOS).
      3. The bound (Design 5): a full-interval run that flags more than 1.5x the worst lag-0 count, or that adds cards
         on a compartment that had none, prints BOUND EXCEEDED and the script exits 2 after printing everything.

Substrate temperature is printed for reference only; it is not paired in the product (Design 1).
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import statistics
import sys
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
BASELINE_MODULE = ROOT / "services/core/app/trusted_baseline.py"
COMPARTMENTS = ("AICU", "Automatoes", "Digilog", "IUACAAS", "Reference", "TheAutomators")
FIELD = "substrate_moisture_pct"
LIMIT = 8.0  # the router's PAIR_DRIFT_LIMITS for both moisture names
WINDOW_S = 7200.0
MIN_N = 12  # the real rule's PAIR_MIN_N; the lag-0 reference needs the same number of earlier readings
CARD_RUN = 3
INTERVAL_S = 300  # AGC2 sampling interval
BOUND_FACTOR = 1.5
ROWS_KEPT = 40  # per device: window (24 rows at 5 min) + the 13 the rule's rhythm walk needs
UF_SKIPPED = ("UF skipped: folder not found (download needs the owner's yes; the doc's UF numbers stand as measured "
              "for v2)")
UF_STUB = ("UF not implemented without the data. The doc expects: four positions in one chamber (air temperature, "
           "humidity), 10 s data; partner lags 0, 10 and 20 s at a 30 s cadence; plus a full interval of lag at 30 s, "
           "and again after resampling to 5 min.")
UF_SUFFIXES = {".csv", ".xlsx", ".xls", ".txt", ".tsv"}
EXPECTED = {
    "own p99.99 (all but Digilog)": "6.0-12.7", "own p99.99 Digilog": "80",
    "pair p99.99 (all but Digilog)": "3.2-6.3", "pair max (all but Digilog)": "6.7",
    "pair p99.99 / max Digilog": "24.5 / 91.8", "flagged": "0 in five compartments; Digilog 47 of 45,311 (0.10 %)",
    "cards": "Digilog 4, others 0",
}
# (key, label, clock case). `shift_s` moves slab 2's sample times; negative means earlier. Slab 1 keeps its times.
SCENARIOS = (
    ("row_earlier", "slab 2 stamped one full row (300 s) earlier", -INTERVAL_S),
    ("one_second_earlier", "slab 2 stamped 1 s earlier", -1),
    ("aligned", "same stamps, both devices (aligned clocks: each sees the other's previous reading, 300 s)", 0),
)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --- reading GrodanSens.csv ---

def _number(text: Optional[str]) -> Optional[float]:
    try:
        value = float((text or "").strip())
    except ValueError:
        return None
    return value if math.isfinite(value) else None


def read_slabs(compartment: Path, column_1: str, column_2: str) -> Tuple[List[tuple], List[tuple]]:
    """(time, value) lists, oldest first, for the two slab columns. Excel days become UTC datetimes rounded to the
    minute (the file stores 5 decimals of a day, which is 0.9 s of noise). NaN cells are dropped, so a probe's list
    holds only the rows where it reported. A repeated time keeps the last row."""
    one: Dict[datetime, float] = {}
    two: Dict[datetime, float] = {}
    with (compartment / "GrodanSens.csv").open(newline="") as handle:
        for row in csv.DictReader(handle, skipinitialspace=True):
            days = _number(row.get("%time") or row.get("%Time"))
            if days is None:
                continue
            when = datetime(1899, 12, 30, tzinfo=timezone.utc) + timedelta(days=days)
            when = when.replace(second=0, microsecond=0) + timedelta(minutes=round((when.second + when.microsecond / 1e6) / 60))
            for target, column in ((one, column_1), (two, column_2)):
                value = _number(row.get(column))
                if value is not None:
                    target[when] = value
    return sorted(one.items()), sorted(two.items())


# --- statistics ---

def percentile(values: List[float], q: float) -> float:
    """Linear-interpolated percentile of `values` (q in [0, 1])."""
    ordered = sorted(values)
    if not ordered:
        return float("nan")
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def trailing_deviation(series: Iterable[tuple], limit: Optional[float] = None) -> Dict[str, Any]:
    """How far each reading leaves the median of the earlier readings of the last 2 h (at least MIN_N of them).

    With `limit`, a reading whose deviation is at least `limit` is flagged and kept out of the median (as Core
    keeps vetoed readings out of its reference). Without it every reading goes in. Returns the absolute deviations,
    the flagged counts and the cards (CARD_RUN flagged readings in a row; a longer run is still one card). `series`
    holds only the rows that reported (NaN cells are dropped), and a run is counted over that list, so a gap in
    time does not end it; any reading that is not flagged does."""
    recent: deque = deque()  # (time, value) of the readings the median uses
    deviations: List[float] = []
    judged = flagged = cards = run = 0
    for when, value in series:
        while recent and (when - recent[0][0]).total_seconds() > WINDOW_S:
            recent.popleft()
        if len(recent) >= MIN_N:
            deviation = abs(value - statistics.median(v for _, v in recent))
            deviations.append(deviation)
            judged += 1
            if limit is not None and deviation >= limit:
                flagged += 1
                run += 1
                if run == CARD_RUN:
                    cards += 1
                continue  # a flagged reading stays out of the median
        run = 0
        recent.append((when, value))
    return {"deviations": deviations, "judged": judged, "flagged": flagged, "cards": cards}


def summary(deviations: List[float]) -> Dict[str, Any]:
    if not deviations:
        return {"n": 0, "p9999": None, "max": None}
    return {"n": len(deviations), "p9999": round(percentile(deviations, 0.9999), 2), "max": round(max(deviations), 2)}


def pair_difference(one: List[tuple], two: List[tuple]) -> List[tuple]:
    """slab 1 minus slab 2 on the rows where both reported (same row, lag 0)."""
    other = dict(two)
    return [(when, value - other[when]) for when, value in one if when in other]


def lag0_table(compartment: Path) -> Dict[str, Any]:
    """The doc's v2 AGC2 table for one compartment: moisture (judged) and temperature (for reference)."""
    out: Dict[str, Any] = {}
    for name, columns, limit in (("moisture", ("WC_slab1", "WC_slab2"), LIMIT),
                                 ("temperature", ("t_slab1", "t_slab2"), None)):
        one, two = read_slabs(compartment, *columns)
        diff = pair_difference(one, two)
        own = [trailing_deviation(series)["deviations"] for series in (one, two)]
        pair = trailing_deviation(diff, limit)
        out[name] = {
            "readings_slab1": len(one), "readings_slab2": len(two), "pair_rows": len(diff),
            "own_slab1": summary(own[0]), "own_slab2": summary(own[1]),
            "pair": summary(pair["deviations"]),
            "flagged": pair["flagged"] if limit is not None else None,
            "cards": pair["cards"] if limit is not None else None,
            "judged": pair["judged"],
        }
    return out


# --- the real rule ---

def run_pair_rule(baseline, one: List[tuple], two: List[tuple], shift_s: int) -> Dict[str, Any]:
    """Slab 1 and slab 2 as two devices of one zone through `pair_reference`. Readings in time order (slab 1 first
    on a tie; the rule only uses strictly earlier partner readings, so the order of a tie does not matter). Each
    device is judged when it reads, with its earlier rows and the other device's rows; a flagged reading has its
    field in `vetoed_fields`, so it leaves the offsets and the partner role."""
    shift = timedelta(seconds=shift_s)
    events = [(when, 0, value) for when, value in one] + [(when + shift, 1, value) for when, value in two]
    events.sort(key=lambda e: (e[0], e[1]))
    names = ("slab-1", "slab-2")
    rows: List[deque] = [deque(maxlen=ROWS_KEPT), deque(maxlen=ROWS_KEPT)]
    last: List[Optional[float]] = [None, None]
    stats = [{"readings": 0, "judged": 0, "flagged": 0, "cards": 0, "skipped_fast": 0, "run": 0} for _ in names]
    fast_step = baseline.PAIR_FAST_STEP[FIELD]
    for when, who, value in events:
        current = {"device_id": names[who], "timestamp": when, FIELD: value}
        entry = baseline.pair_reference(list(rows[who]), list(rows[1 - who]), FIELD, None, current, WINDOW_S, None)
        s = stats[who]
        s["readings"] += 1
        flagged = False
        if entry is not None:
            s["judged"] += 1
            flagged = abs((value - entry["partner_value"]) - entry["offset"]) >= LIMIT
        elif last[who] is not None and abs(value - last[who]) >= fast_step:
            s["skipped_fast"] += 1  # counted with the rule's own threshold; the rule returns None for it
        if flagged:
            s["flagged"] += 1
            s["run"] += 1
            if s["run"] == CARD_RUN:
                s["cards"] += 1
        else:
            s["run"] = 0
        rows[who].append({"device_id": names[who], "timestamp": when, FIELD: value,
                          "vetoed_fields": [FIELD] if flagged else []})
        last[who] = value
    for s in stats:
        del s["run"]
    return {"devices": {names[i]: stats[i] for i in range(2)},
            "judged": sum(s["judged"] for s in stats), "flagged": sum(s["flagged"] for s in stats),
            "cards": sum(s["cards"] for s in stats), "skipped_fast": sum(s["skipped_fast"] for s in stats)}


# --- output ---

def fmt(value: Any, digits: int = 1) -> str:
    return "-" if value is None else (f"{value:.{digits}f}" if isinstance(value, float) else str(value))


def table(header: List[str], body: List[List[str]]) -> str:
    widths = [max(len(str(r[i])) for r in [header] + body) for i in range(len(header))]
    lines = ["  ".join(str(c).ljust(w) for c, w in zip(header, widths)).rstrip()]
    lines.append("  ".join("-" * w for w in widths))
    lines += ["  ".join(str(c).ljust(w) for c, w in zip(r, widths)).rstrip() for r in body]
    return "\n".join(lines)


def uf_part(folder: Path) -> Dict[str, Any]:
    """UF hydroponic chamber. A stub: the file format is not known here (the data is not on this machine)."""
    usable = folder.is_dir() and any(p.suffix.lower() in UF_SUFFIXES for p in folder.rglob("*") if p.is_file())
    if not usable:
        print(UF_SKIPPED)
        return {"status": "skipped", "reason": "folder not found or no usable files"}
    print(UF_STUB)
    return {"status": "not implemented without the data"}


def find_compartments(folder: Path) -> List[Path]:
    if (folder / "GrodanSens.csv").is_file():
        return [folder]
    return [folder / name for name in COMPARTMENTS if (folder / name / "GrodanSens.csv").is_file()]


def bound_check(lag0: Dict[str, Any], full: Dict[str, Dict[str, Any]]) -> List[str]:
    """Design 5: a full-interval run flagging more than BOUND_FACTOR x the worst lag-0 count, or adding cards on a
    compartment that had none, exceeds the bound. Returns the problems (empty: within the bound)."""
    problems = []
    worst = max((v["moisture"]["flagged"] for v in lag0.values()), default=0)
    limit = worst * BOUND_FACTOR
    for key, per_compartment in full.items():
        for name, result in per_compartment.items():
            if result["flagged"] > limit:
                problems.append(f"{key} / {name}: {result['flagged']} flagged readings, over {BOUND_FACTOR}x the worst "
                                f"lag-0 count ({worst}; limit {limit:g})")
            if result["cards"] > 0 and lag0[name]["moisture"]["cards"] == 0:
                problems.append(f"{key} / {name}: {result['cards']} cards where lag 0 had none")
    return problems


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1].strip())
    parser.add_argument("uf_folder", type=Path, help="UF hydroponic chamber folder (may be missing)")
    parser.add_argument("agc2_folder", type=Path, help="AGC2 extracted folder (one folder per compartment)")
    parser.add_argument("--json", type=Path, default=None, help="write the numbers here")
    args = parser.parse_args(argv)

    print("Slow-drift pair check: evidence (docs/design/slow-drift-pair-check.md, Design 5)")
    print(f"Rule: pair_reference from {BASELINE_MODULE.relative_to(ROOT)} (loaded by path); moisture limit {LIMIT:g} %, "
          f"window {WINDOW_S:g} s, MIN_N {MIN_N}, no calibrations, no lapse, no other check.")
    print()
    report: Dict[str, Any] = {"uf": uf_part(args.uf_folder)}
    print()

    compartments = find_compartments(args.agc2_folder)
    if not compartments:
        print(f"AGC2: no GrodanSens.csv found under {args.agc2_folder}; its part is required.", file=sys.stderr)
        return 1
    baseline = load_module("trusted_baseline_pair_drift", BASELINE_MODULE)

    lag0: Dict[str, Any] = {c.name: lag0_table(c) for c in compartments}
    report["agc2_lag0"] = lag0

    print("AGC2 substrate moisture, slab 1 minus slab 2, same row (lag 0), 5 min (the doc's v2 table)")
    print("'own' = one probe vs its own trailing 2 h median; 'pair' = the difference vs its own trailing 2 h median.")
    header = ["Compartment", "rows (both)", "own1 p99.99", "own2 p99.99", "pair p99.99", "pair max", "flagged", "cards"]
    body = []
    for name, v in lag0.items():
        m = v["moisture"]
        body.append([name, str(m["pair_rows"]), fmt(m["own_slab1"]["p9999"]), fmt(m["own_slab2"]["p9999"]),
                     fmt(m["pair"]["p9999"]), fmt(m["pair"]["max"]), f"{m['flagged']} of {m['judged']}", str(m["cards"])])
    print(table(header, body))
    print("Doc: own 6.0-12.7 % (Digilog 80); pair 3.2-6.3 %, max 6.7 (Digilog 24.5, max 91.8); flagged 0 in five "
          "compartments, Digilog 47 of 45,311 (0.10 %), 4 cards.")
    print()
    print("AGC2 substrate temperature, for reference only (not paired, not judged)")
    body = []
    for name, v in lag0.items():
        t = v["temperature"]
        body.append([name, str(t["pair_rows"]), fmt(t["own_slab1"]["p9999"]), fmt(t["own_slab2"]["p9999"]),
                     fmt(t["pair"]["p9999"]), fmt(t["pair"]["max"])])
    print(table(["Compartment", "rows (both)", "own1 p99.99", "own2 p99.99", "pair p99.99", "pair max"], body))
    print("Doc: own 1.8-3.7 degC; pair 0.6-2.6 degC (Digilog max 4.7).")
    print()

    moisture = {c.name: read_slabs(c, "WC_slab1", "WC_slab2") for c in compartments}
    full: Dict[str, Dict[str, Any]] = {}
    for key, label, shift_s in SCENARIOS:
        full[key] = {name: run_pair_rule(baseline, one, two, shift_s) for name, (one, two) in moisture.items()}
        print(f"AGC2 moisture through pair_reference: {label}")
        header = ["Compartment", "device", "readings", "judged", "flagged", "cards", "skipped (fast change)"]
        body = []
        for name, result in full[key].items():
            for device, s in result["devices"].items():
                body.append([name, device, str(s["readings"]), str(s["judged"]), str(s["flagged"]), str(s["cards"]),
                             str(s["skipped_fast"])])
            body.append([name, "both", "", str(result["judged"]), str(result["flagged"]), str(result["cards"]),
                         str(result["skipped_fast"])])
        print(table(header, body))
        print()
    report["agc2_pair_rule"] = {key: {"label": label, "shift_s": shift_s, "compartments": full[key]}
                                for key, label, shift_s in SCENARIOS}

    problems = bound_check(lag0, full)
    report["bound"] = {"exceeded": bool(problems), "problems": problems, "factor": BOUND_FACTOR,
                       "worst_lag0_flagged": max(v["moisture"]["flagged"] for v in lag0.values())}
    if problems:
        print("BOUND EXCEEDED (Design 5: stop and report before going on)")
        for problem in problems:
            print(f"  - {problem}")
    else:
        print("Bound (Design 5): within it. Full-interval runs flag at most "
              f"{BOUND_FACTOR}x the worst lag-0 count and add no cards on a compartment that had none.")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2, default=str) + "\n")
        print(f"numbers written to {args.json}")
    return 2 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
