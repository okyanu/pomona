"""Replay real third-party sensor logs through the deterministic sensor-quality rules.

Unlike scripts/benchmark_sensor_fault_replay.py (synthetic, annotated), these logs
have no fault annotations. The report counts labels per dataset and checks a few
regression guards learned from them. Raw files stay local in datasets/raw/ (see
datasets/sources/*.yaml); a missing dataset is reported as skipped, not failed.

Each packet sees the previous 11 packets of its stream as history (the dashboard
and Sensor Data Checker window) and is checked at its own sample time.
Exit 1 means a guard failed.

Usage: python scripts/benchmark_real_sensor_replay.py [--rules-module PATH]
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "datasets/raw"
AQUAPONIC = RAW / "mendeley_aquaponic_pond_iot/pond_iot_2023_raw.csv"
AGC2 = RAW / "4tu_agc2_cherry_tomato/extracted"
HISTORY = 11


def load_rules(path: Path):
    spec = importlib.util.spec_from_file_location("sensor_quality_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.derive_sensor_quality


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


def rate(report, label, field):
    stats = report["by_field"][field]
    return stats["labels"].get(label, 0) / max(stats["packets"], 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rules-module", type=Path, default=ROOT / "services/model-router/app/sensor_quality.py")
    args = parser.parse_args()
    derive = load_rules(args.rules_module)
    report = {"backend": "deterministic_sensor_quality_only", "real_data": True, "fault_annotations": False,
              "history_packets": HISTORY, "datasets": {}, "guards": [], "skipped": []}

    def guard(name, value, limit, ok):
        report["guards"].append({"guard": name, "value": round(value, 5), "limit": limit, "passed": ok})

    if AQUAPONIC.exists():
        aq = replay(derive, aquaponic_packets(), {"crop": "leafy_greens", "system_type": "nft_aquaponic"},
                    ["ph", "ec_ms_cm", "water_temperature_c"])
        report["datasets"]["mendeley_aquaponic_pond_iot"] = aq
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
            # Commercial drain probes are mostly smooth; Automatoes drain EC really jumps
            # 4.4-6.3 mS/cm between 5-minute samples (1 % of packets), so allow up to 2 %.
            noisy = max(rate(rep, "noisy_signal_possible", "ph"), rate(rep, "noisy_signal_possible", "ec_ms_cm"))
            guard(f"AGC2 {compartment.name} pH/EC noisy_signal rate", noisy, "<= 0.02", noisy <= 0.02)
            stuck = rate(rep, "stuck_value", "substrate_temperature_c")
            guard(f"AGC2 {compartment.name} substrate-temperature stuck_value rate", stuck, "<= 0.005", stuck <= 0.005)
    else:
        report["skipped"].append(str(AGC2.relative_to(ROOT)) + " (extract the .7z there)")

    report["passed"] = all(g["passed"] for g in report["guards"])
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
