"""Tests for the false-reassurance ("blind spot") cases: a real event runs and the probe that would show it goes silent.

Run with the Core venv (it provides pytest and Core's SensorEvent). The end-to-end replay through the real pipeline
is in scripts/tests/test_score_fake_greenhouse.py (model-router venv).
"""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[3]
SIM_DIR = ROOT / "examples" / "simulators"
sys.path.insert(0, str(SIM_DIR))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "services" / "core"))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

import fake_greenhouse as fg
import score_fake_greenhouse as score
from app.schemas import SensorEvent

A, B = "greenhouse-a", "greenhouse-b"
BASE = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
RULES = score.parse_rules(score.AUTOMATION_APP.joinpath("rules.yaml").read_text())
DEFAULTS = (600, 900)
SCENARIOS = SIM_DIR / "scenarios"


def make_clock(step_s: float = 30.0):
    state = {"now": BASE}

    def clock() -> datetime:
        now = state["now"]
        state["now"] = now + timedelta(seconds=step_s)
        return now

    return clock


def run_scenario(path, ticks=None, seed=None):
    scenario = fg.load_scenario(Path(path))
    sim = fg.Simulation(seed=seed if seed is not None else scenario.get("seed", 42), clock=make_clock(), scenario=scenario)
    return [r for _ in range(ticks or scenario["duration_ticks"]) for r in sim.step()]


# --- The simulator ---------------------------------------------------------------------------

def test_core_required_matches_the_sensor_event_schema():
    required = {name for name, field in SensorEvent.model_fields.items() if field.is_required()}
    assert set(fg.CORE_REQUIRED) <= required
    assert required - set(fg.CORE_REQUIRED) == {"device_id", "farm_id", "zone_id", "timestamp"}


def test_blind_spot_scenario_loads_and_every_dropout_leaves_the_probe_out():
    readings = run_scenario(SCENARIOS / "blind_spot.json")
    seen = set()
    for r in readings:
        silent = r.truth["expect"].get("silent_fields", [])
        for field in silent:
            seen.add((r.truth["zone_id"], field))
            assert field not in r.event  # the key is absent, not null
            if field == "soil_moisture_pct":
                assert "substrate_moisture_pct" not in r.event
            assert [f["name"] for f in r.truth["active_faults"]] == ["probe_dropout"]
            assert r.truth["expect"]["forbid_domain_cards_from"] == [] and r.truth["expect"]["recovering_from"] == []
        assert {"air_temperature_c", "humidity_pct", "ec_ms_cm", "ph"} - set(silent) <= set(r.event)  # the others still report
    assert seen == {(A, "soil_moisture_pct"), (A, "air_temperature_c"), (A, "ec_ms_cm"), (A, "substrate_temperature_c"),
                    (B, "ec_ms_cm"), (B, "humidity_pct"), (B, "air_temperature_c")}


def test_core_refuses_a_packet_missing_a_required_field_and_accepts_a_missing_optional_one():
    readings = run_scenario(SCENARIOS / "blind_spot.json")
    refused = accepted = 0
    for r in readings:
        expect = r.truth["expect"]
        if not expect.get("silent_fields"):
            SensorEvent.model_validate(r.event)  # a complete packet is fine
            continue
        required_gone = any(f in fg.CORE_REQUIRED for f in expect["silent_fields"])
        assert bool(expect.get("core_rejects")) == required_gone
        try:
            SensorEvent.model_validate(r.event)
            accepted += 1
            assert not required_gone
        except ValidationError:
            refused += 1
            assert required_gone  # the schema agrees with what the truth log says Core does
    assert refused > 300 and accepted > 50


def test_probe_dropout_is_a_sensor_fault_that_sends_no_lie_and_leaves_no_recovery_tail():
    cls = fg.REGISTRY["probe_dropout"]
    assert cls.kind == "sensor_fault" and cls.needs_field and not cls.hideable
    scenario = {"steps": [{"at_tick": 2, "start": "probe_dropout", "zone": B, "field": "ph"},
                          {"at_tick": 5, "stop": "probe_dropout", "zone": B}]}
    sim = fg.Simulation(seed=1, clock=make_clock(), scenario=scenario)
    rows = [r for _ in range(20) for r in sim.step() if r.truth["zone_id"] == B]
    base = fg.Simulation(seed=1, clock=make_clock())
    base_rows = [r for _ in range(20) for r in base.step() if r.truth["zone_id"] == B]
    for r, b in zip(rows, base_rows):
        assert r.truth["true"] == b.truth["true"]
        assert {k: v for k, v in r.event.items() if k != "ph"} == {k: v for k, v in b.event.items() if k != "ph"}
        assert ("ph" in r.event) == (not 2 <= r.truth["tick"] < 5)
        assert r.truth["expect"]["recovering_from"] == []


