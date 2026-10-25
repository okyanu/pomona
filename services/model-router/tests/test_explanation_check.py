import asyncio
import sys
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_DIR))

from app import advisor
from app.explanation_check import (
    normalize,
    numbers_in,
    permitted_numbers,
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
    assert result["fallback_reason"] == "ollama unavailable: down"


def test_stub_backend_is_unchanged_and_unchecked(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("number check must not run on the stub path")

    monkeypatch.setattr(advisor, "permitted_numbers", forbidden)
    result = asyncio.run(advisor.explain(INSTRUCTION, SENSOR, backend="stub"))
    assert result == advisor._stub_explanation(INSTRUCTION, SENSOR)
    assert result["backend"] == "stub"
    assert "fallback_reason" not in result
