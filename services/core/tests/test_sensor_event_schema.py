"""schemas/sensor-event.schema.json and Core's SensorEvent must accept and reject the same packets.

`jsonschema` is not a Core dependency, so the schema is checked by a small evaluator for the keywords the schema uses
(type, required, properties, anyOf, min/max, length, pattern, date-time) and structurally against the model's fields.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]

from app.schemas import MAX_SOURCE_LENGTH, READING_FIELDS, NpkTargetReading, SensorEvent, WeatherReading

SCHEMA = json.loads((SERVICE_DIR.parents[1] / "schemas" / "sensor-event.schema.json").read_text())
DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(\.\d+)?([Zz]|[+-]\d{2}:\d{2})$")


def has_type(value, name) -> bool:
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if name == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, {"string": str, "boolean": bool, "object": dict, "null": type(None)}[name])


def accepts(schema: dict, value) -> bool:
    """Whether `value` is valid under `schema`: the JSON Schema keywords sensor-event.schema.json uses, nothing more."""
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(has_type(value, name) for name in names):
            return False
    if "anyOf" in schema and not any(accepts(option, value) for option in schema["anyOf"]):
        return False
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", float("inf")):
            return False
        if "pattern" in schema and not re.search(schema["pattern"], value):
            return False
        if schema.get("format") == "date-time" and not DATE_TIME.match(value):
            return False
    if has_type(value, "number"):
        if value < schema.get("minimum", float("-inf")) or value > schema.get("maximum", float("inf")):
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
    if isinstance(value, dict):
        if any(name not in value for name in schema.get("required", [])):
            return False
        if any(name in value and not accepts(sub, value[name]) for name, sub in schema.get("properties", {}).items()):
            return False
    return True


def core_accepts(payload: dict) -> bool:
    try:
        SensorEvent.model_validate(payload)
    except ValidationError:
        return False
    return True


def packet(**updates) -> dict:
    body = {"device_id": "node", "farm_id": "farm", "zone_id": "a", "ph": 6.2,
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), **updates}
    return {key: value for key, value in body.items() if value is not ...}  # `...` removes a key


WEATHER = {"t_mean_c": 20, "t_min_c": 12, "t_max_c": 28, "rh_mean_pct": 60, "wind_speed_2m_ms": 2, "solar_radiation_mj_m2_day": 18}
NPK = {"n_ppm": 150, "p_ppm": 50, "k_ppm": 200, "volume_liters": 500}
FULL = packet(crop="tomato", growth_stage="fruiting", system_type="hydroponic", air_temperature_c=24.5, humidity_pct=61,
              ec_ms_cm=2.1, soil_moisture_pct=40, substrate_temperature_c=21, substrate_moisture_pct=55,
              weather={**WEATHER, "elevation_m": 120}, zone_area_m2=80, crop_kc=1.05, npk_target=NPK, source="esp32",
              received_at="2026-07-21T10:00:00Z", sequence=7, boot_id="boot-1", mqtt_retained=False, schema_version="1.3")

VALID = {
    "minimal": packet(),
    "full": FULL,
    "partial: other readings null": packet(ph=None, ec_ms_cm=2.0, air_temperature_c=None),
    "defaults filled by Core: no crop, stage or system type": packet(crop=...),
    "readings at the bounds": packet(ph=0, ec_ms_cm=20, air_temperature_c=-40, humidity_pct=100, substrate_temperature_c=80),
    "offset timestamp": packet(timestamp="2026-07-21T14:00:00+04:00"),
    "unknown property is ignored": packet(future_field={"a": 1}),
    "null optional context": packet(weather=None, npk_target=None, zone_area_m2=None, crop_kc=None, sequence=None, boot_id=None, source=None),
    "source of 64 characters": packet(source="s" * 64),
    "a 1.x schema version": packet(schema_version="1.12"),
    "weather without elevation": packet(weather=WEATHER),
}
INVALID = {
    "no reading at all": packet(ph=...),
    "only null readings": packet(ph=None, ec_ms_cm=None),
    "context is not a reading": packet(ph=..., zone_area_m2=50, crop_kc=1.0, weather=WEATHER, npk_target=NPK),
    "no device_id": packet(device_id=...),
    "no farm_id": packet(farm_id=...),
    "no zone_id": packet(zone_id=...),
    "no timestamp": packet(timestamp=...),
    "timestamp without a timezone": packet(timestamp="2026-07-21T10:00:00"),
    "timestamp not a time": packet(timestamp="yesterday"),
    "empty device_id": packet(device_id=""),
    "device_id too long": packet(device_id="d" * 129),
    "empty crop": packet(crop=""),
    "system_type too long": packet(system_type="s" * 65),
    "source too long": packet(source="s" * 65),
    "ph above 14": packet(ph=14.1),
    "ph below 0": packet(ph=-0.1),
    "air temperature above 80": packet(air_temperature_c=80.1),
    "air temperature below -40": packet(air_temperature_c=-40.1),
    "humidity above 100": packet(humidity_pct=100.1),
    "ec above 20": packet(ec_ms_cm=20.1),
    "negative soil moisture": packet(soil_moisture_pct=-1),
    "substrate moisture above 100": packet(substrate_moisture_pct=101),
    "boolean as a number": packet(ph=True),
    "text as a number": packet(ph="bad"),
    "other major schema version": packet(schema_version="2.0"),
    "malformed schema version": packet(schema_version="1.0.0"),
    "negative sequence": packet(sequence=-1),
    "fractional sequence": packet(sequence=1.5),
    "sequence as text": packet(sequence="3"),
    "empty boot_id": packet(boot_id=""),
    "zone_area_m2 zero": packet(zone_area_m2=0),
    "zone_area_m2 too large": packet(zone_area_m2=1_000_001),
    "crop_kc above 3": packet(crop_kc=3.1),
    "weather missing a field": packet(weather={k: v for k, v in WEATHER.items() if k != "t_min_c"}),
    "weather temperature above 60": packet(weather={**WEATHER, "t_mean_c": 61}),
    "weather elevation too high": packet(weather={**WEATHER, "elevation_m": 6001}),
    "npk volume zero": packet(npk_target={**NPK, "volume_liters": 0}),
    "npk missing a field": packet(npk_target={k: v for k, v in NPK.items() if k != "k_ppm"}),
    "npk n_ppm above 1000": packet(npk_target={**NPK, "n_ppm": 1001}),
    "mqtt_retained as text": packet(mqtt_retained="maybe"),
}


@pytest.mark.parametrize("name", VALID)
def test_a_packet_the_schema_accepts_core_accepts(name):
    assert accepts(SCHEMA, VALID[name]), "the schema should accept this packet"
    assert core_accepts(VALID[name])


@pytest.mark.parametrize("name", INVALID)
def test_a_packet_the_schema_rejects_core_rejects(name):
    assert not accepts(SCHEMA, INVALID[name]), "the schema should reject this packet"
    assert not core_accepts(INVALID[name])


def bounds(field) -> dict:
    """A model field's numeric and length limits, named as in JSON Schema."""
    names = {"ge": "minimum", "le": "maximum", "gt": "exclusiveMinimum", "min_length": "minLength", "max_length": "maxLength"}
    return {names[key]: getattr(item, key) for item in field.metadata for key in names if getattr(item, key, None) is not None}


