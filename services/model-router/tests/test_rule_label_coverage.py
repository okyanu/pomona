"""Every label a reasoner can emit either matches an automation rule or is listed here as "no card on purpose".

A label with no rule is dropped by the automation engine: the operator sees nothing, however serious the reading.
That is how `sensor_anomaly` (an extreme pH or EC the sensor check still accepts) and the water reasoner's moisture
labels went without a card. The emitted labels are read from the reasoners' own label sets, so a label added to a
reasoner shows up here without anyone remembering to update this file.
"""

import ast
import sys
from pathlib import Path

import yaml

SERVICE_DIR = Path(__file__).resolve().parents[1]
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))

from app import nutrient_ph_ec, sensor_quality, tomato_reasoner, water_irrigation

RULES_PATH = Path(__file__).resolve().parents[2] / "automation-engine" / "app" / "rules.yaml"

# Labels that deliberately make no card. Every entry needs its reason; a new label needs a rule instead, unless it
# has a reason that belongs here.
NO_CARD_ON_PURPOSE = {
    "nutrient_uptake_issue": "only ever emitted together with high_ph, low_ph, high_ec or low_ec, which have their own cards",
    "missing_critical_data": "repeats the sensor check's missing_* labels (sensor_check card); the tomato reasoner's list also "
                             "has substrate_temperature_c, which the sensor check does not expect, so that one gap shows no card",
    "stale_irrigation_data": "the water reasoner's own stale test (fixed timestamps); a stale packet is the sensor check's "
                             "stale_reading, which has a sensor_check card",
    "actuator_conflict": "only blocks direct_actuator_control in the safety gate; needs actuator states that Core packets do "
                         "not carry yet, so there is nothing for an operator card to say (owner to confirm)",
}


def rule_labels() -> set:
    rules = yaml.safe_load(RULES_PATH.read_text())["rules"]
    return {label for rule in rules for label in rule["match_any_labels"]}


def sensor_quality_labels() -> set:
    """The sensor-quality reasoner has no label tuple: read the labels it adds from its own source."""
    labels = set(sensor_quality.FIELD_LABELS.values())
    for node in ast.walk(ast.parse(Path(sensor_quality.__file__).read_text())):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "add_unique" and len(node.args) == 2 \
                and isinstance(node.args[0], ast.Name) and node.args[0].id == "labels":
            labels |= {c.value for c in ast.walk(node.args[1]) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        elif isinstance(node, ast.Dict):  # the early returns: {"data_quality_labels": ["insufficient_context"], ...}
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "data_quality_labels" and isinstance(value, ast.List):
                    labels |= {c.value for c in value.elts if isinstance(c, ast.Constant)}
    return labels


def emitted_labels() -> set:
    return (tomato_reasoner.ALLOWED_RISK_LABELS | nutrient_ph_ec.ALLOWED_LABELS | water_irrigation.ALLOWED_LABELS
            | sensor_quality_labels())


def test_every_emitted_label_has_a_rule_or_a_reason_for_none():
    unmatched = emitted_labels() - rule_labels() - set(NO_CARD_ON_PURPOSE)
    assert not unmatched, (
        f"{sorted(unmatched)} can be emitted by a reasoner but no rule in {RULES_PATH.name} matches it: the operator "
        "would see no card. Add the label to a rule, or to NO_CARD_ON_PURPOSE with a reason.")


def test_no_card_list_holds_only_emitted_labels_without_a_rule():
    assert set(NO_CARD_ON_PURPOSE) <= emitted_labels(), "a label in NO_CARD_ON_PURPOSE is no longer emitted: remove it"
    assert not set(NO_CARD_ON_PURPOSE) & rule_labels(), "a label in NO_CARD_ON_PURPOSE now has a rule: remove it"
    assert all(reason.strip() for reason in NO_CARD_ON_PURPOSE.values())


def test_the_label_scan_finds_the_sensor_quality_labels_the_rules_know():
    # If the scan of sensor_quality.py broke, the first test would pass on a short list: tie it to the rules.
    sensor_rule = next(rule for rule in yaml.safe_load(RULES_PATH.read_text())["rules"] if rule["id"] == "sensor_check")
    assert set(sensor_rule["match_any_labels"]) <= sensor_quality_labels()
    assert {"flatline_possible", "stuck_value", "impossible_ph"} <= sensor_quality_labels()
