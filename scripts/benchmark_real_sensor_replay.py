"""Replay real third-party sensor logs through the deterministic sensor-quality rules.

Unlike scripts/benchmark_sensor_fault_replay.py (synthetic, annotated), these logs
have no fault annotations. The report counts labels per dataset and checks a few
regression guards learned from them. Raw files stay local in datasets/raw/ (see
datasets/sources/*.yaml); a missing dataset is reported as skipped, not failed.

Each packet sees the previous 11 packets of its stream as history (the dashboard
and Sensor Data Checker window) and is checked at its own sample time.

The "sticky" pass then replays the same logs the way Core's outcome feed does: each packet is also judged
against Core's trusted per-stream reference (services/core/app/trusted_baseline.py, built from the earlier
packets the pipeline did not veto). It reports how many packets the persistent checks (drift from the trusted
level, stuck for too long) add on real data, two ways:

  unattended_no_lapse  as Core behaves by default: a flagged level stays "can't confirm" until a calibration.
                       These logs have no operator, so nobody ever calibrates and every real level shift (a
                       drain EC that moves for good) stays flagged for the rest of the log. The rates are high
                       by construction on historical logs, so they are INFORMATIONAL, not guarded.
  lapse_2h             Core with TRUST_BASELINE_MAX_AGE_S=7200: the reference lapses 2 h after the last trusted
                       reading. Shows what the checks flag on their own (this is where the limits were tuned).

The sticky replays are long (14 of them), so they run in parallel: about 20 minutes on a 12-core machine.

Guards cover what must not regress: the legacy pass, the persistent stuck rates (both ways), the drift rate
with the lapse, and fields that had no persistent flags at all. Exit 1 means a guard failed.

The checks added so that pH/EC freezes, sudden steps in air temperature, humidity, moisture and substrate
temperature, and noisy humidity/air/pH/moisture/substrate-temperature probes are no longer missed (NEW_CHECKS
below) each get a tighter guard: they may flag at most 0.15 % of the real readings of a stream, with and without
the lapse.

Usage: python scripts/benchmark_real_sensor_replay.py [--rules-module PATH]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE_MODULE = ROOT / "services/core/app/trusted_baseline.py"
RAW = ROOT / "datasets/raw"
AQUAPONIC = RAW / "mendeley_aquaponic_pond_iot/pond_iot_2023_raw.csv"
AGC2 = RAW / "4tu_agc2_cherry_tomato/extracted"
HISTORY = 11


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_rules(path: Path):
    return load_module("sensor_quality_under_test", path).derive_sensor_quality


def number(text):
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return None if value != value else value  # NaN -> missing


def aquaponic_packets():
    """Last reading of each 5-minute bucket of the unfiltered log.

    The source logger samples several times a minute; the Pomona cress logger takes one
    unaveraged reading per interval, so one raw reading per 5 minutes is the fair model.

    Timestamps have no zone; the pond is in Indonesia, so +07:00 is assumed. TDS (ppm)
    becomes EC with the DFRobot 0.5 factor: EC mS/cm = TDS * 2 / 1000.
    """
    tz = timezone(timedelta(hours=7))
    buckets = {}
    with AQUAPONIC.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            t = datetime.strptime(row["created_date"], "%m/%d/%Y %H:%M")
            key = t.replace(minute=t.minute - t.minute % 5)
            buckets.setdefault(key, []).append(row)
    for key in sorted(buckets):
        row = buckets[key][-1]
        tds = number(row["TDS"])
        packet = {"timestamp": key.replace(tzinfo=tz).isoformat(), "ph": number(row["water_pH"]),
                  "ec_ms_cm": None if tds is None else round(tds * 2 / 1000, 4),
                  "water_temperature_c": number(row["water_temp"])}
        yield {k: v for k, v in packet.items() if v is not None}


def agc2_packets(compartment: Path):
    """Greenhouse climate + drain + slab sensors, 5-minute rows joined on the Excel time.

    Times are Dutch local; +01:00 is assumed (DST ignored), which only shifts clocks.
    """
    tz = timezone(timedelta(hours=1))
    with (compartment / "GrodanSens.csv").open() as handle:
        slab = {row["%time"].strip(): row for row in csv.DictReader(handle, skipinitialspace=True)}
    with (compartment / "GreenhouseClimate.csv").open() as handle:
        for row in csv.DictReader(handle, skipinitialspace=True):
            key = (row.get("%time") or row.get("%Time")).strip()
            when = datetime(1899, 12, 30) + timedelta(days=float(key))
            when = when.replace(second=0, microsecond=0) + timedelta(minutes=round(when.second / 60))
            s = slab.get(key, {})
            packet = {"timestamp": when.replace(tzinfo=tz).isoformat(),
                      "air_temperature_c": number(row["Tair"]), "humidity_pct": number(row["Rhair"]),
                      "ph": number(row["pH_drain_PC"]), "ec_ms_cm": number(row["EC_drain_PC"]),
                      "substrate_temperature_c": number(s.get("t_slab1")),
                      "substrate_moisture_pct": number(s.get("WC_slab1"))}
            yield {k: v for k, v in packet.items() if v is not None}


def _run(derive, packets, context, fields):
    labels, flagged = Counter(), 0
    history = deque(maxlen=HISTORY)
    for packet in packets:
        now = datetime.fromisoformat(packet["timestamp"])
        out = derive(context, packet, fields, now=now, history=list(history))
        flagged += bool(out["data_quality_labels"])
        labels.update(out["data_quality_labels"])
        history.append(packet)
    return flagged, labels


def replay(derive, packets, context, fields, extra_fields=()):
    """Whole-packet flag count, plus labels per field from single-field streams.

    The rules report labels and suspect fields without pairing them, so each field is
    also replayed alone (its own readings and timestamps) to attribute labels cleanly.
    """
    packets = list(packets)
    flagged, labels = _run(derive, packets, context, fields)
    by_field = {}
    for field in [*fields, *extra_fields]:
        stream = [{"timestamp": p["timestamp"], field: p[field]} for p in packets if field in p]
        field_flagged, field_labels = _run(derive, stream, context, [field])
        by_field[field] = {"packets": len(stream), "flagged": field_flagged, "labels": dict(field_labels.most_common())}
    return {"packets": len(packets), "flagged": flagged, "labels": dict(labels.most_common()), "by_field": by_field}


STICKY_SCAN = 5000  # Core's scan limit (services/core/app/trusted_baseline.py DEFAULT_SCAN_LIMIT)
LAPSE_S = 2 * 3600
UNATTENDED = "unattended: no operator to calibrate"
# Persistent stuck flags were zero here when the limits were chosen; they must stay zero (a new flag on a field or
# compartment that had none is a regression), whichever way the reference lapses.
QUIET = {"mendeley_aquaponic_pond_iot": ["water_temperature_c"],
         "4tu_agc2_cherry_tomato/AICU": ["substrate_temperature_c"],
         "4tu_agc2_cherry_tomato/Automatoes": ["substrate_temperature_c"],
         "4tu_agc2_cherry_tomato/IUACAAS": ["substrate_temperature_c"],
         "4tu_agc2_cherry_tomato/Reference": ["air_temperature_c"],
         "4tu_agc2_cherry_tomato/TheAutomators": ["air_temperature_c"]}


# Persistent checks that close gaps the fake-greenhouse game exposed. Each may flag at most 0.15 % of a real stream's
# readings (the budget the older stuck limits were tuned to), whichever way the reference lapses.
NEW_CHECKS = (("ph", "stuck_value"), ("ec_ms_cm", "stuck_value"), ("air_temperature_c", "sensor_drift_possible"),
              ("air_temperature_c", "noisy_signal_possible"), ("humidity_pct", "noisy_signal_possible"),
              ("humidity_pct", "sensor_drift_possible"), ("substrate_moisture_pct", "sensor_drift_possible"),
              ("substrate_temperature_c", "sensor_drift_possible"), ("ph", "noisy_signal_possible"),
              ("substrate_moisture_pct", "noisy_signal_possible"), ("substrate_temperature_c", "noisy_signal_possible"))
NEW_CHECK_LIMIT = 0.0015
# The unshielded pond pH probe really is noisy: the 11-packet rule calls it so on most readings (a guard below needs
# that), so the persistent noise check agreeing with it is not a false flag.
NEW_CHECK_EXEMPT = {("mendeley_aquaponic_pond_iot", "ph", "noisy_signal_possible")}


def replay_sticky(rules, gate, baseline, packets, context, fields, max_age_s=None):
    """Replay like Core's feed: judge each packet with the trusted reference, veto, feed the verdict back.

    Counts, per field, the packets the persistent checks flag on their own (drift from the trusted level,
    stuck too long) and how many packets end up vetoed. Nothing is ever calibrated here, so with no lapse
    (`max_age_s` None) every flagged level shift stays flagged for the rest of the log.
    """
    persistent, vetoed_count, history, stream, total = Counter(), Counter(), deque(maxlen=HISTORY), [], 0
    for packet in packets:
        now = datetime.fromisoformat(packet["timestamp"])
        prior = list(history)
        ref = baseline.stream_baseline(stream[-STICKY_SCAN:], [], now, baseline.DEFAULT_WINDOW_S, baseline.DEFAULT_MIN_N,
                                       max_age_s)
        out = rules.derive_sensor_quality(context, packet, fields, now=now, history=prior, stream_baseline=ref or None)
        for field, stats in ref.items():  # attribute the persistent flags field by field
            labels, suspects = [], []
            rules.apply_persistent_checks(packet, prior, {field: stats}, labels, suspects, [])
            for label in labels:
                persistent[(field, label)] += 1
        vetoed = gate.apply_sensor_veto(packet, prior, out, fields)[2]["vetoed_fields"]
        vetoed_count.update(vetoed)
        stream.append({**packet, "timestamp": now.astimezone(timezone.utc), "vetoed_fields": vetoed})  # UTC: parsed once
        history.append(packet)
        total += 1
    return {"packets": total, "persistent_flags": {f"{f}:{label}": n for (f, label), n in sorted(persistent.items())},
            "vetoed": dict(vetoed_count.most_common())}


def sticky_worker(job):
    """One sticky replay in its own process (the logs are long: 14 replays run side by side)."""
    rules_path, source, arg, context, fields, max_age_s = job
    rules = load_module("sensor_quality_worker", Path(rules_path))
    gate = load_module("trust_gate_worker", Path(rules_path).parent / "trust_gate.py")
    baseline = load_module("trusted_baseline_worker", BASELINE_MODULE)
    packets = aquaponic_packets() if source == "aquaponic" else agc2_packets(Path(arg))
    return replay_sticky(rules, gate, baseline, packets, context, fields, max_age_s)


def sticky_rate(report, field, label):
    return report["persistent_flags"].get(f"{field}:{label}", 0) / max(report["packets"], 1)


def rate(report, label, field):
    stats = report["by_field"][field]
    return stats["labels"].get(label, 0) / max(stats["packets"], 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-module", type=Path, default=ROOT / "services/model-router/app/sensor_quality.py")
    parser.add_argument("--no-sticky", action="store_true", help="skip the sticky-reference pass")
    args = parser.parse_args()
    derive = load_rules(args.rules_module)
    report = {"backend": "deterministic_sensor_quality_only", "real_data": True, "fault_annotations": False,
              "history_packets": HISTORY, "datasets": {}, "sticky": {}, "guards": [], "skipped": []}

    sticky_plan = []

    def run_sticky(key, source, arg, context, fields, stuck_fields, drift_fields, drift_limit):
        """Queue the replays; they run in parallel at the end (see sticky_guards)."""
        if not args.no_sticky:
            sticky_plan.append((key, source, arg, context, fields, stuck_fields, drift_fields, drift_limit))

    def sticky_guards():
        """Both ways: as Core behaves (informational) and with a 2 h lapse (guarded where it must not regress)."""
        jobs = [(str(args.rules_module), source, arg, context, fields, lapse)
                for _, source, arg, context, fields, _, _, _ in sticky_plan for lapse in (None, LAPSE_S)]
        with ProcessPoolExecutor(max_workers=min(os.cpu_count() or 1, len(jobs) or 1)) as pool:
            done = list(pool.map(sticky_worker, jobs))
        for index, (key, _, _, _, _, stuck_fields, drift_fields, drift_limit) in enumerate(sticky_plan):
            attended, lapsed = done[2 * index], done[2 * index + 1]
            report["sticky"][key] = {"unattended_no_lapse": {"note": UNATTENDED, **attended}, "lapse_2h": lapsed}
            for field in stuck_fields:  # the stuck limits do not depend on the lapse
                for label, variant in (("no lapse", attended), ("2 h lapse", lapsed)):
                    value = sticky_rate(variant, field, "stuck_value")
                    guard(f"{key} sticky {field} persistent stuck rate ({label})", value, "<= 0.005", value <= 0.005)
            for field, label in NEW_CHECKS:
                if (key, field, label) in NEW_CHECK_EXEMPT:
                    continue
                for variant_label, variant in (("no lapse", attended), ("2 h lapse", lapsed)):
                    value = sticky_rate(variant, field, label)
                    guard(f"{key} sticky {field} {label} rate ({variant_label})", value, f"<= {NEW_CHECK_LIMIT}",
                          value <= NEW_CHECK_LIMIT)
            for field in QUIET.get(key, []):
                for label, variant in (("no lapse", attended), ("2 h lapse", lapsed)):
                    flags = variant["persistent_flags"].get(f"{field}:stuck_value", 0)
                    guard(f"{key} sticky {field} stays free of persistent flags ({label})", flags, "== 0", flags == 0)
            for field in drift_fields:  # with the lapse; unattended is informational (see the module docstring)
                value = sticky_rate(lapsed, field, "baseline_drift_possible")
                guard(f"{key} sticky {field} persistent drift rate (2 h lapse)", value, f"<= {drift_limit}",
                      value <= drift_limit)

    def guard(name, value, limit, ok):
        report["guards"].append({"guard": name, "value": round(value, 5), "limit": limit, "passed": ok})

    if AQUAPONIC.exists():
        aq = replay(derive, aquaponic_packets(), {"crop": "leafy_greens", "system_type": "nft_aquaponic"},
                    ["ph", "ec_ms_cm", "water_temperature_c"])
        report["datasets"]["mendeley_aquaponic_pond_iot"] = aq
        # The TDS-derived EC is noisy in 1-2 reading bursts (a sensor-check card needs 3 in a row): its drift is
        # reported but not guarded.
        run_sticky("mendeley_aquaponic_pond_iot", "aquaponic", None,
                   {"crop": "leafy_greens", "system_type": "nft_aquaponic"}, ["ph", "ec_ms_cm", "water_temperature_c"],
                   ["water_temperature_c"], ["ph"], 0.02)
        # ~0.7 m3 pond: DS18B20 holds one step up to 4.75 h, so water-temperature freezes are thermal mass.
        stuck = rate(aq, "stuck_value", "water_temperature_c")
        guard("aquaponic water-temperature stuck_value rate", stuck, "<= 0.005", stuck <= 0.005)
        # Unshielded PH-4502C: noise must not be reported as calibration drift. Was 0.39
        # before noisy_signal_possible; the rest mostly anchor on an outlier first reading.
        drift = rate(aq, "baseline_drift_possible", "ph")
        guard("aquaponic pH baseline_drift rate", drift, "<= 0.10", drift <= 0.10)
        noisy = rate(aq, "noisy_signal_possible", "ph")
        guard("aquaponic pH noisy_signal rate", noisy, ">= 0.5", noisy >= 0.5)
    else:
        report["skipped"].append(str(AQUAPONIC.relative_to(ROOT)))

    if AGC2.exists():
        fields = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
        for compartment in sorted(p for p in AGC2.iterdir() if (p / "GreenhouseClimate.csv").exists()):
            rep = replay(derive, agc2_packets(compartment), {"crop": "tomato", "system_type": "greenhouse_substrate"},
                         fields, extra_fields=["substrate_temperature_c", "substrate_moisture_pct"])
            report["datasets"][f"4tu_agc2_cherry_tomato/{compartment.name}"] = rep
            run_sticky(f"4tu_agc2_cherry_tomato/{compartment.name}", "agc2", str(compartment),
                       {"crop": "tomato", "system_type": "greenhouse_substrate"}, fields,
                       ["air_temperature_c", "humidity_pct", "substrate_temperature_c"], ["ph", "ec_ms_cm"], 0.02)
            # Commercial drain probes are mostly smooth; Automatoes drain EC really jumps
            # 4.4-6.3 mS/cm between 5-minute samples (1 % of packets), so allow up to 2 %.
            noisy = max(rate(rep, "noisy_signal_possible", "ph"), rate(rep, "noisy_signal_possible", "ec_ms_cm"))
            guard(f"AGC2 {compartment.name} pH/EC noisy_signal rate", noisy, "<= 0.02", noisy <= 0.02)
            stuck = rate(rep, "stuck_value", "substrate_temperature_c")
            guard(f"AGC2 {compartment.name} substrate-temperature stuck_value rate", stuck, "<= 0.005", stuck <= 0.005)
    else:
        report["skipped"].append(str(AGC2.relative_to(ROOT)) + " (extract the .7z there)")

    sticky_guards()
    report["passed"] = all(g["passed"] for g in report["guards"])
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
