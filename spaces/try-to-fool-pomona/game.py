"""The "Try to fool Pomona" game: one session = a seed plus the list of commands the visitor gave.

A session runs Pomona's real code (nothing is re-implemented here):

  fake_greenhouse.Simulation   the fake physics and the hidden answer key, on a virtual clock
                               (tick N is stamped start + N x 30 s, physics at the real rate: not a time-lapse)
  InProcessPomona              Core's checks, the model-router pipeline in rules_only mode and the alert monitor
  score_fake_greenhouse.Grader the scorer that grades finished episodes against the answer key

The client holds the scenario ({seed, ticks, commands}); the server only caches live sessions and rebuilds
one from its scenario when it is not cached (restart, sleep, eviction, replay link). Both paths run the same
`Session.advance` / `Session.command`, so a rebuilt session equals the cached one.

The engine files come from `vendor/` (scripts/build_fool_space.sh copies them from the repo); set
FOOL_SPACE_ROOT to use a repo checkout instead.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Tuple

SPACE_DIR = Path(__file__).resolve().parent
ENGINE_ROOT = Path(os.environ.get("FOOL_SPACE_ROOT") or SPACE_DIR / "vendor").resolve()
if not (ENGINE_ROOT / "examples" / "simulators" / "inprocess_pomona.py").is_file():
    raise ImportError(f"Pomona's engine files are not in {ENGINE_ROOT}: run scripts/build_fool_space.sh from the "
                      "repo root (or set FOOL_SPACE_ROOT to a repo checkout)")
for _sub in ("scripts", "examples/simulators"):
    if str(ENGINE_ROOT / _sub) not in sys.path:
        sys.path.insert(0, str(ENGINE_ROOT / _sub))

import fake_greenhouse as fg  # noqa: E402
import inprocess_pomona as ipp  # noqa: E402
import score_fake_greenhouse as score  # noqa: E402

GITHUB = "https://github.com/okyanu/pomona"
DOCS = f"{GITHUB}/blob/main/docs"

TICK_S = 30                                  # seconds between readings (Pomona's real default)
START = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)  # tick 0: the simulator's epoch day at its default start hour 8
MAX_HOURS = 24                               # simulated hours per session
MAX_TICKS = MAX_HOURS * 3600 // TICK_S
WARMUP_TICKS = 20                            # a new session starts 10 simulated minutes in, so Pomona has a baseline
MAX_ADVANCE_TICKS = 240                      # one request: at most 2 simulated hours
MAX_COMMANDS = 300                           # per session (keeps the scenario far under the 64 KB request cap)
MAX_HIDDEN = 3
SERIES_TICKS = 240                           # sparklines: the last 2 simulated hours ...
SERIES_STRIDE = 4                            # ... one point every 2 minutes
SCENARIO_VERSION = 1

RULES = ipp.load_rules()
DEFAULTS = ipp.alert_defaults()
LOOP = asyncio.new_event_loop()              # shared by every engine; each reading runs under ipp.PIPELINE_LOCK

# --- What the visitor sees by name --------------------------------------------------------------

ZONE_LABELS = {"greenhouse-a": ("A", "Substrate tomato"), "greenhouse-b": ("B", "Hydroponic tomato")}
FIELD_LABELS = {
    "air_temperature_c": ("Air temperature", "°C"), "humidity_pct": ("Humidity", "%"),
    "ec_ms_cm": ("EC", "mS/cm"), "ph": ("pH", ""), "soil_moisture_pct": ("Substrate moisture", "%"),
    "substrate_temperature_c": ("Substrate temperature", "°C"),
}
FIELD_WORDS = {"air_temperature_c": "air temperature", "humidity_pct": "humidity", "ec_ms_cm": "EC", "ph": "pH",
               "soil_moisture_pct": "substrate moisture", "substrate_temperature_c": "substrate temperature"}
TRICKS: Dict[str, Dict[str, str]] = {
    "stuck": {"title": "Stuck sensor", "blurb": "The reading freezes at its last value.", "group": "lie"},
    "drift": {"title": "Slow drift", "blurb": "The reading creeps away from the truth, minute by minute.",
              "group": "lie"},
    "jump": {"title": "Sudden jump", "blurb": "The reading is shifted by a fixed amount.", "group": "lie"},
    "spike": {"title": "One absurd reading", "blurb": "A single impossible value, then the sensor recovers.",
              "group": "lie"},
    "noisy": {"title": "Noisy sensor", "blurb": "The reading gets ten times jumpier.", "group": "lie"},
    "dropout": {"title": "Sensor goes silent", "blurb": "No readings arrive from the zone.", "group": "lie"},
    "dead_clock": {"title": "Dead clock", "blurb": "The device stamps 1970, as if its clock lost power.",
                   "group": "lie"},
    "plausible_offset": {"title": "Plausible offset", "blurb": "The reading is off by a steady, believable amount.",
                         "group": "lie"},
    "heat_spike": {"title": "Heat spike", "blurb": "A vent fails on a sunny day and the air really heats up.",
                   "group": "hurt"},
    "cold_night": {"title": "Cold night", "blurb": "The heating fails and the air really cools to about 13 °C.",
                   "group": "hurt"},
    "humid_night": {"title": "Humid night", "blurb": "Humidity really climbs to about 90 %.", "group": "hurt"},
    "nutrient_over_concentration": {"title": "Nutrient overdose",
                                    "blurb": "A doser error really pushes the EC up.", "group": "hurt"},
    "dry_zone": {"title": "Dry zone", "blurb": "Irrigation fails and the substrate really dries out (fast, for the demo). "
                 "Substrate zone only.", "group": "hurt"},
}
# A fault on a field other than its default one needs a sensible size for that field (the simulator's defaults are
# for pH / EC). Not user-editable: visitors choose what and where, not the numbers.
FIELD_PARAMS: Dict[str, Dict[str, Dict[str, float]]] = {
    "jump": {"ec_ms_cm": {"offset": 1.5}, "air_temperature_c": {"offset": 4.0},
             "substrate_temperature_c": {"offset": 4.0}, "humidity_pct": {"offset": 15.0},
             "soil_moisture_pct": {"offset": 15.0}},
    "spike": {"ec_ms_cm": {"value": 15.0}, "air_temperature_c": {"value": 75.0},
              "substrate_temperature_c": {"value": 75.0}, "humidity_pct": {"value": 100.0},
              "soil_moisture_pct": {"value": 100.0}},
    "plausible_offset": {"ph": {"offset": 0.8}, "air_temperature_c": {"offset": 3.0},
                         "substrate_temperature_c": {"offset": 3.0}, "humidity_pct": {"offset": 10.0},
                         "soil_moisture_pct": {"offset": 10.0}},
}
CARD_TITLES = {
    "high_humidity_fan": "a humidity card", "high_ec_alert": "a high-EC card", "low_ec_alert": "a low-EC card",
    "ph_out_of_range": "a pH card", "water_level_check": "a substrate-moisture card",
    "heat_stress_check": "a heat card", "cold_stress_check": "a cold card",
    "sensor_check": "a check-the-sensor card",
    "sensor_flatline": "a flat-probe hint",
}
CARD_NAMES = {
    "high_humidity_fan": "Humidity", "high_ec_alert": "High EC", "low_ec_alert": "Low EC", "ph_out_of_range": "pH",
    "water_level_check": "Substrate moisture", "heat_stress_check": "Heat", "cold_stress_check": "Cold",
    "sensor_check": "Check the sensor", "sensor_flatline": "Flat probe hint",
}
LABEL_WORDS = {"fungal_pressure": "fungal pressure (humid)", "heat_stress": "heat stress",
               "cold_stress": "cold stress", "high_ec": "high EC", "low_ec": "low EC", "high_ph": "high pH",
               "low_ph": "low pH", "water_level_risk": "water level risk"}

# verdict code -> how it is shown. `class`: caught / fooled / unfair / short / info. `{n}` and `{card}` are filled in.
VERDICTS: Dict[str, Dict[str, str]] = {
    "caught": {"class": "caught", "scorer": "caught", "headline": "Pomona caught it{after}",
               "why": "The matching card was raised once the problem had lasted its waiting time. A lying sensor "
                      "gets a \"check the sensor\" card instead of advice.",
               "doc": f"{DOCS}/FAKE_GREENHOUSE.md#reading-the-report"},
    "caught_cant_confirm": {"class": "caught", "scorer": "caught_cant_confirm",
                            "headline": "Pomona couldn't confirm it and asked for a meter check",
                            "why": "The reading moved to a level Pomona had not confirmed, so it refused to act on it "
                                   "and asked for a meter check. That is the safe answer.",
                            "doc": f"{DOCS}/SENSOR_TEMPORAL_CHECKS.md"},
    "missed": {"class": "fooled", "scorer": "MISSED", "headline": "You fooled Pomona",
               "why": "The problem lasted longer than the card's waiting time and no card was raised.",
               "doc": f"{DOCS}/FAKE_GREENHOUSE.md#honest-limits"},
    "caught_at_recovery": {"class": "fooled", "scorer": "MISSED (noticed only when it ended)",
                           "headline": "You fooled Pomona: it only noticed when your trick ended",
                           "why": "Pomona raised its check-the-sensor card only after the trick stopped and the reading "
                                  "snapped back to the true value. It did not see the lie while it lasted, so this "
                                  "counts as missed.",
                           "doc": f"{DOCS}/FAKE_GREENHOUSE.md#honest-limits"},
    "wrong_card": {"class": "fooled", "scorer": "WRONG CARD",
                   "headline": "You fooled Pomona: it trusted your lying sensor and raised {card}",
                   "why": "Pomona believed the faulty reading and built advice on it. That is the worst outcome.",
                   "doc": f"{DOCS}/FAKE_GREENHOUSE.md#reading-the-report"},
    "no_card_rule": {"class": "fooled", "scorer": "no card rule",
                     "headline": "You fooled Pomona: it has no alert for this yet (known gap)",
                     "why": "Pomona can see the condition but has no card rule for it yet.",
                     "doc": f"{DOCS}/FAKE_GREENHOUSE.md#honest-limits"},
    "too_short_to_raise": {"class": "short", "scorer": "too short to raise",
                           "headline": "Too short to count; keep it going at least {n} min",
                           "why": "Cards wait until a problem has lasted 10 minutes (30 for humidity), so one odd "
                                  "reading doesn't wake a grower at 3 am.",
                           "doc": f"{DOCS}/ADVICE_CARDS.md"},
    "undetectable": {"class": "unfair", "scorer": "undetectable",
                     "headline": "Unfair trick: nobody can see this from the readings alone",
                     "why": "A steady offset inside the normal range looks exactly like a real value, so it is "
                            "not counted against Pomona.",
                     "doc": f"{DOCS}/FAKE_GREENHOUSE.md#honest-limits"},
    "false_alarm": {"class": "alarm", "scorer": "FALSE ALARM", "headline": "Pomona cried wolf",
                    "why": "A card was raised while nothing was wrong.",
                    "doc": f"{DOCS}/FAKE_GREENHOUSE.md#reading-the-report"},
    "rejected_by_core": {"class": "caught", "scorer": "rejected by Core",
                         "headline": "Pomona's front door stopped it: a 1970 clock is refused",
                         "why": "Core refuses readings stamped before 2020 before any check runs, so a dead clock "
                                "never gets in. Counted as caught.",
                         "doc": f"{DOCS}/FAKE_GREENHOUSE.md#reading-the-report"},
    "not_published": {"class": "info", "scorer": "no data (not scored)",
                      "headline": "Nothing arrived, so there was nothing to judge",
                      "why": "A silent sensor sends no readings to check. This one isn't scored either way.",
                      "doc": f"{DOCS}/FAKE_GREENHOUSE.md#reading-the-report"},
    "accepted_by_core": {"class": "fooled", "scorer": "ACCEPTED BY CORE",
                         "headline": "You fooled Pomona: Core accepted a 1970 clock",
                         "why": "The dead-clock reading got past Core's ingest check.",
                         "doc": f"{DOCS}/FAKE_GREENHOUSE.md#reading-the-report"},
}
FOOLED = {"missed", "caught_at_recovery", "wrong_card", "no_card_rule", "accepted_by_core"}
CAUGHT = {"caught", "caught_cant_confirm", "rejected_by_core"}


# --- Scenario: the part the client holds ----------------------------------------------------------

_NAME = re.compile(r"^[a-z_-]{1,40}$")
COMMAND_KEYS = {"t", "op", "name", "zone", "field"}
OPS = {"start", "stop", "calibrate", "hidden", "reveal"}


def new_scenario(seed: int) -> Dict[str, Any]:
    return {"v": SCENARIO_VERSION, "seed": seed, "ticks": 0, "commands": []}


def check_scenario(raw: Any) -> Dict[str, Any]:
    """Validate a client-held scenario and return it normalised. Raises ValueError with a visitor-safe message."""
    if not isinstance(raw, dict) or set(raw) - {"v", "seed", "ticks", "commands"}:
        raise ValueError("scenario must be an object with seed, ticks and commands")
    seed, ticks, commands = raw.get("seed"), raw.get("ticks"), raw.get("commands")
    if raw.get("v", SCENARIO_VERSION) != SCENARIO_VERSION:
        raise ValueError("unknown scenario version")
    for label, value, high in (("seed", seed, 2**31 - 1), ("ticks", ticks, MAX_TICKS)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= high:
            raise ValueError(f"{label} must be a whole number from 0 to {high}")
    if not isinstance(commands, list) or len(commands) > MAX_COMMANDS:
        raise ValueError(f"commands must be a list of at most {MAX_COMMANDS}")
    clean: List[Dict[str, Any]] = []
    last_t = 0
    for cmd in commands:
        if not isinstance(cmd, dict) or set(cmd) - COMMAND_KEYS:
            raise ValueError("bad command")
        t = cmd.get("t")
        if isinstance(t, bool) or not isinstance(t, int) or not last_t <= t <= ticks:
            raise ValueError("command times must be in order and inside the session")
        last_t = t
        item: Dict[str, Any] = {"t": t, "op": cmd.get("op")}
        if item["op"] not in OPS:
            raise ValueError("unknown command")
        for key in ("name", "zone", "field"):
            if cmd.get(key) is not None:
                if not isinstance(cmd[key], str) or not _NAME.match(cmd[key]):
                    raise ValueError(f"bad {key}")
                item[key] = cmd[key]
        clean.append(item)
    return {"v": SCENARIO_VERSION, "seed": seed, "ticks": ticks, "commands": clean}


def scenario_key(scenario: Dict[str, Any]) -> str:
    return json.dumps(scenario, sort_keys=True, separators=(",", ":"))


# --- The session ---------------------------------------------------------------------------------

def virtual_clock():
    """Tick N is stamped START + N x 30 s. The simulator reads its clock once per step."""
    state = {"n": 0}

    def now() -> datetime:
        value = START + timedelta(seconds=TICK_S * state["n"])
        state["n"] += 1
        return value

    return now


def tick_of(sample: Any) -> int:
    stamp = sample if isinstance(sample, datetime) else ipp.parse_ts(str(sample))
    return int(round((stamp - START).total_seconds() / TICK_S))


def tick_iso(tick: int) -> str:
    return ipp.iso_z(START + timedelta(seconds=TICK_S * tick))


class Session:
    """One visitor's greenhouse. Not thread-safe: the server hands a session to one request at a time."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.sim = fg.Simulation(seed=seed, interval=TICK_S, sim_speed=1.0, start_hour=8.0, clock=virtual_clock())
        self.engine = ipp.InProcessPomona(RULES, DEFAULTS, loop=LOOP)
        self.commands: List[Dict[str, Any]] = []
        self.rows: List[Dict[str, Any]] = []             # compact truth rows, all the Grader reads
        self.alert_events: List[Dict[str, Any]] = []
        self.frame_info: Dict[Tuple[str, int], Dict[str, Any]] = {}
        self.recent: Dict[str, Deque[Optional[Dict[str, float]]]] = {z: deque(maxlen=SERIES_TICKS) for z in self.sim.zones}
        self.last_vals: Dict[str, Dict[str, float]] = {}
        self.last_got: Dict[str, Dict[str, Any]] = {}     # the engine's answer for the zone's last accepted reading
        self.last_note: Dict[str, Optional[str]] = {z: None for z in self.sim.zones}
        self._board: Optional[Tuple[int, Dict[str, Any]]] = None

    @classmethod
    def build(cls, scenario: Dict[str, Any]) -> "Session":
        """Rebuild a session from its client-held scenario (cache miss, restart, replay link)."""
        session = cls(scenario["seed"])
        try:
            for cmd in scenario["commands"]:
                session.advance_to(cmd["t"])
                session.command({k: v for k, v in cmd.items() if k != "t"})
            session.advance_to(scenario["ticks"])
        except Exception:
            session.close()
            raise
        return session

    @classmethod
    def start_new(cls, seed: int) -> "Session":
        session = cls(seed)
        session.advance_to(WARMUP_TICKS)
        return session

    def close(self) -> None:
        self.engine.close()

    @property
    def tick(self) -> int:
        return self.sim.tick

    def scenario(self) -> Dict[str, Any]:
        return {"v": SCENARIO_VERSION, "seed": self.seed, "ticks": self.tick,
                "commands": [dict(c) for c in self.commands]}

    # Commands (the same code path for a live click and a replay)

    def command(self, cmd: Dict[str, Any]) -> None:
        op = cmd.get("op")
        name, zone, field = cmd.get("name"), cmd.get("zone"), cmd.get("field")
        sim = self.sim
        if len(self.commands) >= MAX_COMMANDS:
            raise ValueError("this session has used all its commands; start a new one")
        if op == "start":
            if name not in TRICKS:
                raise ValueError("unknown trick")
            field = fg.canonical(field)
            use = field or fg.REGISTRY[name].default_field
            sim.queue_start(name, zone, field, FIELD_PARAMS.get(name, {}).get(use, {}))
        elif op == "stop":
            if name not in TRICKS:
                raise ValueError("unknown trick")
            sim.queue_stop(name, zone, fg.canonical(field))
        elif op == "calibrate":
            sim.queue_calibrate(zone, field)
            field = fg.canonical(field)
        elif op == "hidden":
            if sim.revealed:
                raise ValueError("the blind test is over: start a new session for another")
            if len(sim.hidden_log) >= MAX_HIDDEN:
                raise ValueError(f"at most {MAX_HIDDEN} hidden tricks per session")
            sim.queue_hidden()
        elif op == "reveal":
            if not sim.hidden_log:
                raise ValueError("there is no hidden trick to reveal")
            self._reveal()
        else:
            raise ValueError("unknown command")
        item: Dict[str, Any] = {"t": self.tick, "op": op}
        for key, value in (("name", name), ("zone", zone), ("field", field)):
            if value is not None and op in ("start", "stop", "calibrate"):
                item[key] = value
        self.commands.append(item)

    def _reveal(self) -> None:
        """Name the hidden tricks and end them, so their episodes can be graded."""
        self.sim.reveal()
        for entry in self.sim.hidden_log:
            self.sim.queue_stop_hidden(entry["id"])

    # Ticking

    def advance_to(self, tick: int) -> None:
        if tick < self.tick:
            raise ValueError("a command is dated before the session's clock")
        self.advance(tick - self.tick)

    def advance(self, ticks: int) -> int:
        """Run up to `ticks` more readings (never past the 24 h cap). Returns how many ran."""
        ticks = max(0, min(ticks, MAX_TICKS - self.tick))
        for _ in range(ticks):
            for reading in self.sim.step():
                self._take(reading)
        if self.tick >= MAX_TICKS and self.sim.hidden_log and not self.sim.revealed:
            self.sim.reveal()  # the end of the session: nothing left to hide
        return ticks

    def _take(self, reading: Any) -> None:
        truth, event = reading.truth, reading.event
        zone_id, tick = truth["zone_id"], truth["tick"]
        sim = self.sim
        for item in truth.get("calibrations", []):  # before the reading, so the engine has it when it judges it
            self.engine.calibrate(zone_id, item["field"], item["at"], farm_id=sim.farm_id, device_id=truth["device_id"])
        fields = [f for f in sim.zones[zone_id].cfg.sensors if f not in truth["placeholder_fields"]]
        sent = {"timestamp": event["timestamp"], **{f: event[f] for f in fields}} if event else None
        row = {"tick": tick, "zone_id": zone_id, "wall_timestamp": truth["wall_timestamp"],
               "published": event is not None, "sent": sent, "expect": truth["expect"],
               "active_faults": [{"name": f["name"], "field": f["field"], "source": f["source"]}
                                 for f in truth["active_faults"]],
               "active_events": [{"name": e["name"], "source": e["source"]} for e in truth["active_events"]]}
        self.rows.append(row)
        values: Optional[Dict[str, float]] = None
        self.last_note[zone_id] = None
        if event is None:
            self.last_note[zone_id] = "No reading arrived (the sensor is silent)."
        elif not score.core_accepted(row):
            self.last_note[zone_id] = "Core refused the last reading: its clock says 1970."
        else:
            got = self.engine.observe(event)
            self.frame_info[(zone_id, tick)] = {
                "labels": got["labels"], "trust": got["trust"], "vetoed_fields": got["vetoed_fields"],
                "card_labels": got["card_labels"], "sensor_check_labels": got["sensor_check_labels"]}
            self.alert_events += got["alert_events"]
            self.last_got[zone_id] = got
            values = {f: event[f] for f in fields}
            self.last_vals[zone_id] = values
        self.recent[zone_id].append(values)

    # Grading

    def grade(self) -> Dict[str, Any]:
        """The existing Grader over everything so far, as episodes with a verdict (cached per tick)."""
        if self._board and self._board[0] == self.tick:
            return self._board[1]
        grader = score.Grader(self.rows, self.alert_events, RULES, DEFAULTS, self.frame_info)
        real = grader.real_episodes()
        faults = grader.fault_episodes(real)
        board = {"real": real, "faults": faults, "false_alarms": grader.false_alarms(real, faults)}
        self._board = (self.tick, board)
        return board

    def hidden_ticks(self) -> Dict[Tuple[str, str], List[int]]:
        marks: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        for row in self.rows:
            for item in row["active_faults"] + row["active_events"]:
                if item["source"] == "hidden":
                    marks[(row["zone_id"], item["name"])].append(row["tick"])
        return marks

    def episodes(self) -> Dict[str, Any]:
        board, last = self.grade(), self.tick - 1
        masked_marks = {} if self.sim.revealed else self.hidden_ticks()

        def hidden(zone: str, names: List[str], start: int, end: int) -> bool:
            return any(start <= t <= end for name in names for t in masked_marks.get((zone, name), ()))

        out: List[Dict[str, Any]] = []
        for ep in board["real"]:
            names = ep["events"]
            title = " + ".join(TRICKS[n]["title"] for n in names if n in TRICKS) or \
                f"Real problem: {LABEL_WORDS.get(ep['label'], ep['label'])}"
            out.append(self._episode(ep, "real", ep["outcome"], title, ep["zone"], None, names, last, hidden))
        for ep in board["faults"]:
            title = TRICKS[ep["fault"]]["title"]
            out.append(self._episode(ep, "fault", ep["outcome"], title, ep["zone"], ep["field"], [ep["fault"]],
                                     last, hidden))
        out.sort(key=lambda e: (e["start_tick"], e["zone"]))
        alarms = [{"id": f"alarm:{a['zone']}:{a['rule']}:{a['tick']}", "kind": "alarm", "zone": a["zone"],
                   "title": f"{CARD_NAMES.get(a['rule'], a['rule'])} card with nothing wrong", "field": None,
                   "start_tick": a["tick"], "end_tick": a["tick"], "status": "done", "hidden": False,
                   "verdict": "false_alarm", **self._verdict_text("false_alarm", {}, a)} for a in board["false_alarms"]]
        shown = [e for e in out + alarms if not e["hidden"]]
        done = [e for e in shown if e["status"] == "done"]
        counts = lambda codes: sum(1 for e in done if e["verdict"] in codes)  # noqa: E731
        totals = {"fooled": counts(FOOLED), "caught": counts(CAUGHT), "unfair": counts({"undetectable"}),
                  "too_short": counts({"too_short_to_raise"}), "not_scored": counts({"not_published"}),
                  "false_alarms": counts({"false_alarm"}),
                  "running": sum(1 for e in shown if e["status"] == "running"),
                  "hidden_waiting": sum(1 for e in out if e["hidden"])}
        return {"list": sorted(out + alarms, key=lambda e: (e["start_tick"], e["zone"])), "totals": totals}

    def _episode(self, ep: Dict[str, Any], kind: str, outcome: str, title: str, zone: str, field: Optional[str],
                 names: List[str], last: int, hidden: Any) -> Dict[str, Any]:
        running = ep["end_tick"] >= last
        masked = hidden(zone, names, ep["start_tick"], ep["end_tick"])
        item: Dict[str, Any] = {
            "id": f"{kind}:{zone}:{'+'.join(names) or ep.get('label')}:{ep['start_tick']}", "kind": kind, "zone": zone,
            "title": "Hidden trick" if masked else title, "field": None if masked else field,
            "start_tick": ep["start_tick"], "end_tick": ep["end_tick"],
            "status": "running" if running else "done", "hidden": masked}
        if masked:  # nothing that names the trick: not its id, not whether it was a sensor lie or a real event
            return {**item, "id": f"hidden:{zone}:{ep['start_tick']}", "kind": "hidden", "verdict": None,
                    "headline": "Pomona's blind test: the verdict comes with the reveal.",
                    "why": "", "doc": "", "class": "hidden"}
        item.update(verdict=outcome, **self._verdict_text(outcome, ep, None, running))
        return item

    @staticmethod
    def _verdict_text(code: str, ep: Dict[str, Any], alarm: Optional[Dict[str, Any]] = None,
                      running: bool = False) -> Dict[str, Any]:
        spec = VERDICTS.get(code, VERDICTS["missed"])
        raised = ep.get("raised") or {}
        if raised and not raised.get("already_active"):
            after = f" (after {max(1, round(raised['delay_s'] / 60))} min)"
        else:
            after = " (a sensor card was already open)" if raised else ""
        card = CARD_TITLES.get((ep.get("wrong_cards") or [{}])[0].get("rule", ""), "a card")
        minutes = max(1, round(ep.get("raise_after_s", 600) / 60))
        headline = spec["headline"].format(after=after, card=card, n=minutes)
        if running:  # not over yet: say what Pomona has done so far, grade it when it ends
            headline = ("Still running. Pomona has raised its card so far" + after) if code in CAUGHT \
                else "Still running. Pomona has only raised a card since your trick ended" if code == "caught_at_recovery" \
                else "Still running. Pomona has not raised a card yet"
        return {"headline": headline, "why": spec["why"], "doc": spec["doc"], "class": "running" if running else spec["class"]}

    # The picture

    def timeline(self) -> Dict[str, Any]:
        """Per zone: bands for the tricks (names hidden until the reveal) and bands for Pomona's cards."""
        reveal = self.sim.revealed
        tricks: Dict[str, List[Dict[str, Any]]] = {z: [] for z in self.sim.zones}
        open_bands: Dict[Tuple[str, str, Optional[str], bool], Dict[str, Any]] = {}
        for row in self.rows:
            seen = set()
            for item, field in [(i, i.get("field")) for i in row["active_faults"]] + \
                    [(i, None) for i in row["active_events"]]:
                is_hidden = item["source"] == "hidden"
                key = (row["zone_id"], item["name"], field, is_hidden)
                seen.add(key)
                band = open_bands.get(key)
                if band is None or band["end_tick"] < row["tick"] - 1:
                    band = open_bands[key] = {
                        "name": item["name"] if reveal or not is_hidden else "hidden",
                        "title": TRICKS[item["name"]]["title"] if reveal or not is_hidden else "Hidden trick",
                        "field": field if reveal or not is_hidden else None, "hidden": is_hidden and not reveal,
                        "start_tick": row["tick"], "end_tick": row["tick"]}
                    tricks[row["zone_id"]].append(band)
                band["end_tick"] = row["tick"]
        cards: Dict[str, List[Dict[str, Any]]] = {z: [] for z in self.sim.zones}
        open_cards: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for event in self.alert_events:
            key, tick = (event["zone_id"], event["rule_id"]), tick_of(event["sample_time"])
            if event["event"] == "raised":
                band = {"rule": event["rule_id"], "title": CARD_NAMES.get(event["rule_id"], event["rule_id"]),
                        "sensor": event["action"] == ipp.SENSOR_ACTION, "start_tick": tick, "end_tick": None}
                open_cards[key] = band
                cards[event["zone_id"]].append(band)
            elif key in open_cards:
                open_cards.pop(key)["end_tick"] = tick
        return {"tricks": tricks, "cards": cards}

    def view(self) -> Dict[str, Any]:
        sim, last = self.sim, self.tick - 1
        state = sim.state()
        states = self.engine.states(sim.farm_id)
        zones = []
        for zone_id, zone in sim.zones.items():
            letter, system = ZONE_LABELS.get(zone_id, (zone_id, zone.cfg.system_type))
            fields = [f for f in zone.cfg.sensors if f not in zone.placeholder_fields]
            got = self.last_got.get(zone_id)
            vetoed = {"soil_moisture_pct" if f == "substrate_moisture_pct" else f for f in (got or {}).get("vetoed_fields", [])}
            values = self.last_vals.get(zone_id, {})
            history = list(self.recent[zone_id])
            ticks_back = range(len(history) - 1, -1, -SERIES_STRIDE)
            series = {f: [(history[i] or {}).get(f) for i in sorted(ticks_back)] for f in fields}
            trick_state = next(z for z in state["zones"] if z["zone_id"] == zone_id)
            active = [{"name": i["name"], "title": TRICKS[i["name"]]["title"], "field": i["field"],
                       "stopping": i["stopping"], "pending": False, "since_tick": i["started_tick"]}
                      for i in trick_state["injections"]]
            active += [{"name": c["name"], "title": TRICKS[c["name"]]["title"], "field": c["field"], "stopping": False,
                        "pending": True, "since_tick": self.tick} for c in state["pending"]
                       if c["op"] == "start" and c["zone"] == zone_id]
            cards = [self._card(s) for s in states if s["zone_id"] == zone_id and s["state"] in ("active", "recovering", "pending")]
            zones.append({
                "id": zone_id, "letter": letter, "system": system, "fields": [
                    {"key": f, "label": FIELD_LABELS[f][0], "unit": FIELD_LABELS[f][1], "value": values.get(f),
                     "vetoed": f in vetoed, "series": series[f]} for f in fields],
                "trust": got["trust"] if got else None, "labels": [LABEL_WORDS.get(x, x.replace("_", " ")) for x in (got or {}).get("labels", [])],
                "cards": cards, "tricks": active, "note": self.last_note[zone_id],
                "calibratable": zone.calibratable})
        hidden = {"running": sum(1 for h in state["hidden"]), "revealed": state["revealed"],
                  "total": len(sim.hidden_log), "items": []}
        if state["revealed"]:
            hidden["items"] = [{"id": h["id"], "title": TRICKS[h["name"]]["title"], "zone": h["zone"], "field": h["field"],
                                "started_tick": h["started_tick"]} for h in sim.reveal() if h["started_tick"] is not None]
        episodes = self.episodes()
        elapsed_min = self.tick * TICK_S / 60
        return {
            "clock": {"tick": self.tick, "sim_time": tick_iso(self.tick), "start_time": tick_iso(0),
                      "elapsed_min": elapsed_min, "cap_min": MAX_TICKS * TICK_S / 60, "at_cap": self.tick >= MAX_TICKS,
                      "tick_seconds": TICK_S},
            "zones": zones, "hidden": hidden, "episodes": episodes["list"], "totals": episodes["totals"],
            "timeline": self.timeline(), "scenario": self.scenario(), "export": self.export()}

    @staticmethod
    def _card(state: Dict[str, Any]) -> Dict[str, Any]:
        return {"rule": state["rule_id"], "title": CARD_NAMES.get(state["rule_id"], state["rule_id"]),
                "state": state["state"], "message": state["message"], "since_tick": tick_of(state["since"]),
                "sensor": state["action"] == ipp.SENSOR_ACTION}

    def export(self) -> Dict[str, Any]:
        """The session as a scenario file `make fake-greenhouse SCENARIO=...` loads (hidden steps only once revealed)."""
        scenario = self.sim.session_scenario()
        if not self.sim.revealed:
            scenario["steps"] = [s for s in scenario["steps"] if s.get("source") != "hidden"]
        scenario["duration_ticks"] = self.tick
        scenario["description"] = (f"Exported from the Try to fool Pomona Space ({GITHUB}). Seed {self.seed}, "
                                   f"{self.tick} ticks of {TICK_S} s.")
        return scenario