def test_probe_dropout_needs_a_field_the_zone_has():
    sim = fg.Simulation(clock=make_clock())
    with pytest.raises(ValueError):
        sim.validate_start("probe_dropout", B, "soil_moisture_pct", {})
    with pytest.raises(ValueError):
        sim.validate_start("probe_dropout", A, None, {})


def test_hidden_random_never_picks_probe_dropout():
    for seed in range(1, 6):
        sim = fg.Simulation(seed=seed, clock=make_clock())
        for _ in range(12):
            sim.queue_hidden()
        assert "probe_dropout" not in {e["name"] for e in sim.hidden_log}


@pytest.mark.parametrize("name", ["smoke", "quick", "validation", "cold", "demo"])
def test_existing_scenarios_carry_no_blind_spot_marks(name):
    ticks = 60
    for r in run_scenario(SCENARIOS / f"{name}.json", ticks=ticks):
        assert "silent_fields" not in r.truth["expect"] and "core_rejects" not in r.truth["expect"]
        assert "probe_dropout" not in json.dumps(r.truth["active_faults"])


# --- The verdict, on hand-built truth logs -----------------------------------------------------

def row(tick, zone=A, silent=None, events=(), expected=(), accepted=True):
    """One truth-log line at 30 s ticks. `silent` is the field a probe_dropout is on; `accepted` says whether Core stored it."""
    wall = BASE + timedelta(seconds=30 * tick)
    expect = {"kind": "real_event" if events else "normal", "expected_labels": list(expected),
              "forbid_domain_cards_from": [], "detectable": True, "onset_step": False, "recovering_from": []}
    if silent:
        expect["silent_fields"] = [silent]
        if not accepted:
            expect["core_rejects"] = True
    return {"tick": tick, "wall_timestamp": wall.isoformat(), "zone_id": zone, "device_id": f"dev-{zone}", "published": True,
            "sent": {"farm_id": "demo-farm", "zone_id": zone, "device_id": f"dev-{zone}", "timestamp": wall.isoformat()},
            "active_faults": [{"name": "probe_dropout", "field": silent}] if silent else [],
            "active_events": [{"name": "nutrient_over_concentration", "field": None}] if events else [],
            "expect": expect}


def case_rows(field="ec_ms_cm", label="high_ec", accepted=False, total=90, silent=(10, 70), event=(8, 70), cross=30, zone=A):
    """Warm-up, then an event with the probe silent from tick 10 (`accepted`: Core still stores the packets)."""
    out = []
    for t in range(total):
        quiet = silent[0] <= t < silent[1]
        running = event[0] <= t < event[1]
        out.append(row(t, zone, field if quiet else None, events=("e",) if running else (),
                       expected=[label] if running and t >= cross else [], accepted=accepted or not quiet))
    return out


def raised(zone, rule, tick):
    stamp = (BASE + timedelta(seconds=30 * tick)).isoformat().replace("+00:00", "Z")
    return {"zone_id": zone, "farm_id": "demo-farm", "rule_id": rule, "event": "raised", "sample_time": stamp}


def grade(rows, events=(), info=None):
    return score.Grader(rows, list(events), RULES, DEFAULTS, info).report()


def only_case(report):
    (case,) = report["blind_spot_cases"]
    return case


def test_nothing_shown_while_the_fault_runs_is_false_reassurance():
    # The probe goes silent but Core keeps storing packets (an optional field), nothing flags it, no card comes.
    report = grade(case_rows(accepted=True))
    case = only_case(report)
    assert case["outcome"] == "false_reassurance" and case["via"] == [] and case["signal"] is None
    assert report["summary"]["blind_spot"]["false_reassurance"] == 1
    assert score.failures(report) == 1  # --fail-on-miss fails on it
    # the real episode it hid is not counted as a plain miss
    (episode,) = report["real_episodes"]
    assert episode["outcome"] == "blind_spot" and report["summary"]["real_episodes"]["missed"] == 0


def test_a_zone_gone_silent_is_cant_confirm_through_the_device_flag_only():
    report = grade(case_rows(accepted=False))
    case = only_case(report)
    assert case["outcome"] == "cant_confirm" and case["via"] == ["device silent"] and case["silent_flag_only"]
    # the flag turns on the device timeout (120 s) after the last accepted reading (tick 9)
    assert case["signal"]["time"] == BASE + timedelta(seconds=30 * 9 + 120)
    assert case["core_refused_frames"] == 60
    assert report["summary"]["blind_spot"]["cant_confirm_by_silent_flag_only"] == 1 and score.failures(report) == 0


def test_a_sensor_card_is_cant_confirm_and_comes_first_when_earlier():
    report = grade(case_rows(accepted=True), [raised(A, "sensor_check", 14)])
    case = only_case(report)
    assert case["outcome"] == "cant_confirm" and case["via"] == ["sensor card"] and not case["silent_flag_only"]
    assert case["signal"]["time"] == BASE + timedelta(seconds=30 * 14)


