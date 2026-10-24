"""Offline, synthetic time-ordered replay of the actual sensor-quality rules.

No model inference, network, database writes, or actuator path. Fault annotations
are evaluator-only; they are never passed to the detector. Exit 1 means gaps.

Besides detection, every frame is also run through the deterministic domain
specialists three ways (clean counterpart, faulty ungated, faulty gated by the
sensor veto) to count wrong domain labels that were shown as trusted.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/model-router"))
import yaml

from app.nutrient_ph_ec import derive_nutrient_ph_ec
from app.sensor_quality import derive_sensor_quality
from app.tomato_reasoner import derive_tomato_risk
from app.trust_gate import apply_sensor_veto
from app.water_irrigation import derive_water_irrigation_risk

FIELDS = ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct"]
# No substrate probes in these packets, so a recirculating system keeps the clean frames free of
# constant "missing substrate" labels.
FARM = {"crop": "tomato", "system_type": "controlled_greenhouse"}
# Constant EC error from frame 0: inside the plausible range, no baseline to drift from, and large
# enough to cross the 4.5 mS/cm high-EC threshold (+1.5 would be wrong in value but not in label).
PLAUSIBLE_EC_OFFSET = 3.0
UNDETECTABLE = {"plausible_offset"}
RULES_PATH = ROOT / "services/automation-engine/app/rules.yaml"
# Labels that produce an advice card in the automation engine; sensor_check is the can't-confirm card, not advice.
CARD_LABELS = {label for rule in yaml.safe_load(RULES_PATH.read_text())["rules"] if rule["id"] != "sensor_check"
               for label in rule["match_any_labels"]}
METRIC_DEFINITIONS = {
    "faulty_frames": "frames where a fault was injected, whether or not a detector can catch it",
    "clean_labels": "domain labels (water + nutrient + tomato specialists) for the same frame before the fault was injected",
    "wrong": "a frame's domain labels differ (either direction) from the clean counterpart's",
    "wrong_ungated": "faulty frames whose labels, computed on the raw faulty reading, are wrong",
    "wrong_gated": "faulty frames whose labels, computed after the sensor veto, are wrong (a cannot_confirm frame has no labels, so it is wrong only if the clean frame had some)",
    "card_labels": "labels matched by any rule in services/automation-engine/app/rules.yaml except sensor_check, i.e. labels that make an advice card",
    "wrong_cards": "wrong restricted to card_labels: the card-producing labels differ from the clean counterpart's",
    "wrong_cards_ungated": "faulty frames whose card-producing labels, on the raw faulty reading, are wrong (the old pipeline would show a wrong advice card)",
    "trusted_wrong_cards_ungated": "wrong_cards_ungated frames where the sensor-quality check raised nothing",
    "wrong_cards_gated": "faulty frames whose card-producing labels, after the sensor veto, are wrong",
    "trusted_wrong_cards_gated": "wrong_cards_gated frames where trust_verdict is not cannot_confirm: a wrong advice card still shown as reliable",
    "trusted_wrong_ungated": "wrong_ungated frames where the sensor-quality check raised nothing, so the wrong labels look trusted",
    "trusted_wrong_gated": "faulty frames where the labels computed after the sensor veto are wrong and trust_verdict is not cannot_confirm, i.e. a wrong label still shown as reliable",
    "cannot_confirm_frames": "faulty frames with trust_verdict cannot_confirm (no domain labels produced)",
    "partial_frames": "faulty frames with trust_verdict partial (some fields vetoed, the rest still reasoned on)",
    "trusted_wrong_rate_ungated": "trusted_wrong_ungated / faulty_frames",
    "trusted_wrong_cards_rate_ungated": "trusted_wrong_cards_ungated / faulty_frames",
    "trusted_wrong_cards_rate_gated": "trusted_wrong_cards_gated / faulty_frames",
    "trusted_wrong_rate_gated": "trusted_wrong_gated / faulty_frames",
}


def scenarios():
    start = datetime(2026, 9, 6, 8, tzinfo=timezone.utc)
    for name in ("normal", "spike", "missing_ph", "conflicting_probes", "dropout",
                 "slow_drift", "stuck_value", "sustained_impossible_ph", "plausible_offset",
                 "ph_jump", "ec_drift_high", "stuck_humidity_high"):
        frames = []
        for step in range(12):
            now = start + timedelta(minutes=20 * step)
            sensor = {"ph": 6.0, "ec_ms_cm": 2.0, "air_temperature_c": 24.0 + step % 2 * .1,
                      "humidity_pct": 60.0, "timestamp": now.isoformat()}
            if name == "stuck_humidity_high":  # a stuck probe needs earlier variation to be told from a steady one
                sensor["humidity_pct"] = 60.0 + step % 2
            clean = dict(sensor)
            faulty = 3 <= step < 9 and name != "normal"
            if 3 <= step < 9 and name != "normal":
                if name == "spike": sensor["ph"] = 13.0
                elif name == "missing_ph": sensor.pop("ph")
                elif name == "conflicting_probes": sensor["backup_air_temperature_c"] = 36.0
                elif name == "dropout":
                    sensor["timestamp"] = (start + timedelta(minutes=40)).isoformat()
                elif name == "slow_drift":
                    sensor["ph"] = 6.0 + .1 * (step - 2)
                    sensor["previous_ph"] = sensor["ph"] - .1
                elif name == "stuck_value": sensor["air_temperature_c"] = 24.0
                elif name == "sustained_impossible_ph": sensor["ph"] = 13.0
                elif name == "ph_jump":  # plausible but wrong: crosses the 7.2 high-pH threshold
                    sensor["ph"], sensor["previous_ph"] = 7.6, 6.0 if step == 3 else 7.6
                elif name == "stuck_humidity_high": sensor["humidity_pct"] = 88.0  # latched high
            # A spike is a single faulty sample, followed by recovery.
            if name == "spike" and step != 3:
                sensor["ph"], faulty = 6.0, False
            injected = faulty
            # Annotate only frames the deterministic detectors can honestly catch.
            if name == "dropout" and 3 <= step < 9:
                sample = datetime.fromisoformat(sensor["timestamp"])
                faulty = (now - sample).total_seconds() > 60 * 60
            elif name == "stuck_value" and 3 <= step < 9:
                # Needs prior variation plus a 3-sample freeze window.
                faulty = step >= 4
            elif name == "slow_drift" and 3 <= step < 9:
                faulty = abs(sensor["ph"] - 6.0) >= 0.35
            elif name == "ph_jump" and 3 <= step < 9:
                # The previous_ph step flags the jump; after it the value is steady until the startup
                # baseline check has three sustained samples (step 5).
                faulty = step == 3 or step >= 5
            elif name == "stuck_humidity_high" and 3 <= step < 9:
                faulty = step >= 5  # a freeze needs three identical samples
            elif name == "ec_drift_high" and step >= 3:
                # EC climbs 0.5 mS/cm per sample, crosses the 4.5 high-EC threshold at step 7 and holds at 5.5; it does
                # not recover, because the noise/drift windows keep flagging it. Three sustained samples are needed.
                sensor["ec_ms_cm"] = min(2.0 + .5 * (step - 2), 5.5)
                injected, faulty = True, step >= 5
            elif name == "plausible_offset":
                sensor["ec_ms_cm"] = round(2.0 + PLAUSIBLE_EC_OFFSET, 3)
                injected = faulty = True
            frames.append((now, sensor, faulty, injected, clean))
        yield name, frames


def domain_labels(sensor, expected, vetoed=()):
    """Sorted labels from the deterministic water, nutrient and tomato rules (no network, no audit writes)."""
    data = {"farm_context": FARM, "sensor": sensor, "expected_fields": expected}
    return sorted({*derive_water_irrigation_risk(data)["irrigation_risk_labels"],
                   *derive_nutrient_ph_ec(data)["nutrient_risk_labels"],
                   *derive_tomato_risk({**FARM, **sensor, "vetoed_fields": list(vetoed)})["risk_labels"]})


def gated_labels(sensor, history, quality):
    """(labels, trust gate) the way the guarded pipeline computes them: veto first, then the specialists."""
    masked, _, gate = apply_sensor_veto(sensor, history, quality, FIELDS)
    if gate["trust_verdict"] == "cannot_confirm":
        return [], gate
    expected = [field for field in FIELDS if field not in gate["vetoed_fields"]]
    return domain_labels(masked, expected, gate["vetoed_fields"]), gate


def summarize(rows):
    total = {key: sum(row[key] for row in rows) for key in (
        "faulty_frames", "wrong_ungated", "wrong_gated", "trusted_wrong_ungated", "trusted_wrong_gated",
        "wrong_cards_ungated", "trusted_wrong_cards_ungated", "wrong_cards_gated", "trusted_wrong_cards_gated",
        "cannot_confirm_frames", "partial_frames")}
    for kind in ("ungated", "gated"):
        total[f"trusted_wrong_rate_{kind}"] = (
            round(total[f"trusted_wrong_{kind}"] / total["faulty_frames"], 4) if total["faulty_frames"] else None)
        total[f"trusted_wrong_cards_rate_{kind}"] = (
            round(total[f"trusted_wrong_cards_{kind}"] / total["faulty_frames"], 4) if total["faulty_frames"] else None)
    return total


def run_benchmark():
    reports = []
    for name, frames in scenarios():
        tp = fp = fn = tn = 0
        onset = first_detection = None
        latency_ms = []
        predictions = []
        history = []
        metrics = dict.fromkeys(("faulty_frames", "wrong_ungated", "wrong_gated", "trusted_wrong_ungated",
                                 "trusted_wrong_gated", "wrong_cards_ungated", "trusted_wrong_cards_ungated",
                                 "wrong_cards_gated", "trusted_wrong_cards_gated", "cannot_confirm_frames",
                                 "partial_frames"), 0)
        for now, sensor, faulty, injected, clean in frames:
            before = perf_counter()
            result = derive_sensor_quality(
                FARM,
                sensor,
                FIELDS,
                now=now,
                history=history,
            )
            latency_ms.append((perf_counter() - before) * 1000)
            alerted = bool(result["human_review_required"])
            tp += int(faulty and alerted)
            fp += int(not faulty and alerted)
            fn += int(faulty and not alerted)
            tn += int(not faulty and not alerted)
            if faulty and onset is None: onset = now
            if faulty and alerted and first_detection is None: first_detection = now
            clean_labels = domain_labels(clean, FIELDS)
            ungated = domain_labels(sensor, FIELDS)
            gated, gate = gated_labels(sensor, history, result)
            verdict = gate["trust_verdict"]
            if injected:
                wrong_ungated, wrong_gated = ungated != clean_labels, gated != clean_labels
                metrics["faulty_frames"] += 1
                metrics["wrong_ungated"] += int(wrong_ungated)
                metrics["wrong_gated"] += int(wrong_gated)
                metrics["trusted_wrong_ungated"] += int(wrong_ungated and not alerted)
                metrics["trusted_wrong_gated"] += int(wrong_gated and verdict != "cannot_confirm")
                cards = {label for label in clean_labels if label in CARD_LABELS}
                wrong_cards_ungated = {l for l in ungated if l in CARD_LABELS} != cards
                wrong_cards_gated = {l for l in gated if l in CARD_LABELS} != cards
                metrics["wrong_cards_ungated"] += int(wrong_cards_ungated)
                metrics["trusted_wrong_cards_ungated"] += int(wrong_cards_ungated and not alerted)
                metrics["wrong_cards_gated"] += int(wrong_cards_gated)
                metrics["trusted_wrong_cards_gated"] += int(wrong_cards_gated and verdict != "cannot_confirm")
                metrics["cannot_confirm_frames"] += int(verdict == "cannot_confirm")
                metrics["partial_frames"] += int(verdict == "partial")
            predictions.append({"time": now.isoformat(), "fault_annotation": faulty,
                                "labels": result["data_quality_labels"], "review": alerted,
                                "fault_injected": injected, "trust_verdict": verdict,
                                "domain_labels": {"clean": clean_labels, "ungated": ungated, "gated": gated}})
            history.append(dict(sensor))
        reports.append({"scenario": name, "detectable": name not in UNDETECTABLE,
                        "true_positive": tp, "false_positive": fp,
                        "false_negative": fn, "true_negative": tn,
                        "detection_delay_minutes": (first_detection - onset).total_seconds() / 60 if first_detection else None,
                        "max_detector_latency_ms": max(latency_ms), **metrics, "frames": predictions})
    return {"backend": "deterministic_rules_only", "synthetic": True,
            "model_quality_evaluation": False,
            "limitations": "Synthetic fault annotations are not field ground truth. Flat or slowly changing values can be legitimate; missing these annotations alone does not justify adding alarm rules. Dropout is evaluated by replaying the last packet with advancing current time, not by testing MQTT transport. Temporal stuck/baseline checks use prior packets in-process; they are not a full MQTT soak. No memory benchmark or real-model inference is performed. Trusted-wrong counts compare domain labels frame by frame against the same frame before the fault was injected; a wrong value that does not change a label is not counted. plausible_offset is a constant in-range error from frame 0 that the sensor-quality rules cannot detect (detectable false): it is excluded from the passed gate but included in the trusted-wrong totals, where the veto cannot help.",
            "metric_definitions": METRIC_DEFINITIONS,
            "passed": all(r["false_positive"] == 0 and r["false_negative"] == 0 for r in reports if r["detectable"]),
            "totals": summarize(reports),
            "totals_detectable": summarize([r for r in reports if r["detectable"]]),
            "scenarios": reports}


if __name__ == "__main__":
    report = run_benchmark()
    print(json.dumps(report, indent=2))
    # Human-readable summary on stderr so stdout stays pure JSON.
    columns = ("faulty_frames", "wrong_ungated", "trusted_wrong_ungated", "wrong_gated", "trusted_wrong_gated",
               "wrong_cards_ungated", "trusted_wrong_cards_ungated", "wrong_cards_gated", "trusted_wrong_cards_gated",
               "cannot_confirm_frames", "partial_frames")
    heads = ("faulty", "wrong_u", "tw_u", "wrong_g", "tw_g", "cards_u", "tw_cards_u", "cards_g", "tw_cards_g", "cannot", "partial")
    print(f"{'scenario':<26}" + "".join(f"{h:>11}" for h in heads), file=sys.stderr)
    for row in [*report["scenarios"], {"scenario": "ALL", **report["totals"]},
                {"scenario": "ALL detectable", **report["totals_detectable"]}]:
        print(f"{row['scenario']:<26}" + "".join(f"{row[c]:>11}" for c in columns), file=sys.stderr)
    print(f"trusted_wrong_rate ungated={report['totals']['trusted_wrong_rate_ungated']} "
          f"gated={report['totals']['trusted_wrong_rate_gated']}; cards ungated="
          f"{report['totals']['trusted_wrong_cards_rate_ungated']} gated={report['totals']['trusted_wrong_cards_rate_gated']}",
          file=sys.stderr)
    raise SystemExit(0 if report["passed"] else 1)