def check_fields(model, schema: dict, validator_bounds=None) -> None:
    """`validator_bounds`: limits the model enforces in a validator (not field metadata), by field name."""
    assert set(schema["properties"]) == set(model.model_fields), "schema properties differ from the model's fields"
    assert set(schema.get("required", [])) == {name for name, f in model.model_fields.items() if f.is_required()}
    for name, field in model.model_fields.items():
        sub = schema["properties"][name]
        assert {k: v for k, v in sub.items() if k in ("minimum", "maximum", "exclusiveMinimum", "minLength", "maxLength")} == {**bounds(field), **(validator_bounds or {}).get(name, {})}, name
        if not field.is_required() and field.default is not None and isinstance(field.default, (str, int, float)) and not isinstance(field.default, bool):
            assert sub.get("default") == field.default, f"{name} default"
        if field.is_required():
            assert "null" not in (sub["type"] if isinstance(sub["type"], list) else [sub["type"]]), f"{name} is required, not nullable"


def test_the_schema_has_the_models_fields_bounds_defaults_and_required_set():
    check_fields(SensorEvent, SCHEMA, {"source": {"maxLength": MAX_SOURCE_LENGTH}})
    check_fields(WeatherReading, SCHEMA["properties"]["weather"])
    check_fields(NpkTargetReading, SCHEMA["properties"]["npk_target"])


def test_the_at_least_one_reading_rule_names_the_models_reading_fields():
    assert [next(iter(option["required"])) for option in SCHEMA["anyOf"]] == list(READING_FIELDS)
    for option in SCHEMA["anyOf"]:  # a reading counts only as a number: null does not
        assert next(iter(option["properties"].values())) == {"type": "number"}


def test_the_evaluator_itself_tells_good_from_bad():
    assert accepts({"type": "number", "minimum": 1}, 1) and not accepts({"type": "number", "minimum": 1}, 0.5)
    assert not accepts({"type": "number"}, True) and not accepts({"type": "integer"}, 1.5)
    assert not accepts({"type": "string", "maxLength": 2}, "abc") and accepts({"type": ["string", "null"]}, None)
