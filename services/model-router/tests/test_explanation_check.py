import asyncio
import sys
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from app import advisor
from app.explanation_check import (
    BINDING_TABLE,
    GroundingViolation,
    NumberSpan,
    OtherSource,
    ReadingSource,
    VPD_FIELD,
    bound_fields,
    grounding_violations,
    normalize,
    number_sources,
    number_spans,
    numbers_in,
    permitted_numbers,
    text_sources,
    unsupported_numbers,
)

SENSOR = {
    "air_temperature_c": 31.0,
    "humidity_pct": 86.5,
    "ec_ms_cm": 3.8,
    "ph": 6.84,
    "crop": "tomato",
}
INSTRUCTION = "Explain the readings."


def bad(text, sensor=None, instruction=INSTRUCTION, context=None):
    permitted = permitted_numbers(instruction, sensor if sensor is not None else SENSOR, context)
    return unsupported_numbers(text, permitted)


# --- number extraction ---


def test_grounded_text_passes_exact_and_rounded():
    assert bad("EC is 3.8 mS/cm, pH 6.84, humidity 86.5% and air 31 C.") == []
    assert bad("pH was 6.8.") == []
    assert bad("pH is about 7 and humidity near 87.") == []


def test_wrong_number_is_reported():
    assert bad("EC is 3.4 mS/cm.") == [3.4]
    assert bad("pH 7.4 and temperature 31") == [7.4]


def test_computed_number_fails():
    assert bad("Air is 31 C, which is 87.8 F.") == [87.8]


def test_superscript_digits_are_fabricated_numbers():
    assert normalize("EC ³·⁸") == "EC 3 8"
    assert bad("PPFD of 10¹⁵ photons") == [1015.0]


def test_arabic_indic_digits_are_read():
    assert numbers_in("EC ٣.٨") == [3.8]
    assert bad("EC ٣.٨") == []
    assert bad("EC ٣.٤") == [3.4]


def test_fullwidth_digits_are_read():
    assert numbers_in("３８") == [38.0]


def test_other_non_ascii_becomes_space_not_deleted():
    # Deleting the middle dot would fuse 3 and 8 into 38.
    assert numbers_in("3·8") == [3.0, 8.0]


def test_chemical_and_field_names_are_not_numbers():
    assert numbers_in("CO2 and ET0 and H2O") == []
    assert numbers_in("co2_ppm and ec_ms_cm") == []
    assert numbers_in("light in umol m-2 s-1 and kg day-1") == []


def test_decimal_after_letter_hyphen_is_a_positive_number():
    assert numbers_in("pH-7.4 is high") == [7.4]
    assert numbers_in("EC-3.4") == [3.4]
    assert bad("pH-7.4 is high", sensor={"ph": 6.8}) == [7.4]
    assert numbers_in("mm day-1") == []


def test_list_markers_are_ignored():
    assert numbers_in("1. Check pH\n2) Check EC\n  3. Wait") == []
    assert numbers_in("1. Check pH 6.84") == [6.84]
    assert numbers_in("6.8 is fine") == [6.8]


def test_range_dash_is_not_minus():
    assert numbers_in("5.5-6.5") == [5.5, 6.5]
    assert numbers_in("6-7") == [6.0, 7.0]
    assert numbers_in("5.5–6.5") == [5.5, 6.5]
    assert bad("target 5.5-6.5", instruction="Target range 5.5 to 6.5.") == []


def test_minus_sign_matters():
    assert numbers_in("-3") == [-3.0]
    assert numbers_in("temp (-3 C) and x=-2 and y:-1") == [-3.0, -2.0, -1.0]
    assert numbers_in("−3") == [-3.0]
    assert bad("dropped to -3 C", sensor={"air_temperature_c": 3}) == [-3.0]


