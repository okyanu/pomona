#!/usr/bin/env python3
"""Grade Pomona against a fake greenhouse truth log: the answer key next to Pomona's cards.

The truth log (examples/simulators/fake_greenhouse.py --truth-log) says, for every reading, what
was really true and what a correct system should conclude. This script compares that with the
alerts Pomona raised (the operator-visible cards on Core's feed path: automation-engine alerts).

  --automation-url URL   stack mode, stdlib only: read the alert events from a running
                         automation-engine (and, with --core-url, what Core stored)
  --offline              replay the Core-accepted events through the real model-router pipeline
                         and the real alert monitor in-process (run with the model-router venv)

Joins are by zone + sample timestamp (parsed, so ISO spellings do not matter). Alert time is the
sample time of the reading, never the wall clock. See METRIC_DEFINITIONS in the JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
AUTOMATION_APP = ROOT / "services" / "automation-engine" / "app"
ROUTER_DIR = ROOT / "services" / "model-router"
SENSOR_RULE = "sensor_check"
# Fields a card is built from, per rule: a raise of that rule during a fault on one of them is a wrong card.
RULE_FIELDS = {
    "ph_out_of_range": ("ph",),
    "high_ec_alert": ("ec_ms_cm",),
    "low_ec_alert": ("ec_ms_cm",),
    "high_humidity_fan": ("humidity_pct", "air_temperature_c"),
    "water_level_check": ("soil_moisture_pct", "substrate_moisture_pct"),
}
# Core's SensorEvent optional fields: Core's stored packet has them as null when absent.
CORE_OPTIONAL = ("substrate_temperature_c", "substrate_moisture_pct", "weather", "zone_area_m2", "crop_kc",
                 "npk_target")
ACCEPTED_STATUSES = (200, 201)

METRIC_DEFINITIONS = {
    "real_episode": "a run of consecutive frames on a zone where the truth log's expected_labels holds one label",
    "caught": "the rule for the label raised, with a sample time from the first true crossing to the episode end plus the rule's clear window",
    "delay": "seconds and samples from the first true crossing to the raise",
    "too_short_to_raise": "the episode (or fault window) is shorter than the rule's raise_after, so no raise was possible: not counted as missed",
    "sensor_check_frames": "offline: readings in a sensor-fault window where the sensor check fired, even when no alert was raised because the label never lasted raise_after",
    "no_card_rule": "the expected label has no rule in rules.yaml (heat_stress), so Pomona has no card to raise: not a miss",
    "missed": "a long enough real episode where the rule never raised",
    "sensor_fault_episode": "frames with a sensor fault active plus its recovering_from tail, where the fault leaves wrong readings in Pomona's 11-packet history",
    "sensor_check_caught": "the sensor_check rule raised inside the fault window",
    "trusted_wrong_card": "a rule built on the faulty field raised inside the fault window (a wrong advice card, same idea as trusted_wrong_cards_gated in the fault replay benchmark)",
    "undetectable": "plausible_offset: an in-range constant offset Pomona cannot tell from a real value; reported apart, never counted as a miss",
    "dead_clock": "the device stamped 1970: expected to be rejected by Core (delivery 422 or not stored)",
    "false_alarm": "a raise whose sample time is in no episode's window (real episodes: same rule, until its clear window ends; fault episodes: any rule)",
    "card_labels": "labels matched by any rule in rules.yaml except sensor_check, i.e. labels that make an advice card",
    "normal_frame_with_card": "offline: frame the truth log calls normal where the pipeline produced a card label the truth does not expect",
    "normal_frame_with_sensor_check": "offline: frame the truth log calls normal where the pipeline produced a sensor_check label, split into outside and inside recovering_from tails (inside is expected lingering)",
    "wrong_cards": "offline: sensor-fault frames whose card labels differ from the card labels of the truth's expected_labels",
    "trusted_wrong_cards": "wrong_cards frames where trust_verdict is not cannot_confirm: a wrong card still shown as reliable",
    "cannot_confirm_frames": "offline: sensor-fault frames with trust_verdict cannot_confirm",
    "partial_frames": "offline: sensor-fault frames with trust_verdict partial",
}


# --- Small helpers ----------------------------------------------------------------------

def parse_ts(text: str) -> datetime:
    """Any ISO spelling (Z or offset) as an aware UTC datetime."""
    value = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
    return (value if value.tzinfo else value.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def clock(value: datetime) -> str:
    return value.strftime("%H:%M:%S")


def parse_rules(text: str) -> List[Dict[str, Any]]:
    """Read rules.yaml without PyYAML: the file is a flat list of rules with scalar and list values."""
    rules: List[Dict[str, Any]] = []
    current: Dict[str, Any] = {}
    key = ""
    for raw in text.splitlines():
        body = raw.strip()
        if not body or body.startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        if indent == 0:
            if body != "rules:":
                break
            continue
        if indent == 2 and body.startswith("- "):
            current = {}
            rules.append(current)
            body, indent = body[2:], 4
        if indent == 4:
            key, _, value = body.partition(":")
            value = value.strip()
            if value.startswith("["):
                current[key] = [item.strip() for item in value[1:-1].split(",") if item.strip()]
            elif value in ("", ">-", ">"):
                current[key] = [] if value == "" else ""
            else:
                current[key] = int(value) if value.isdigit() else value
        elif body.startswith("- "):
            current[key].append(body[2:].strip())
        else:
            current[key] = (current[key] + " " + body).strip()
    return rules


def alert_defaults() -> Tuple[int, int]:
    """Alert monitor defaults (raise, clear seconds) from automation-engine config.py."""
    text = (AUTOMATION_APP / "config.py").read_text()
    raise_after = re.search(r"alert_raise_after_seconds:[^=]*=\s*Field\(default=(\d+)", text)
    clear_after = re.search(r"alert_clear_after_seconds:[^=]*=\s*Field\(default=(\d+)", text)
    return (int(raise_after.group(1)) if raise_after else 600, int(clear_after.group(1)) if clear_after else 900)


def load_truth(path: Path) -> List[Dict[str, Any]]:
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def core_accepted(row: Dict[str, Any]) -> bool:
    """Did Core store this reading? The delivery result when the simulator posted it, else the truth kind."""
    if not row.get("published"):
        return False
    delivery = row.get("delivery")
    if delivery is not None:
        return delivery.get("status") in ACCEPTED_STATUSES
    return row["expect"]["kind"] != "rejected_by_core"


@dataclass
class Frame:
    row: Dict[str, Any]
    zone: str
    tick: int
    time: datetime  # wall time of the attempt
    accepted: bool
    sample: Optional[datetime]  # sent timestamp, only for accepted frames (the join key)

    @property
    def expect(self) -> Dict[str, Any]:
        return self.row["expect"]


def build_frames(rows: List[Dict[str, Any]]) -> Dict[str, List[Frame]]:
    zones: Dict[str, List[Frame]] = {}
    for row in sorted(rows, key=lambda r: (r["zone_id"], r["tick"])):
        accepted = core_accepted(row)
        sample = parse_ts(row["sent"]["timestamp"]) if accepted and row.get("sent") else None
        zones.setdefault(row["zone_id"], []).append(
            Frame(row, row["zone_id"], row["tick"], parse_ts(row["wall_timestamp"]), accepted, sample))
    return zones


def runs(frames: List[Frame], predicate) -> List[List[Frame]]:
    out: List[List[Frame]] = []
    current: List[Frame] = []
    for frame in frames:
        if predicate(frame):
            current.append(frame)
        elif current:
            out.append(current)
            current = []
    return out + ([current] if current else [])


# --- Episodes and grading --------------------------------------------------------------------

class Grader:
    def __init__(self, rows: List[Dict[str, Any]], events: List[Dict[str, Any]], rules: List[Dict[str, Any]],
                 defaults: Tuple[int, int], frame_info: Optional[Dict[Tuple[str, int], Dict[str, Any]]] = None):
        self.zones = build_frames(rows)
        self.rules = {rule["id"]: rule for rule in rules}
        self.defaults = defaults
        self.frame_info = frame_info
        self.label_rule = {}
        for rule in rules:
            if rule["id"] != SENSOR_RULE:
                for label in rule["match_any_labels"]:
                    self.label_rule.setdefault(label, rule["id"])
        self.by_sample = {(zone, f.sample): f for zone, frames in self.zones.items() for f in frames if f.sample}
        self.unmatched: List[Dict[str, Any]] = []
        self.raises: List[Dict[str, Any]] = []
        for event in events:
            if event.get("event") != "raised":
                continue
            frame = self.by_sample.get((event["zone_id"], parse_ts(event["sample_time"])))
            if frame is None:
                self.unmatched.append(event)
                continue
            self.raises.append({"zone": frame.zone, "rule": event["rule_id"], "tick": frame.tick,
                                "time": frame.time, "sample_time": event["sample_time"]})
        self.raises.sort(key=lambda r: (r["time"], r["rule"]))

    def window(self, rule_id: str) -> Tuple[timedelta, timedelta]:
        rule = self.rules.get(rule_id, {})
        return (timedelta(seconds=rule.get("raise_after_seconds", self.defaults[0])),
                timedelta(seconds=rule.get("clear_after_seconds", self.defaults[1])))

    def find_raise(self, zone: str, rule_id: str, start: datetime, end: datetime) -> Optional[Dict[str, Any]]:
        return next((r for r in self.raises if r["zone"] == zone and r["rule"] == rule_id and start <= r["time"] <= end),
                    None)

    # Episodes

    def real_episodes(self) -> List[Dict[str, Any]]:
        out = []
        for zone, frames in self.zones.items():
            labels = sorted({label for f in frames for label in f.expect["expected_labels"]})
            for label in labels:
                for run in runs(frames, lambda f, label=label: label in f.expect["expected_labels"]):
                    rule_id = self.label_rule.get(label)
                    start, end = run[0], run[-1]
                    names = sorted({e["name"] for f in run for e in f.row["active_events"]})
                    ep = {"type": "real_event", "zone": zone, "label": label, "rule": rule_id,
                          "events": names, "start_tick": start.tick, "end_tick": end.tick,
                          "start_time": start.time, "end_time": end.time,
                          "duration_s": (end.time - start.time).total_seconds(), "raised": None}
                    if rule_id is None:
                        ep["outcome"] = "no_card_rule"
                    else:
                        raise_after, clear_after = self.window(rule_id)
                        ep["raise_after_s"] = raise_after.total_seconds()
                        ep["clear_after_s"] = clear_after.total_seconds()
                        hit = self.find_raise(zone, rule_id, start.time, end.time + clear_after)
                        if hit:
                            ep["outcome"] = "caught"
                            ep["raised"] = self._raised(hit, start.time, start.tick)
                        elif end.time - start.time < raise_after:
                            ep["outcome"] = "too_short_to_raise"
                        else:
                            ep["outcome"] = "missed"
                    out.append(ep)
        return out

    @staticmethod
    def _raised(hit: Dict[str, Any], start_time: datetime, start_tick: int) -> Dict[str, Any]:
        return {"rule": hit["rule"], "time": hit["time"], "tick": hit["tick"],
                "delay_s": (hit["time"] - start_time).total_seconds(), "delay_samples": hit["tick"] - start_tick}

    def fault_episodes(self, real: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        names = sorted({f["name"] for frames in self.zones.values() for fr in frames
                        for f in fr.row["active_faults"]})
        for zone, frames in self.zones.items():
            for name in names:
                def on(frame: Frame, name=name) -> bool:
                    return (any(f["name"] == name for f in frame.row["active_faults"])
                            or name in frame.expect["recovering_from"])
                for run in runs(frames, on):
                    active = [f for f in run if any(x["name"] == name for x in f.row["active_faults"])]
                    if not active:
                        continue  # only a lingering tail from an earlier window
                    start, end, active_end = run[0], run[-1], active[-1]
                    field = next((x["field"] for f in active for x in f.row["active_faults"] if x["name"] == name), None)
                    forbidden = sorted({fld for f in active for fld in f.expect["forbid_domain_cards_from"]})
                    ep = {"type": "sensor_fault", "fault": name, "zone": zone, "field": field,
                          "forbidden_fields": forbidden, "start_tick": start.tick, "end_tick": end.tick,
                          "active_end_tick": active_end.tick, "start_time": start.time, "end_time": end.time,
                          "active_end_time": active_end.time, "duration_s": (end.time - start.time).total_seconds(),
                          "frames": len(run), "raised": None, "wrong_cards": []}
                    if name == "dropout":
                        ep["outcome"] = "not_published"
                    elif name == "dead_clock":
                        rejected = all(not f.accepted for f in active)
                        ep["outcome"] = "rejected_by_core" if rejected else "accepted_by_core"
                        ep["frames"] = len(active)
                    else:
                        self._grade_fault(ep, name, real)
                    out.append(ep)
        return out

    def _grade_fault(self, ep: Dict[str, Any], name: str, real: List[Dict[str, Any]]) -> None:
        zone, start, end = ep["zone"], ep["start_time"], ep["end_time"]
        check = self.find_raise(zone, SENSOR_RULE, start, end)
        if check:
            ep["raised"] = self._raised(check, start, ep["start_tick"])
        for hit in self.raises:
            fields = RULE_FIELDS.get(hit["rule"], ())
            if hit["zone"] != zone or not start <= hit["time"] <= end or not set(fields) & set(ep["forbidden_fields"]):
                continue
            if any(r["zone"] == zone and r["rule"] == hit["rule"] and r["start_time"] <= hit["time"]
                   <= r["end_time"] + timedelta(seconds=r.get("clear_after_s", 0)) for r in real):
                continue  # the same card is also right for a real event happening at that time
            ep["wrong_cards"].append({"rule": hit["rule"], "time": hit["time"], "tick": hit["tick"]})
        raise_after, _ = self.window(SENSOR_RULE)
        ep["raise_after_s"] = raise_after.total_seconds()
        if self.frame_info:  # offline: did the sensor check ever fire on a single reading, even if it never persisted?
            ep["sensor_check_frames"] = sum(
                1 for f in self.zones[zone] if start <= f.time <= end
                and self.frame_info.get((zone, f.tick), {}).get("sensor_check_labels"))
        if name == "plausible_offset":
            ep["outcome"] = "undetectable"
        elif ep["wrong_cards"]:
            ep["outcome"] = "wrong_card"
        elif check:
            ep["outcome"] = "caught"
        elif ep["duration_s"] < raise_after.total_seconds():
            ep["outcome"] = "too_short_to_raise"
        else:
            ep["outcome"] = "missed"

    def false_alarms(self, real: List[Dict[str, Any]], faults: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for hit in self.raises:
            _, clear_after = self.window(hit["rule"])
            in_real = any(e["zone"] == hit["zone"] and e["rule"] == hit["rule"] and e["start_time"] <= hit["time"]
                          <= e["end_time"] + clear_after for e in real)
            in_fault = any(e["zone"] == hit["zone"] and e["start_time"] <= hit["time"] <= e["end_time"] + clear_after
                           for e in faults)
            if not (in_real or in_fault):
                item = {"zone": hit["zone"], "rule": hit["rule"], "tick": hit["tick"], "time": hit["time"]}
                if self.frame_info and (hit["zone"], hit["tick"]) in self.frame_info:
                    item["labels"] = self.frame_info[(hit["zone"], hit["tick"])]["labels"]
                out.append(item)
        return out

    def reading_level(self) -> Dict[str, Any]:
        """Offline only: per-frame verdicts from the real pipeline against the truth kind."""
        info = self.frame_info or {}
        out = {"normal_frames": 0, "normal_with_card": 0, "normal_with_sensor_check_outside_tail": 0,
               "normal_with_sensor_check_inside_tail": 0, "normal_tail_frames": 0, "faulty_frames": 0,
               "wrong_cards": 0, "trusted_wrong_cards": 0, "cannot_confirm_frames": 0, "partial_frames": 0}
        card_rules = set(self.label_rule)
        for frames in self.zones.values():
            for f in frames:
                got = info.get((f.zone, f.tick))
                if got is None:
                    continue
                kind = f.expect["kind"]
                if kind == "normal":
                    tail = bool(f.expect["recovering_from"])
                    out["normal_frames"] += 1
                    out["normal_tail_frames"] += tail
                    # A card label the truth still expects (an event just stopped, the true state not yet back) is right.
                    out["normal_with_card"] += bool(set(got["card_labels"]) - set(f.expect["expected_labels"]))
                    if got["sensor_check_labels"]:
                        out["normal_with_sensor_check_inside_tail" if tail else
                            "normal_with_sensor_check_outside_tail"] += 1
                elif kind in ("sensor_fault", "both"):
                    out["faulty_frames"] += 1
                    wanted = sorted(set(f.expect["expected_labels"]) & card_rules)
                    wrong = sorted(got["card_labels"]) != wanted
                    out["wrong_cards"] += wrong
                    out["trusted_wrong_cards"] += wrong and got["trust"] != "cannot_confirm"
                    out["cannot_confirm_frames"] += got["trust"] == "cannot_confirm"
                    out["partial_frames"] += got["trust"] == "partial"
        return out

    def report(self) -> Dict[str, Any]:
        real = self.real_episodes()
        faults = self.fault_episodes(real)
        false_alarms = self.false_alarms(real, faults)
        count = lambda items, key, value: sum(1 for i in items if i[key] == value)
        sensor = [e for e in faults if e["fault"] not in ("dropout", "dead_clock", "plausible_offset")]
        delays = [e["raised"]["delay_s"] for e in real if e["raised"]]
        summary = {
            "real_episodes": {"total": len(real), "caught": count(real, "outcome", "caught"),
                              "missed": count(real, "outcome", "missed"),
                              "too_short_to_raise": count(real, "outcome", "too_short_to_raise"),
                              "no_card_rule": count(real, "outcome", "no_card_rule"),
                              "max_delay_s": max(delays) if delays else None},
            "sensor_fault_episodes": {"total": len(sensor), "sensor_check_caught": count(sensor, "outcome", "caught"),
                                      "trusted_wrong_card": count(sensor, "outcome", "wrong_card"),
                                      "too_short_to_raise": count(sensor, "outcome", "too_short_to_raise"),
                                      "missed": count(sensor, "outcome", "missed")},
            "undetectable": {"total": count(faults, "fault", "plausible_offset"),
                             "sensor_check_raised": sum(1 for e in faults if e["fault"] == "plausible_offset" and e["raised"]),
                             "wrong_card": sum(1 for e in faults if e["fault"] == "plausible_offset" and e["wrong_cards"])},
            "dead_clock": {"total": count(faults, "fault", "dead_clock"),
                           "rejected_by_core": count(faults, "outcome", "rejected_by_core"),
                           "accepted_by_core": count(faults, "outcome", "accepted_by_core")},
            "dropout": {"total": count(faults, "fault", "dropout")},
            "false_alarms": len(false_alarms), "unmatched_events": len(self.unmatched),
        }
        frames = [f for fr in self.zones.values() for f in fr]
        return {"frames": {"total": len(frames), "accepted_by_core": sum(f.accepted for f in frames),
                           "published": sum(bool(f.row["published"]) for f in frames)},
                "rules": {rid: {"labels": r["match_any_labels"], "raise_after_s": self.window(rid)[0].total_seconds(),
                                "clear_after_s": self.window(rid)[1].total_seconds()} for rid, r in self.rules.items()},
                "summary": summary, "real_episodes": real, "fault_episodes": faults, "false_alarms": false_alarms,
                "unmatched_events": self.unmatched, "reading_level": self.reading_level() if self.frame_info else None,
                "metric_definitions": METRIC_DEFINITIONS}


def failures(report: Dict[str, Any]) -> int:
    """Missed real episodes plus wrong cards (the things --fail-on-miss fails on)."""
    summary = report["summary"]
    return summary["real_episodes"]["missed"] + summary["sensor_fault_episodes"]["trusted_wrong_card"]


# --- Offline replay: the real pipeline and the real alert monitor, in-process --------------------

def pipeline_risk_labels(result: Dict[str, Any]) -> List[str]:
    """Same as services/core/app/outcome_feed.py (copied: that package cannot be imported next to this one)."""
    return list(dict.fromkeys([
        *(result.get("sensor_quality") or {}).get("data_quality_labels", []),
        *(result.get("water_irrigation") or {}).get("irrigation_risk_labels", []),
        *(result.get("nutrient_ph_ec") or {}).get("nutrient_risk_labels", []),
        *(result.get("crop_risk") or {}).get("risk_labels", []),
    ]))


def core_packet(sent: Dict[str, Any]) -> Dict[str, Any]:
    """The reading as Core stores and forwards it: UTC timestamp with Z, absent optionals as null."""
    packet = {k: v for k, v in sent.items() if k != "source"}
    for key in CORE_OPTIONAL:
        packet.setdefault(key, None)
    packet["timestamp"] = iso_z(parse_ts(sent["timestamp"]))
    return packet


def load_alert_monitor(rules: List[Dict[str, Any]], defaults: Tuple[int, int], db_path: Path):
    """The real AlertMonitor (stdlib only), loaded by path so its `app` package never clashes."""
    spec = importlib.util.spec_from_file_location("pomona_alerts", AUTOMATION_APP / "alerts.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["pomona_alerts"] = module  # needed before exec for dataclass-style lookups
    spec.loader.exec_module(module)
    return module.AlertMonitor(rules, defaults[0], defaults[1], db_path=db_path, max_events=1_000_000)


def replay_offline(rows: List[Dict[str, Any]], rules: List[Dict[str, Any]], defaults: Tuple[int, int]):
    """Replay Core-accepted events like Core's outcome feed. Returns (alert events, frame info, states)."""
    sys.path.insert(0, str(ROUTER_DIR))
    try:
        from app import pipeline  # model-router's app package
    except ImportError as error:
        raise SystemExit(f"--offline needs the model-router venv (services/model-router/.venv/bin/python): {error}")
    pipeline.write_pipeline_audit = lambda record: None
    loop = asyncio.new_event_loop()
    history: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    events: List[Dict[str, Any]] = []
    info: Dict[Tuple[str, int], Dict[str, Any]] = {}
    card_labels = {label for r in rules if r["id"] != SENSOR_RULE for label in r["match_any_labels"]}
    check_labels = {label for r in rules if r["id"] == SENSOR_RULE for label in r["match_any_labels"]}
    with tempfile.TemporaryDirectory(prefix="score-fake-greenhouse.") as tmp:
        monitor = load_alert_monitor(rules, defaults, Path(tmp) / "alerts.db")
        try:
            for row in sorted(rows, key=lambda r: (r["tick"], r["zone_id"])):
                if not core_accepted(row):
                    continue
                sent = row["sent"]
                sample = parse_ts(sent["timestamp"])
                sensor = core_packet(sent)
                sensor.update(received_at=iso_z(sample + timedelta(seconds=1)), mqtt_retained=False)
                key = (sent["farm_id"], sent["zone_id"])
                prior = [{k: v for k, v in p.items() if k not in ("received_at", "mqtt_retained")}
                         for p in history.get(key, [])[-11:]]
                pipeline._now = lambda now=sample + timedelta(seconds=1): now
                farm = {"crop": sensor["crop"], "system_type": sensor["system_type"], "zone_id": sensor["zone_id"],
                        "weather": sensor.get("weather"), "zone_area_m2": sensor.get("zone_area_m2"),
                        "crop_kc": sensor.get("crop_kc"), "npk_target": sensor.get("npk_target")}
                result = loop.run_until_complete(pipeline.evaluate_pipeline(
                    farm, sensor, [], {"action_type": "continue_monitoring"}, "core_feed", "rules_only",
                    "core_feed", history=prior))
                history.setdefault(key, []).append(sensor)
                labels = pipeline_risk_labels(result)
                info[(row["zone_id"], row["tick"])] = {
                    "labels": labels, "trust": result["trust_gate"]["trust_verdict"],
                    "card_labels": sorted(set(labels) & card_labels),
                    "sensor_check_labels": sorted(set(labels) & check_labels)}
                events += monitor.observe(sent["farm_id"], sent["zone_id"], sent["device_id"], sample, labels)["events"]
            states = monitor.states()
        finally:
            monitor.close()
            loop.close()
    return events, info, states