def test_a_flagged_reading_for_that_field_is_cant_confirm_offline_only():
    rows = case_rows(accepted=True)
    info = {(A, t): {"labels": [], "trust": "trusted", "vetoed_fields": [], "card_labels": [], "sensor_check_labels": []}
            for t in range(len(rows))}
    assert only_case(grade(rows, info=info))["outcome"] == "false_reassurance"
    info[(A, 20)]["vetoed_fields"] = ["ec_ms_cm"]
    case = only_case(grade(rows, info=info))
    assert case["outcome"] == "cant_confirm" and case["via"] == ["reading flagged"]
    info[(A, 20)]["vetoed_fields"] = ["ph"]  # another probe's veto is not about this field
    assert only_case(grade(rows, info=info))["outcome"] == "false_reassurance"
    info[(A, 20)]["labels"] = ["missing_ec"]  # but the missing-data label for it is
    assert only_case(grade(rows, info=info))["via"] == ["reading flagged"]


def test_the_events_own_card_while_the_probe_is_silent_is_alerted():
    case = only_case(grade(case_rows(accepted=True), [raised(A, "high_ec_alert", 40)]))
    assert case["outcome"] == "alerted" and case["via"] == ["event card"] and case["domain_card"]["rule"] == "high_ec_alert"


def test_a_card_raised_after_the_probe_came_back_does_not_count_for_the_silence():
    report = grade(case_rows(accepted=True), [raised(A, "high_ec_alert", 80)])
    assert only_case(report)["outcome"] == "false_reassurance"


def test_too_short_a_silence_is_not_judged():
    report = grade(case_rows(accepted=True, silent=(10, 13), event=(8, 20), cross=11, total=40))
    assert only_case(report)["outcome"] == "too_short_to_judge" and score.failures(report) == 0


def test_a_probe_silent_while_nothing_crossed_or_no_event_runs_is_not_judged():
    assert only_case(grade(case_rows(cross=200)))["outcome"] == "no_fault_in_window"
    assert only_case(grade(case_rows(event=(0, 0))))["outcome"] == "no_real_event"
    # the label belongs to another probe: heat is not decided by the EC probe
    assert only_case(grade(case_rows(label="heat_stress")))["outcome"] == "no_fault_in_window"


def test_the_label_decides_which_silent_probe_matters():
    for field, label in (("soil_moisture_pct", "water_level_risk"), ("air_temperature_c", "heat_stress"),
                         ("humidity_pct", "fungal_pressure"), ("ph", "high_ph")):
        assert only_case(grade(case_rows(field=field, label=label)))["labels"] == [label]


def test_a_real_miss_with_the_probe_back_long_enough_is_still_a_miss():
    # Silent for 6 minutes, back for the rest of a 30 minute episode, never a card: the silence is not the reason.
    rows = case_rows(accepted=False, silent=(10, 22), event=(8, 80), cross=12, total=100)
    report = grade(rows)
    (episode,) = report["real_episodes"]
    assert episode["outcome"] == "missed" and report["summary"]["real_episodes"]["missed"] == 1


def test_a_card_in_the_silence_is_not_a_false_alarm_and_a_probe_dropout_is_no_sensor_fault_episode():
    report = grade(case_rows(accepted=True), [raised(A, "sensor_check", 14)])
    assert report["summary"]["false_alarms"] == 0
    assert report["fault_episodes"] == [] and report["summary"]["sensor_fault_episodes"]["total"] == 0


def test_cases_come_sorted_and_the_markdown_has_the_blind_spot_table():
    rows = case_rows(zone=A, accepted=False) + case_rows(zone=B, field="humidity_pct", label="fungal_pressure", accepted=True)
    report = grade(rows)
    assert [c["zone"] for c in report["blind_spot_cases"]] == [A, B]
    text = score.markdown(report, "offline", Path("t.jsonl"))
    assert "## Blind spots" in text and "FALSE REASSURANCE" in text and "passive flag only" in text
    assert "Blind spots (a probe silent while a real event runs): 2; FALSE REASSURANCE 1" in text
    assert "false_reassurance" in report["metric_definitions"] and "cant_confirm" in report["metric_definitions"]


def test_core_accepted_follows_the_delivery_then_the_truth():
    refused = row(3, silent="ec_ms_cm", accepted=False)
    assert not score.core_accepted(refused)
    assert score.core_accepted({**refused, "delivery": {"status": 201}})  # a real Core answer wins
    assert not score.core_accepted({**row(3, silent="ec_ms_cm"), "delivery": {"status": 422}})
    assert score.core_accepted(row(3, silent="substrate_temperature_c"))  # an optional field: Core stores it


def test_reports_of_runs_without_a_silent_probe_keep_their_shape():
    rows = [row(t) for t in range(40)]
    report = grade(rows)
    assert "blind_spot" not in report["summary"] and "blind_spot_cases" not in report
    assert "blind_spot" not in report["summary"]["real_episodes"]
    assert "false_reassurance" not in report["metric_definitions"]
    assert "Blind spots" not in score.markdown(report, "offline", Path("t.jsonl"))