def test_thousands_separator_and_trailing_dot():
    assert numbers_in("1,200 ppm") == [1200.0]
    assert numbers_in("1,2000") == [1.0, 2000.0]
    assert numbers_in("pH was 6.8.") == [6.8]
    assert numbers_in(".5 units") == [0.5]
    assert bad("CO2 near 1,200 ppm", sensor={"co2_ppm": 1200}) == []


def test_decimal_comma_fails_closed():
    assert bad("pH 6,8") == [6.0, 8.0]


def test_decimal_glued_to_letter_is_still_a_number():
    assert bad("EC3.4 is high") == [3.4]


# --- permitted numbers ---


def test_guarded_context_and_instruction_numbers_are_permitted():
    context = {
        "blocked_actions": ["dose_nutrients"],
        "safe_next_checks": ["Re-measure drain EC within 45 minutes"],
        "thresholds": {"ph_max": 6.8, "limits": [3.2, 12]},
    }
    assert bad("Re-check in 45 minutes; limits 3.2 and 12, ph max 6.8", context=context) == []
    assert bad("Check by 50 minutes", context=context) == [50.0]
    assert bad("Compare with 5.9", instruction="Compare with 5.9") == []


def test_bool_in_sensor_permits_nothing_extra():
    permitted = permitted_numbers(INSTRUCTION, {"ph": True, "ec_ms_cm": 2}, None)
    assert permitted == {0.0, 1.0, 2.0}
    permitted = permitted_numbers(INSTRUCTION, {"ph": True}, {"flag": True})
    assert permitted == {0.0, 1.0}
    assert unsupported_numbers("count 1 and 0", permitted) == []


def test_fields_not_shown_to_model_are_not_permitted():
    assert bad("flow 12.5", sensor={"flow_rate": 12.5}) == [12.5]


# --- explain() wiring ---


def _patch(monkeypatch, name, text):
    calls = []

    async def fake(instruction, sensor, guarded_context=None):
        calls.append((instruction, sensor, guarded_context))
        return {
            "model_id": "m",
            "backend": "ollama" if name == "_ollama_explanation" else "huggingface",
            "huggingface_repo": "r",
            "explanation": text,
            "likely_risks": [],
            "missing_data": [],
            "safe_checks": [],
            "human_review_required": True,
            "safety_note": "Advisory only.",
        }

    monkeypatch.setattr(advisor, name, fake)
    return calls


@pytest.mark.parametrize(
    "backend,name",
    [("ollama", "_ollama_explanation"), ("huggingface", "_huggingface_explanation")],
)
def test_explain_keeps_grounded_model_text(monkeypatch, backend, name):
    _patch(monkeypatch, name, "EC is 3.8 and pH is 6.8; air 31 C.")
    result = asyncio.run(advisor.explain(INSTRUCTION, SENSOR, backend=backend))
    assert result["backend"] == backend
    assert result["explanation"] == "EC is 3.8 and pH is 6.8; air 31 C."
    assert "fallback_reason" not in result


@pytest.mark.parametrize(
    "backend,name,label",
    [
        ("ollama", "_ollama_explanation", "ollama"),
        ("huggingface", "_huggingface_explanation", "Hugging Face"),
    ],
)
def test_explain_falls_back_on_ungrounded_numbers(monkeypatch, backend, name, label):
    _patch(monkeypatch, name, "EC is 7.4, then 31.5, 7.4 and 31.5 again, pH 6.8.")
    result = asyncio.run(advisor.explain(INSTRUCTION, SENSOR, backend=backend))
    expected = advisor._stub_explanation(INSTRUCTION, SENSOR)
    assert result["backend"] == "stub"
    assert result["explanation"] == expected["explanation"]
    assert result["fallback_reason"] == (
        f"{label} explanation quoted numbers not in the readings or guarded context: "
        "7.4, 31.5; deterministic explanation used instead"
    )