# --- Stack mode (stdlib only) --------------------------------------------------------------

def get_json(url: str, timeout: float = 15.0) -> Any:
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"unsupported URL {url!r}")
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 (http/https checked above)
        return json.loads(response.read())


def fetch_alerts(automation_url: str, farm_id: str, zones: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    events, states = [], []
    for zone in zones:
        query = urllib.parse.urlencode({"farm_id": farm_id, "zone_id": zone, "limit": 10000})
        data = get_json(f"{automation_url.rstrip('/')}/v1/automation/alerts?{query}")
        events += data["events"]
        states += data["alerts"]
    return events, states


def fetch_core_events(core_url: str, farm_id: str, zones: List[str]) -> Dict[str, List[datetime]]:
    stored: Dict[str, List[datetime]] = {}
    for zone in zones:
        offset, got = 0, []
        while True:
            query = urllib.parse.urlencode({"farm_id": farm_id, "zone_id": zone, "limit": 500, "offset": offset})
            page = get_json(f"{core_url.rstrip('/')}/v1/sensors/events?{query}")["events"]
            got += [parse_ts(e["timestamp"]) for e in page]
            if len(page) < 500:
                break
            offset += 500
        stored[zone] = got
    return stored


def core_check(grader: Grader, stored: Dict[str, List[datetime]]) -> Dict[str, Any]:
    """What Core stored against what the truth log says it accepted."""
    accepted = {zone: {f.sample for f in frames if f.accepted} for zone, frames in grader.zones.items()}
    dead = {zone: {parse_ts(f.row["sent"]["timestamp"]) for f in frames if f.row["published"] and not f.accepted
                   and f.row.get("sent")} for zone, frames in grader.zones.items()}
    out = {"stored": sum(len(v) for v in stored.values()), "accepted_in_truth": sum(len(v) for v in accepted.values())}
    out["accepted_missing_in_core"] = sum(len(accepted[z] - set(stored.get(z, []))) for z in accepted)
    out["rejected_but_stored"] = sum(len(dead[z] & set(stored.get(z, []))) for z in dead)
    return out


# --- Report ------------------------------------------------------------------------------

def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, dict):
        return {k if not isinstance(k, tuple) else "|".join(map(str, k)): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


VERDICTS = {"caught": "caught", "missed": "MISSED", "too_short_to_raise": "too short to raise",
            "no_card_rule": "no card rule", "wrong_card": "WRONG CARD", "undetectable": "undetectable",
            "rejected_by_core": "rejected by Core", "accepted_by_core": "ACCEPTED BY CORE",
            "not_published": "no data (not scored)"}


def describe(ep: Dict[str, Any]) -> Tuple[str, str]:
    """(what really happened, expected answer) for the timeline table."""
    if ep["type"] == "real_event":
        what = "real event " + (", ".join(ep["events"]) or "?") + f" (true state crossed {ep['label']})"
        return what, (f"{ep['rule']} card" if ep["rule"] else f"{ep['label']} (Pomona has no card rule)")
    field = f" on {ep['field']}" if ep["field"] else ""
    what = f"sensor fault {ep['fault']}{field}" + (" (reading wrong, truth unchanged)" if ep["forbidden_fields"] else "")
    expected = {"dropout": "no packets; nothing to judge", "dead_clock": "Core rejects the 1970 timestamp",
                "plausible_offset": "undetectable today"}.get(ep["fault"])
    return what, expected or (f"{SENSOR_RULE} card, no domain card from {', '.join(ep['forbidden_fields'])}")


def raised_text(ep: Dict[str, Any]) -> str:
    parts = []
    if ep.get("raised"):
        r = ep["raised"]
        parts.append(f"{r['rule']} at {clock(r['time'])} (+{r['delay_s']:.0f} s, {r['delay_samples']} samples)")
    parts += [f"{w['rule']} at {clock(w['time'])}" for w in ep.get("wrong_cards", [])]
    if not parts and ep.get("sensor_check_frames"):
        return f"nothing raised (sensor check seen on {ep['sensor_check_frames']} readings, never lasted {ep['raise_after_s']:.0f} s)"
    return "; ".join(parts) or "nothing"


def markdown(report: Dict[str, Any], mode: str, truth: Path) -> str:
    s = report["summary"]
    episodes = sorted(report["real_episodes"] + report["fault_episodes"], key=lambda e: (e["start_time"], e["zone"]))
    lines = ["# Fake greenhouse: answer key next to Pomona's cards", "",
             f"Mode: {mode}. Truth log: `{truth}`. Cards are automation-engine alerts (a rule raised only after its "
             "raise_after window). Times are UTC sample times; delay counts from the first true crossing.", "",
             "## Timeline", "", "| Zone | Start | End | What really happened | Expected answer | Pomona raised | Verdict |",
             "|---|---|---|---|---|---|---|"]
    for ep in episodes:
        what, expected = describe(ep)
        lines.append(f"| {ep['zone']} | {clock(ep['start_time'])} | {clock(ep['end_time'])} | {what} | {expected} | "
                     f"{raised_text(ep)} | {VERDICTS.get(ep['outcome'], ep['outcome'])} |")
    for fa in report["false_alarms"]:
        extra = f" (labels: {', '.join(fa['labels'])})" if fa.get("labels") else ""
        lines.append(f"| {fa['zone']} | {clock(fa['time'])} | | normal operation | no card | {fa['rule']} at "
                     f"{clock(fa['time'])}{extra} | FALSE ALARM |")
    real, sensor = s["real_episodes"], s["sensor_fault_episodes"]
    lines += ["", "## Summary", "",
              f"- Real episodes: {real['total']}; caught {real['caught']}, missed {real['missed']}, too short to raise "
              f"{real['too_short_to_raise']}, no card rule {real['no_card_rule']}"
              + (f"; slowest raise {real['max_delay_s']:.0f} s after the crossing." if real["max_delay_s"] is not None else "."),
              f"- Sensor faults: {sensor['total']}; sensor_check caught {sensor['sensor_check_caught']}, wrong domain card "
              f"{sensor['trusted_wrong_card']}, too short to raise {sensor['too_short_to_raise']}, missed {sensor['missed']}.",
              f"- Undetectable (plausible_offset): {s['undetectable']['total']}; sensor_check raised "
              f"{s['undetectable']['sensor_check_raised']}, wrong card {s['undetectable']['wrong_card']}.",
              f"- Dead clock: {s['dead_clock']['total']}; rejected by Core {s['dead_clock']['rejected_by_core']}, "
              f"accepted {s['dead_clock']['accepted_by_core']}. Dropout episodes: {s['dropout']['total']}.",
              f"- False alarms in normal operation: {s['false_alarms']}. Alerts not in this truth log: {s['unmatched_events']}."]
    rl = report.get("reading_level")
    if rl:
        lines.append(f"- Reading level (offline): {rl['normal_frames']} normal frames, {rl['normal_with_card']} with a card "
                     f"label, {rl['normal_with_sensor_check_outside_tail']} with a sensor check outside recovery tails "
                     f"({rl['normal_with_sensor_check_inside_tail']} inside the {rl['normal_tail_frames']} tail frames). "
                     f"Sensor-fault frames: {rl['faulty_frames']}, wrong cards {rl['wrong_cards']} "
                     f"({rl['trusted_wrong_cards']} still trusted), cannot_confirm {rl['cannot_confirm_frames']}, "
                     f"partial {rl['partial_frames']}.")
    if report.get("core_check"):
        c = report["core_check"]
        lines.append(f"- Core stored {c['stored']} readings; the truth log says {c['accepted_in_truth']} were accepted "
                     f"({c['accepted_missing_in_core']} missing, {c['rejected_but_stored']} rejected ones stored).")
    return "\n".join(lines) + "\n"


def print_summary(report: Dict[str, Any], mode: str) -> None:
    s = report["summary"]
    real, sensor = s["real_episodes"], s["sensor_fault_episodes"]
    print(f"[{mode}] frames {report['frames']['total']} (accepted by Core {report['frames']['accepted_by_core']})")
    print(f"[{mode}] real episodes {real['total']}: caught {real['caught']}, missed {real['missed']}, "
          f"too short {real['too_short_to_raise']}, no card rule {real['no_card_rule']}")
    print(f"[{mode}] sensor faults {sensor['total']}: sensor_check caught {sensor['sensor_check_caught']}, "
          f"wrong card {sensor['trusted_wrong_card']}, too short {sensor['too_short_to_raise']}, missed {sensor['missed']}")
    print(f"[{mode}] undetectable {s['undetectable']['total']}, dead clock rejected "
          f"{s['dead_clock']['rejected_by_core']}/{s['dead_clock']['total']}, false alarms {s['false_alarms']}")
    rl = report.get("reading_level")
    if rl:
        print(f"[{mode}] normal frames {rl['normal_frames']}: with card {rl['normal_with_card']}, sensor check outside "
              f"tails {rl['normal_with_sensor_check_outside_tail']}, inside tails {rl['normal_with_sensor_check_inside_tail']}")


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--truth", type=Path, required=True, help="truth log written by fake_greenhouse.py")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--offline", action="store_true", help="replay in-process (model-router venv)")
    mode.add_argument("--automation-url", help="read alerts from a running automation-engine")
    p.add_argument("--core-url", help="stack mode: also confirm what Core stored")
    p.add_argument("--farm-id", help="default: the farm in the truth log")
    p.add_argument("--rules", type=Path, default=AUTOMATION_APP / "rules.yaml")
    p.add_argument("--json", type=Path, help="write the full report here")
    p.add_argument("--report", type=Path, help="write the markdown timeline here")
    p.add_argument("--fail-on-miss", action="store_true", help="exit 1 on a missed real episode or a wrong card")
    args = p.parse_args(argv)
    if args.core_url and not args.automation_url:
        p.error("--core-url belongs with --automation-url (stack mode)")

    rows = load_truth(args.truth)
    rules = parse_rules(args.rules.read_text())
    defaults = alert_defaults()
    zones = sorted({r["zone_id"] for r in rows})
    farm_id = args.farm_id or next(r["sent"]["farm_id"] for r in rows if r.get("sent"))
    info = states = stored = None
    if args.offline:
        events, info, states = replay_offline(rows, rules, defaults)
        label = "offline"
    else:
        events, states = fetch_alerts(args.automation_url, farm_id, zones)
        stored = fetch_core_events(args.core_url, farm_id, zones) if args.core_url else None
        label = "stack"
    grader = Grader(rows, events, rules, defaults, info)
    report = grader.report()
    report.update(mode=label, truth=str(args.truth), farm_id=farm_id, alerts_now=states,
                  alert_events=[e for e in events if e.get("event")], defaults={"raise_s": defaults[0], "clear_s": defaults[1]})
    if stored is not None:
        report["core_check"] = core_check(grader, stored)
    print_summary(report, label)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(jsonable(report), indent=2) + "\n")
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(markdown(report, label, args.truth))
    return 1 if args.fail_on_miss and failures(report) else 0


if __name__ == "__main__":
    sys.exit(main())
