"""Post-generation number check for model-written advisor explanations.

Guarantees: every number in the explanation text equals (or is a 0-2 decimal
rounding of) a number the model was shown: the sensor readings in the summary,
numbers in the guarded context, or numbers in the instruction. Numbers the
model computed (unit conversions, sums) are not grounded and fail.

Does not guarantee: that a grounded number is attached to the right quantity
(it cannot tell "EC 6.8" from "pH 6.8"), that numbers written as words are
correct, or that the text is otherwise accurate. Decimal commas ("6,8") and
numbers glued to a letter ("pH6", "CO2") are not read as numbers.
"""

import math
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Dict, Iterable, List, Optional, Set

from app.config import SENSOR_FIELDS

_DASHES = "‐‑‒–—―−﹣－"
_ALWAYS_ALLOWED = frozenset({0.0, 1.0})
_MINUS_CONTEXT = set("([=:,")
_TOLERANCE = 1e-9

# Integer with optional "1,200" style thousands groups and optional fraction,
# or a bare ".5". A trailing "." is never part of the number.
_NUMBER = re.compile(
    r"(?<![\d.])\.\d+|\d+(?:,\d{3}(?!\d))*(?:\.\d+)?"
)


def normalize(text: str) -> str:
    """Map Unicode digits and dashes to ASCII; replace other non-ASCII with a space."""
    out: List[str] = []
    for ch in text:
        if ch.isascii():
            out.append(ch)
        elif ch in _DASHES:
            out.append("-")
        else:
            digit = unicodedata.digit(ch, None)
            out.append(str(digit) if digit is not None else " ")
    return "".join(out)


def numbers_in(text: str) -> List[float]:
    """Numbers quoted in text, in order, after normalize()."""
    text = normalize(text)
    found: List[float] = []
    for match in _NUMBER.finditer(text):
        start, end = match.start(), match.end()
        raw = match.group(0)
        has_fraction = "." in raw

        before = text[start - 1] if start > 0 else ""
        if (before.isalpha() or before == "_") and not has_fraction:
            continue  # CO2, ET0, H2O, co2_ppm

        line_start = text.rfind("\n", 0, start) + 1
        if not text[line_start:start].strip() and text[end : end + 2] in (". ", ") "):
            continue  # list marker "1. " / "2) "

        negative = False
        if before == "-":
            prior = text[start - 2] if start > 1 else ""
            if prior.isalpha() and not has_fraction:
                continue  # unit exponent (never fractional): m-2, day-1
            negative = start == 1 or prior.isspace() or prior in _MINUS_CONTEXT

        value = float(raw.replace(",", ""))
        found.append(-value if negative else value)
    return found


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _walk(value: Any, out: Set[float]) -> None:
    if _is_number(value):
        out.add(float(value))
    elif isinstance(value, str):
        out.update(numbers_in(value))
    elif isinstance(value, dict):
        for key, item in value.items():
            _walk(str(key), out)
            _walk(item, out)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _walk(item, out)
    elif value is not None and not isinstance(value, (bool, int, float)):
        out.update(numbers_in(str(value)))  # json.dumps(default=str) shows these


def permitted_numbers(
    instruction: str,
    sensor: Dict[str, Any],
    guarded_context: Optional[Dict[str, Any]] = None,
) -> Set[float]:
    """The numbers build_user_message() shows the model, plus 0 and 1."""
    permitted: Set[float] = set(_ALWAYS_ALLOWED)
    for field in SENSOR_FIELDS:
        value = sensor.get(field)
        if _is_number(value):
            permitted.add(float(value))
    if guarded_context:
        _walk(guarded_context, permitted)
    permitted.update(numbers_in(instruction))
    return permitted


def _grounded(value: float, permitted: Iterable[float]) -> bool:
    for p in permitted:
        if abs(value - p) < _TOLERANCE:
            return True
        if not math.isfinite(p):
            continue
        exact = Decimal(repr(p))  # half-up, so 86.5 -> 87 (round() gives 86)
        for places in (0, 1, 2):
            rounded = exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
            if abs(value - float(rounded)) < _TOLERANCE:
                return True
    return False


def unsupported_numbers(text: str, permitted: Set[float]) -> List[float]:
    """Numbers in text that no permitted number grounds, in order."""
    return [v for v in numbers_in(text) if not _grounded(v, permitted)]


def format_number(value: float) -> str:
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)