def test_explain_fallback_formats_whole_numbers_compactly(monkeypatch):
    _patch(monkeypatch, "_ollama_explanation", "Light is 450 and EC 3.4.")
    result = asyncio.run(advisor.explain(INSTRUCTION, SENSOR, backend="ollama"))
    assert "450, 3.4;" in result["fallback_reason"]


def test_explain_passes_guarded_context_to_the_check(monkeypatch):
    _patch(monkeypatch, "_ollama_explanation", "Re-measure in 45 minutes.")
    context = {"safe_next_checks": ["Re-measure in 45 minutes"]}
    result = asyncio.run(
        advisor.explain(INSTRUCTION, SENSOR, backend="ollama", guarded_context=context)
    )
    assert result["backend"] == "ollama"


def test_explain_exception_fallbacks_unchanged(monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(advisor, "_ollama_explanation", boom)
    result = asyncio.run(advisor.explain(INSTRUCTION, SENSOR, backend="ollama"))
    assert result["backend"] == "stub"
    assert result["fallback_reason"] == "ollama unavailable (RuntimeError)"  # class name only; "down" goes to the log


def test_stub_backend_is_unchanged_and_unchecked(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("number check must not run on the stub path")

    monkeypatch.setattr(advisor, "permitted_numbers", forbidden)
    result = asyncio.run(advisor.explain(INSTRUCTION, SENSOR, backend="stub"))
    assert result == advisor._stub_explanation(INSTRUCTION, SENSOR)
    assert result["backend"] == "stub"
    assert "fallback_reason" not in result


# --- number_spans, and numbers_in / permitted_numbers unchanged ---

# Outputs recorded from the pre-spans implementation (git HEAD before this work).
NUMBERS_IN_GOLDEN = [
    ("EC is 3.8 mS/cm, pH 6.84, humidity 86.5% and air 31 C.", [3.8, 6.84, 86.5, 31.0]),
    ("pH was 6.8.", [6.8]),
    ("pH is about 7 and humidity near 87.", [7.0, 87.0]),
    ("Air is 31 C, which is 87.8 F.", [31.0, 87.8]),
    ("PPFD of 10\u00b9\u2075 photons", [1015.0]),
    ("EC \u0663.\u0668", [3.8]),
    ("\uff13\uff18", [38.0]),
    ("3\u00b78", [3.0, 8.0]),
    ("CO2 and ET0 and H2O", []),
    ("co2_ppm and ec_ms_cm", []),
    ("light in umol m-2 s-1 and kg day-1", []),
    ("pH-7.4 is high", [7.4]),
    ("EC-3.4", [3.4]),
    ("mm day-1", []),
    ("1. Check pH\n2) Check EC\n  3. Wait", []),
    ("1. Check pH 6.84", [6.84]),
    ("6.8 is fine", [6.8]),
    ("5.5-6.5", [5.5, 6.5]),
    ("6-7", [6.0, 7.0]),
    ("5.5\u20136.5", [5.5, 6.5]),
    ("-3", [-3.0]),
    ("temp (-3 C) and x=-2 and y:-1", [-3.0, -2.0, -1.0]),
    ("\u22123", [-3.0]),
    ("dropped to -3 C", [-3.0]),
    ("1,200 ppm", [1200.0]),
    ("1,2000", [1.0, 2000.0]),
    (".5 units", [0.5]),
    ("pH 6,8", [6.0, 8.0]),
    ("EC3.4 is high", [3.4]),
    ("humidity_pct=71 soil_moisture_pct=50.0", [71.0, 50.0]),
    ("temperature 23.5 \u00b0C, 1e5, 3.8.5, 12.", [23.5, 1.0, 3.8, 5.0, 12.0]),
    ("x 7. y", [7.0]),
    ("", []),
    ("\u22122.5 and --3 and a-3", [-2.5, 3.0]),
]


@pytest.mark.parametrize("text,expected", NUMBERS_IN_GOLDEN)
def test_numbers_in_unchanged_on_corpus(text, expected):
    assert numbers_in(text) == expected
    assert [item.value for item in number_spans(text)] == expected


def test_permitted_numbers_unchanged_on_corpus():
    context = {
        "blocked_actions": ["dose_nutrients"],
        "safe_next_checks": ["Re-measure drain EC within 45 minutes"],
        "thresholds": {"ph_max": 6.8, "limits": [3.2, 12]},
    }
    assert permitted_numbers(INSTRUCTION, SENSOR, None) == {0.0, 1.0, 3.8, 6.84, 31.0, 86.5}
    assert permitted_numbers(INSTRUCTION, SENSOR, context) == {
        0.0, 1.0, 3.2, 3.8, 6.8, 6.84, 12.0, 31.0, 45.0, 86.5,
    }
    weird = {"flag": True, "n": float("nan"), "inf": float("inf"), "k": {"7": 8}}
    assert permitted_numbers("Target range 5.5 to 6.5.", {"ph": True, "ec_ms_cm": 2}, weird) == {
        0.0, 1.0, 2.0, 5.5, 6.5, 7.0, 8.0,
    }
    nested = {"a": [1, 2, (3, 4)], "b": {"c": "temp 4.5, 7"}, "d": None}
    sensor = {"co2_ppm": 1200, "soil_moisture_pct": 50.0, "light_umol": 400}
    assert permitted_numbers("Compare with 5.9", sensor, nested) == {
        0.0, 1.0, 2.0, 3.0, 4.0, 4.5, 5.9, 7.0, 50.0, 400.0, 1200.0,
    }
    assert permitted_numbers("x", {}, {}) == {0.0, 1.0}


def test_number_spans_give_value_and_span():
    text = "EC 3.8 and pH 6.84 at 31 C"
    spans = number_spans(text)
    assert [s.value for s in spans] == [3.8, 6.84, 31.0]
    assert [text[s.start : s.end] for s in spans] == ["3.8", "6.84", "31"]
    assert spans[0] == NumberSpan(3.8, 3, 6)
    assert spans[0].span == (3, 6)


def test_number_span_of_a_negative_number_includes_the_sign():
    text = "dropped to -3 C and \u22122.5"
    spans = number_spans(text)
    assert [s.value for s in spans] == [-3.0, -2.5]
    assert text[spans[0].start : spans[0].end] == "-3"


def test_number_spans_are_in_original_text_coordinates():
    text = "EC \u0663.\u0668 and \uff13\uff18"
    spans = number_spans(text)
    assert [s.value for s in spans] == [3.8, 38.0]
    assert text[spans[0].start : spans[0].end] == "\u0663.\u0668"
    assert text[spans[1].start : spans[1].end] == "\uff13\uff18"


def test_number_spans_skip_glued_numbers_and_list_markers():
    assert number_spans("CO2 and pH6") == []
    spans = number_spans("1. Check pH 6.84\n2) Check EC 3.8")
    assert [s.value for s in spans] == [6.84, 3.8]


# --- field binding ---


def bound(text):
    return [fields for _, fields in bound_fields(text)]


TEMPS = {"air_temperature_c", "substrate_temperature_c", "water_temperature_c"}
MOISTURE = {"substrate_moisture_pct", "soil_moisture_pct", "root_zone_moisture_pct"}


def test_binding_table_names_every_field():
    named = set()
    for _kind, _text, fields in BINDING_TABLE:
        named.update(fields)
    # pH is a fixed rule (right before the number), not a table row
    assert named == TEMPS | MOISTURE | {"humidity_pct", "ec_ms_cm", VPD_FIELD}


@pytest.mark.parametrize("text", ["31 C", "31 \u00b0C", "31\u00b0C", "31 \u2103", "31 celsius"])
def test_celsius_unit_binds_the_three_temperatures(text):
    assert bound(text) == [TEMPS]


def test_percent_unit_binds_humidity_and_moisture():
    assert bound("71%") == [{"humidity_pct"} | MOISTURE]
    assert bound("71 %") == [{"humidity_pct"} | MOISTURE]


def test_ms_cm_unit_binds_ec_and_kpa_binds_vpd():
    assert bound("3.8 mS/cm") == [{"ec_ms_cm"}]
    assert bound("1.2 kPa") == [{VPD_FIELD}]


def test_unit_must_be_right_after_the_number():
    assert bound("31 and then C") == [set()]
    assert bound("6 cm") == [set()]  # not 6 C
    assert bound("3 Cs") == [set()]


@pytest.mark.parametrize("text", ["pH 6.8", "pH of 6.8", "pH=6.8", "pH: 6.8", "ph = 6.8"])
def test_ph_right_before_binds_ph(text):
    assert bound(text) == [{"ph"}]


def test_ph_is_not_a_field_word_and_pH6_is_not_read():
    assert bound("pH was close to 6.8") == [set()]
    assert bound("pH6 and 6.8") == [set()]  # pH6 is glued, never a number
    assert [s.value for s in number_spans("pH6")] == []
    assert bound("graph 6.8") == [set()]


def test_field_words_bind_within_four_words():
    assert bound("humidity 71") == [{"humidity_pct"}]
    assert bound("EC 3.8") == [{"ec_ms_cm"}]
    assert bound("air temperature 31") == [{"air_temperature_c"}]
    assert bound("substrate temperature 20") == [{"substrate_temperature_c"}]
    assert bound("water temperature 18") == [{"water_temperature_c"}]
    assert bound("moisture 40") == [MOISTURE]
    assert bound("soil moisture 40") == [{"soil_moisture_pct"}]
    assert bound("VPD 1.2") == [{VPD_FIELD}]
    assert bound("temperature 31") == [TEMPS]


def test_four_word_window_edge():
    assert bound("humidity is now at 71") == [{"humidity_pct"}]  # 4 words before
    assert bound("humidity is now at about 71") == [set()]  # 5 words before
    # a phrase counts when its last word is inside the window
    assert bound("air temperature is now at 31") == [{"air_temperature_c"}]
    assert bound("air temperature is now at about 31") == [set()]


def test_field_word_does_not_cross_a_sentence_break():
    assert bound("Humidity looks fine. Air is 31") == [set()]
    assert bound("Humidity looks fine; air is 31") == [set()]


def test_raw_field_name_with_equals():
    assert bound("humidity_pct=71") == [{"humidity_pct"}]
    assert bound("soil_moisture_pct=50.0") == [{"soil_moisture_pct"}]
    assert bound("ec_ms_cm = 3.8") == [{"ec_ms_cm"}]
    assert bound("ph=6.8") == [{"ph"}]
    assert bound("substrate_temperature_c=20.5") == [{"substrate_temperature_c"}]
    assert bound("co2_ppm=1200") == [set()]  # not a bound field


def test_explicit_forms_win_over_units_and_words():
    assert bound("humidity_pct=71%") == [{"humidity_pct"}]
    assert bound("EC pH 6.8") == [{"ph"}]


def test_bound_fields_per_number_and_list_markers():
    text = "1. Check pH 6.84\n2) EC 3.8 mS/cm, humidity 86.5%"
    assert bound(text) == [{"ph"}, {"ec_ms_cm"}, {"humidity_pct"} | MOISTURE]
    assert bound("1. Wait") == []


def test_ec_and_ph_in_one_sentence():
    # 6.8 has no pH right before it and EC is too far; the stub never writes this
    assert bound("EC and pH are 3.8 and 6.8") == [{"ec_ms_cm"}, set()]


# --- grounding_violations ---


def reading(zone, device, field, value, t="2026-11-14T10:00:00Z"):
    return ReadingSource(zone, device, field, value, t)


ZONE_A = [
    reading("zone-a", "dev-1", "humidity_pct", 71.0),
    reading("zone-a", "dev-1", "air_temperature_c", 24.2),
    reading("zone-a", "dev-1", "ph", 6.8),
    reading("zone-a", "dev-1", "ec_ms_cm", 2.1),
    reading("zone-a", "dev-2", "ec_ms_cm", 2.7),
]
NEIGHBOUR = [reading("zone-b", "dev-9", "ec_ms_cm", 3.3), reading("zone-b", "dev-9", "ph", 5.9)]
CONTEXT = {"farm_overview": {"weather": {"rh_mean_pct": 62, "t_mean_c": 23.5}}}


def violations(text, extra=(), device_id=None, exempt=(), zone="zone-a", instruction=INSTRUCTION):
    sources = number_sources(instruction, list(ZONE_A) + list(NEIGHBOUR), CONTEXT)
    sources = list(sources) + list(extra)
    return grounding_violations(text, sources, zone, device_id=device_id, exempt=exempt)


def kinds(found):
    return [(v.kind, v.value) for v in found]


def test_correct_scoped_text_has_no_violation():
    text = "Humidity is 71%, air temperature 24.2 C, pH 6.8 and EC 2.1 mS/cm."
    assert violations(text) == []


def test_rounded_numbers_are_grounded_as_today():
    assert violations("Humidity is 71.0 and air temperature 24 C.") == []
    assert kinds(violations("air temperature 24.20 C")) == []
    assert violations("pH 6.8, humidity about 71") == []
    assert kinds(violations("air temperature is 24.3 C")) == [("unsupported", 24.3)]


def test_rounding_tolerance_is_the_flat_checks():
    # same _grounded as the flat check: 24 for 23.6 is grounded (0 decimals); 24.4 is not.
    # (Values are floats, so "24.0" is the same number as "24".)
    sources = number_sources(INSTRUCTION, [reading("z", "d", "air_temperature_c", 23.6)], None)
    assert grounding_violations("air temperature 24", sources, "z") == []
    assert grounding_violations("air temperature 23.6", sources, "z") == []
    assert kinds(grounding_violations("air temperature 24.4", sources, "z")) == [
        ("unsupported", 24.4)
    ]
    assert unsupported_numbers("24.0", permitted_numbers(INSTRUCTION, {"air_temperature_c": 23.6})) == []


def test_weather_humidity_quoted_as_zone_humidity_is_wrong_scope():
    found = violations("Humidity is 62% in the zone.")
    assert kinds(found) == [("wrong_scope", 62.0)]
    assert found[0].fields >= {"humidity_pct"}
    assert found[0].span == (12, 14)


def test_weather_number_stays_fine_when_unbound():
    assert violations("The outdoor reading is 62 today.") == []


def test_neighbour_zone_ec_is_wrong_scope():
    assert kinds(violations("EC is 3.3 mS/cm.")) == [("wrong_scope", 3.3)]
    # the neighbour's own zone is fine for the neighbour
    assert violations("EC is 3.3 mS/cm.", zone="zone-b") == []


def test_ec_quoted_with_the_ph_value_is_wrong_field():
    found = violations("EC 6.8 is too high.")
    assert kinds(found) == [("wrong_field", 6.8)]
    assert found[0].fields == {"ec_ms_cm"}


def test_ph_quoted_with_the_ec_value_is_wrong_field():
    assert kinds(violations("pH 2.1")) == [("wrong_field", 2.1)]


def test_other_device_of_the_same_zone_is_wrong_device_when_device_given():
    text = "EC is 2.7 mS/cm."
    assert violations(text) == []  # no device named: any device of the zone grounds it
    assert kinds(violations(text, device_id="dev-1")) == [("wrong_device", 2.7)]
    assert violations(text, device_id="dev-2") == []
    assert violations("EC is 2.1 mS/cm.", device_id="dev-1") == []


def test_zone_level_reading_grounds_any_device():
    zone_level = ReadingSource("zone-a", None, "humidity_pct", 55.0, None)
    assert violations("Humidity 55%", extra=[zone_level], device_id="dev-1") == []


def test_wrong_device_beats_wrong_field_beats_wrong_scope():
    extra = [reading("zone-a", "dev-2", "ec_ms_cm", 9.0), reading("zone-a", "dev-1", "ph", 9.0)]
    extra.append(reading("zone-b", "dev-9", "ec_ms_cm", 9.0))
    assert kinds(violations("EC 9", extra=extra, device_id="dev-1")) == [("wrong_device", 9.0)]
    assert kinds(violations("EC 9", extra=extra[1:])) == [("wrong_field", 9.0)]
    assert kinds(violations("EC 9", extra=extra[2:])) == [("wrong_scope", 9.0)]


def test_instruction_and_rule_text_numbers_are_wrong_scope_in_a_field_claim():
    sources = number_sources(
        "Mention the 30 limit.",
        ZONE_A,
        None,
        rule_texts=["Air above 16 C at night is fine."],
    )
    found = grounding_violations("Air temperature 30 C and humidity 16%", sources, "zone-a")
    assert kinds(found) == [("wrong_scope", 30.0), ("wrong_scope", 16.0)]
    # unbound, they still ground (today's rule)
    assert grounding_violations("Stay under 30, above 16.", sources, "zone-a") == []


def test_check_text_and_reference_sources():
    extra = [
        OtherSource("check_text", "check", 45.0),
        OtherSource("reference", "median", 68.0, zone_id="zone-a", device_id="dev-1", field="humidity_pct"),
        OtherSource("reference", "median", 4.4, zone_id="zone-b", device_id="dev-9", field="humidity_pct"),
    ]
    assert violations("Humidity median 68%", extra=extra) == []
    assert kinds(violations("Humidity 4.4%", extra=extra)) == [("wrong_scope", 4.4)]
    assert kinds(violations("Humidity 45%", extra=extra)) == [("wrong_scope", 45.0)]
    assert kinds(violations("Humidity 68%", extra=extra, device_id="dev-2")) == [
        ("wrong_device", 68.0)
    ]
    assert kinds(violations("EC 68", extra=extra)) == [("wrong_field", 68.0)]


def test_derived_source_carries_the_zones_of_its_inputs():
    derived = OtherSource("derived", "vpd", 1.15, zones=("zone-a",), field=VPD_FIELD)
    other = OtherSource("derived", "vpd", 0.77, zones=("zone-b",), field=VPD_FIELD)
    assert violations("VPD is 1.15 kPa", extra=[derived, other]) == []
    assert kinds(violations("VPD is 0.77 kPa", extra=[derived, other])) == [("wrong_scope", 0.77)]
    assert kinds(violations("humidity 1.15", extra=[derived])) == [("wrong_field", 1.15)]
    assert violations("a value of 1.15", extra=[derived]) == []  # unbound: any source


def test_placeholder_grounds_nothing_unless_exempt():
    placeholder = OtherSource(
        "placeholder", "zone-b.soil_moisture_pct", 50.0, zone_id="zone-b", field="soil_moisture_pct"
    )
    shown = [ReadingSource("zone-b", "dev-9", "soil_moisture_pct", 50.0, None)]
    bare = [placeholder]  # the reading itself is not given as a source: it is a placeholder
    assert kinds(grounding_violations("moisture is 50 %", bare, "zone-b")) == [("unsupported", 50.0)]
    assert kinds(grounding_violations("soil_moisture_pct=50.0", bare, "zone-b")) == [
        ("unsupported", 50.0)
    ]
    assert kinds(grounding_violations("a value of 50", bare, "zone-b")) == [("unsupported", 50.0)]
    exempt = [("soil_moisture_pct", 50.0)]
    assert grounding_violations("soil_moisture_pct=50.0", bare, "zone-b", exempt=exempt) == []
    # any other use of 50 bound to moisture stays a violation
    assert kinds(grounding_violations("moisture is 50 %", bare, "zone-b", exempt=exempt)) == [
        ("unsupported", 50.0)
    ]
    assert kinds(
        grounding_violations("soil_moisture_pct=50.0", bare, "zone-b", exempt=[("humidity_pct", 50.0)])
    ) == [("unsupported", 50.0)]
    assert shown  # (a real reading of 50 would ground it; the placeholder must not)


def test_exempt_only_the_raw_field_form():
    placeholder = OtherSource(
        "placeholder", "zone-b.soil_moisture_pct", 50.0, zone_id="zone-b", field="soil_moisture_pct"
    )
    exempt = [("soil_moisture_pct", 50.0)]
    assert grounding_violations("soil_moisture_pct=50.0", [placeholder], "zone-b", exempt=exempt) == []
    # bound by a word or a unit (even to exactly that field): not the placeholder printing
    for text in (
        "soil moisture 50",
        "soil_moisture_pct 50",
        "soil moisture is 50 %",
        "moisture 50 %",
    ):
        found = grounding_violations(text, [placeholder], "zone-b", exempt=exempt)
        assert kinds(found) == [("unsupported", 50.0)], text


def test_unbound_numbers_keep_todays_rule():
    assert violations("Values were 71, 6.8 and 3.3.") == []  # any source, any zone
    assert kinds(violations("Value 999 is odd.")) == [("unsupported", 999.0)]
    assert violations("Count 0 or 1.") == []
    assert violations("Wait 45 minutes.", instruction="Wait 45 minutes.") == []
    assert kinds(violations("Wait 50 minutes.", instruction="Wait 45 minutes.")) == [
        ("unsupported", 50.0)
    ]


def test_zero_and_one_are_not_sources_for_bound_numbers():
    assert kinds(violations("humidity 1%")) == [("unsupported", 1.0)]


def test_one_record_per_bad_number_in_order_with_span_and_fields():
    text = "EC 6.8 and humidity 62% and pH 6.8"
    found = violations(text)
    assert [type(v) for v in found] == [GroundingViolation, GroundingViolation]
    assert kinds(found) == [("wrong_field", 6.8), ("wrong_scope", 62.0)]
    assert [text[v.start : v.end] for v in found] == ["6.8", "62"]
    assert found[0].fields == {"ec_ms_cm"}


def test_unknown_role_is_rejected():
    with pytest.raises(ValueError):
        grounding_violations("EC 2.1", [OtherSource("bogus", "x", 2.1)], "zone-a")


def test_stub_style_text_is_grounded_by_raw_field_readings():
    text = "humidity_pct=71 air_temperature_c=24.2 ph=6.8 ec_ms_cm=2.1"
    assert violations(text) == []
    assert kinds(violations("ec_ms_cm=6.8")) == [("wrong_field", 6.8)]


def test_number_sources_roles_and_paths():
    sources = number_sources(
        "Use 30.",
        [ReadingSource("z", "d", "ph", 6.8, None), ReadingSource("z", "d", "ec_ms_cm", True, None)],
        {"farm": {"area": 120, "kc": [0.85]}, "note": "NPK 10-5"},
        rule_texts=["night 16 C"],
    )
    by_role = {}
    for s in sources:
        if isinstance(s, OtherSource):
            by_role.setdefault(s.role, []).append((s.path, s.value))
    assert by_role["instruction"] == [("instruction", 30.0)]
    assert by_role["rule_text"] == [("rule_texts[0]", 16.0)]
    assert ("guarded_context.farm.area", 120.0) in by_role["farm_context"]
    assert ("guarded_context.farm.kc[0]", 0.85) in by_role["farm_context"]
    assert sum(isinstance(s, ReadingSource) for s in sources) == 1  # the bool reading is dropped
    assert text_sources("check_text", "in 45 minutes", "chk") == [OtherSource("check_text", "chk", 45.0)]