def info() -> Dict[str, Any]:
    """Static facts for the page: the tricks, zones and fields to choose from, the verdict table, the caps."""
    sim = fg.Simulation()
    catalog = sim.catalog()
    zones = [{"id": z["zone_id"], "letter": ZONE_LABELS[z["zone_id"]][0], "system": ZONE_LABELS[z["zone_id"]][1],
              "fields": [f for f in z["sensors"] if not (z["zone_id"] == "greenhouse-b" and f == "soil_moisture_pct")],
              "calibratable": z["calibratable"]} for z in catalog["zones"]]
    tricks = []
    for item in catalog["injections"]:
        if item["name"] not in TRICKS:  # a simulator injection the game does not offer (the blind-spot scenario's probe_dropout)
            continue
        meta = TRICKS[item["name"]]
        tricks.append({"name": item["name"], "title": meta["title"], "blurb": meta["blurb"], "group": meta["group"],
                       "takes_field": item["takes_field"], "needs_field": item["needs_field"],
                       "default_field": item["default_field"], "zones": item["zones"]})
    return {"zones": zones, "tricks": tricks, "fields": {k: {"label": v[0], "unit": v[1]} for k, v in FIELD_LABELS.items()},
            "verdicts": [{"code": code, **{k: v for k, v in spec.items() if k != "scorer"}, "scorer": spec["scorer"]}
                         for code, spec in VERDICTS.items()],
            "caps": {"max_hours": MAX_HOURS, "tick_seconds": TICK_S, "max_advance_ticks": MAX_ADVANCE_TICKS,
                     "warmup_ticks": WARMUP_TICKS, "series_stride": SERIES_STRIDE, "series_ticks": SERIES_TICKS},
            "windows": {"default_min": DEFAULTS[0] // 60, "humidity_min": 30,
                        "sensor_check_samples": next((r.get("raise_after_samples") for r in RULES if r["id"] == "sensor_check"), None)},
            "build": build_info()}


def build_info() -> Dict[str, Any]:
    path = ENGINE_ROOT / "BUILD_INFO.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"commit": None, "short_commit": None, "dirty": None}
    return {"commit": data.get("commit"), "short_commit": data.get("short_commit"), "dirty": data.get("dirty")}
