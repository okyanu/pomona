"""Post-generation number check for model-written advisor explanations.

Guarantees: every number in the explanation text equals (or is a 0-2 decimal
rounding of) a number the model was shown: the sensor readings in the summary,
numbers in the guarded context, or numbers in the instruction. Numbers the
model computed (unit conversions, sums) are not grounded and fail.

Does not guarantee: that numbers written as words are correct, or that the
text is otherwise accurate. Decimal commas ("6,8") and numbers glued to a
letter ("pH6", "CO2") are not read as numbers. `permitted_numbers` /
`unsupported_numbers` (the flat check the live advisor uses) cannot tell
"EC 6.8" from "pH 6.8".

The scoped check (`number_sources`, `bound_fields`, `grounding_violations`)
can: it binds a number to the field(s) its unit or nearby words name, and
accepts it only when a source of the right zone, field and device shows that
number. It is used by the abstention eval; the live advisor does not call it.
"""

import math
import re
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import (
    Any,
    Dict,
    FrozenSet,
    Iterable,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)

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


class NumberSpan(NamedTuple):
    """One number quoted in a text: value, and the [start, end) span it came from.

    The span is in `normalize(text)` coordinates, which equal the original
    text's (normalize maps one character to one character). A negative number's
    span includes its minus sign.
    """

    value: float
    start: int
    end: int

    @property
    def span(self) -> Tuple[int, int]:
        return (self.start, self.end)


def number_spans(text: str) -> List[NumberSpan]:
    """Numbers quoted in text, in order, with their spans, after normalize()."""
    text = normalize(text)
    found: List[NumberSpan] = []
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
        if negative:
            found.append(NumberSpan(-value, start - 1, end))
        else:
            found.append(NumberSpan(value, start, end))
    return found


def numbers_in(text: str) -> List[float]:
    """Numbers quoted in text, in order, after normalize()."""
    return [item.value for item in number_spans(text)]


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


ROLES = (
    "instruction",  # numbers in the instruction text
    "rule_text",  # numbers in rules.yaml messages (30, 16 C ...)
    "check_text",  # numbers in router check text
    "farm_context",  # weather, NPK target, zone area, crop Kc ...
    "reference",  # stream_baseline median / last value (zone, device, field)
    "derived",  # VPD, agronomy_calc (zones of the inputs)
    "placeholder",  # printed, but grounds nothing
)
_ZONELESS_ROLES = frozenset({"instruction", "rule_text", "check_text", "farm_context"})


class ReadingSource(NamedTuple):
    """A sensor reading the model was shown, with where it came from."""

    zone_id: Optional[str]
    device_id: Optional[str]
    field: str
    value: float
    sample_time: Optional[str] = None


class OtherSource(NamedTuple):
    """Any other number the model was shown. `role` is one of ROLES.

    `reference` carries zone_id / device_id / field (None = any device / any
    field). `derived` carries `zones` (the zones of its inputs) and, optionally,
    the pseudo-field it states. `placeholder` carries the same as informative
    data only: it never grounds a number.
    """

    role: str
    path: str
    value: float
    zone_id: Optional[str] = None
    device_id: Optional[str] = None
    field: Optional[str] = None
    zones: Tuple[str, ...] = ()


Source = Union[ReadingSource, OtherSource]


def text_sources(role: str, text: str, path: str = "") -> List[OtherSource]:
    """One OtherSource per number in text (rule messages, check text ...)."""
    return [OtherSource(role, path, value) for value in numbers_in(text)]


def _walk_sources(value: Any, path: str, out: List[OtherSource]) -> None:
    if _is_number(value):
        out.append(OtherSource("farm_context", path, float(value)))
    elif isinstance(value, str):
        out.extend(text_sources("farm_context", value, path))
    elif isinstance(value, dict):
        for key, item in value.items():
            out.extend(text_sources("farm_context", str(key), "%s.%s" % (path, key)))
            _walk_sources(item, "%s.%s" % (path, key), out)
    elif isinstance(value, (list, tuple, set)):
        for index, item in enumerate(value):
            _walk_sources(item, "%s[%d]" % (path, index), out)
    elif value is not None and not isinstance(value, (bool, int, float)):
        out.extend(text_sources("farm_context", str(value), path))  # json.dumps(default=str)


def number_sources(
    instruction: str,
    readings: Iterable[ReadingSource],
    guarded_context: Optional[Dict[str, Any]] = None,
    rule_texts: Iterable[str] = (),
) -> List[Source]:
    """Every number the model was shown, as typed sources.

    `readings` are kept as given (non-numeric values dropped); the guarded
    context becomes `farm_context` sources (path "guarded_context.<key>..."),
    the instruction `instruction` sources, each rule text `rule_text` sources.
    `reference`, `derived`, `check_text` and `placeholder` sources are added by
    the caller (they need zone/device knowledge this module does not have);
    `text_sources` builds the text ones.
    """
    sources: List[Source] = [r for r in readings if _is_number(r.value)]
    sources.extend(text_sources("instruction", instruction, "instruction"))
    for index, text in enumerate(rule_texts):
        sources.extend(text_sources("rule_text", text, "rule_texts[%d]" % index))
    if guarded_context:
        _walk_sources(guarded_context, "guarded_context", sources)  # type: ignore[arg-type]
    return sources


def permitted_numbers(
    instruction: str,
    sensor: Dict[str, Any],
    guarded_context: Optional[Dict[str, Any]] = None,
) -> Set[float]:
    """The numbers build_user_message() shows the model, plus 0 and 1."""
    readings = [
        ReadingSource(None, None, field, float(sensor[field]))
        for field in SENSOR_FIELDS
        if _is_number(sensor.get(field))
    ]
    permitted: Set[float] = set(_ALWAYS_ALLOWED)
    permitted.update(s.value for s in number_sources(instruction, readings, guarded_context))
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


# --- field binding -------------------------------------------------------

VPD_FIELD = "vpd_kpa"  # pseudo-field: VPD is derived, not a packet field

_TEMPERATURE = frozenset(
    {"air_temperature_c", "substrate_temperature_c", "water_temperature_c"}
)
_MOISTURE = frozenset(
    {"substrate_moisture_pct", "soil_moisture_pct", "root_zone_moisture_pct"}
)
_PERCENT = _MOISTURE | {"humidity_pct"}
_ALL_FIELDS = (
    _TEMPERATURE
    | _PERCENT
    | {"ph", "ec_ms_cm", VPD_FIELD}
)

# The ONE table of units and words. (kind, text, fields)
#   unit: right after the number (one optional space). A text with an
#         uppercase letter ("C") matches case-sensitively, others do not care.
#   word: a field word within the 4 words before the number; may be a phrase.
# `pH` right before the number and the raw `field=` form are fixed rules
# (see bound_fields), not table rows.
BINDING_TABLE: Tuple[Tuple[str, str, FrozenSet[str]], ...] = (
    ("unit", "\u00b0c", _TEMPERATURE),
    ("unit", "\u00bac", _TEMPERATURE),
    ("unit", "\u2103", _TEMPERATURE),
    ("unit", "\u00b0 c", _TEMPERATURE),
    ("unit", "celsius", _TEMPERATURE),
    ("unit", "C", _TEMPERATURE),
    ("unit", "%", _PERCENT),
    ("unit", "percent", _PERCENT),
    ("unit", "ms/cm", frozenset({"ec_ms_cm"})),
    ("unit", "ds/m", frozenset({"ec_ms_cm"})),
    ("unit", "kpa", frozenset({VPD_FIELD})),
    ("word", "air temperature", frozenset({"air_temperature_c"})),
    ("word", "air temp", frozenset({"air_temperature_c"})),
    ("word", "substrate temperature", frozenset({"substrate_temperature_c"})),
    ("word", "substrate temp", frozenset({"substrate_temperature_c"})),
    ("word", "root zone temperature", frozenset({"substrate_temperature_c"})),
    ("word", "water temperature", frozenset({"water_temperature_c"})),
    ("word", "solution temperature", frozenset({"water_temperature_c"})),
    ("word", "temperature", _TEMPERATURE),
    ("word", "temp", _TEMPERATURE),
    ("word", "humidity", frozenset({"humidity_pct"})),
    ("word", "relative humidity", frozenset({"humidity_pct"})),
    ("word", "rh", frozenset({"humidity_pct"})),
    ("word", "soil moisture", frozenset({"soil_moisture_pct"})),
    ("word", "substrate moisture", frozenset({"substrate_moisture_pct"})),
    ("word", "root zone moisture", frozenset({"root_zone_moisture_pct"})),
    ("word", "moisture", _MOISTURE),
    ("word", "ec", frozenset({"ec_ms_cm"})),
    ("word", "electrical conductivity", frozenset({"ec_ms_cm"})),
    ("word", "conductivity", frozenset({"ec_ms_cm"})),
    ("word", "vpd", frozenset({VPD_FIELD})),
    ("word", "vapor pressure deficit", frozenset({VPD_FIELD})),
    ("word", "vapour pressure deficit", frozenset({VPD_FIELD})),
)

_UNITS = sorted(
    ((text, fields) for kind, text, fields in BINDING_TABLE if kind == "unit"),
    key=lambda row: -len(row[0]),
)
_WORDS: Dict[Tuple[str, ...], FrozenSet[str]] = {
    tuple(text.split()): fields for kind, text, fields in BINDING_TABLE if kind == "word"
}
for _name in _ALL_FIELDS - {"ph"}:  # the raw field name as a word ("pH" binds only right before)
    _WORDS.setdefault((_name,), frozenset({_name}))
_PHRASES = sorted(_WORDS, key=lambda phrase: -len(phrase))
_WINDOW = 4
_MAX_PHRASE = max(len(phrase) for phrase in _PHRASES)

_PH_BEFORE = re.compile(r"(?<![a-z0-9_])ph(?:\s+of)?\s*[=:\-]?\s*$", re.IGNORECASE)
_RAW_FIELD_BEFORE = re.compile(r"(?<![a-z0-9_])([a-z][a-z0-9_]*)\s*=\s*$", re.IGNORECASE)
_SENTENCE_BREAK = re.compile(r"[\n;?!]|\.\s")
_WORD_TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\d+(?:[.,]\d+)*")


def _unit_fields(text: str, end: int) -> FrozenSet[str]:
    after = text[end:]
    if after[:1] in (" ", "\t"):
        after = after[1:]
    for unit, fields in _UNITS:
        chunk = after[: len(unit)]
        same = chunk == unit if unit != unit.lower() else chunk.lower() == unit
        if not same:
            continue
        following = after[len(unit) : len(unit) + 1]
        if unit[-1:].isalpha() and (following.isalnum() or following == "_"):
            continue  # "6 cm" is not "6 C"
        return fields
    return frozenset()


def _word_fields(before: str) -> FrozenSet[str]:
    cut = 0
    for match in _SENTENCE_BREAK.finditer(before):
        cut = match.end()
    tokens = [t.lower() for t in _WORD_TOKEN.findall(before[cut:])]
    tokens = tokens[-(_WINDOW + _MAX_PHRASE - 1) :]
    window_start = len(tokens) - _WINDOW  # a phrase counts if it ENDS in the window
    fields: Set[str] = set()
    i = 0
    while i < len(tokens):
        for phrase in _PHRASES:
            end = i + len(phrase)
            if tuple(tokens[i:end]) == phrase and end - 1 >= window_start:
                fields.update(_WORDS[phrase])
                i = end - 1
                break
        i += 1
    return frozenset(fields)


def _bind(text: str) -> List[Tuple[NumberSpan, FrozenSet[str], bool]]:
    """(span, bound fields, bound by the raw `field=` form?) for every number."""
    normalized = normalize(text)
    out: List[Tuple[NumberSpan, FrozenSet[str], bool]] = []
    for item in number_spans(text):
        before = normalized[: item.start]
        if _PH_BEFORE.search(before):
            out.append((item, frozenset({"ph"}), False))
            continue
        raw = _RAW_FIELD_BEFORE.search(before)
        if raw and raw.group(1).lower() in _ALL_FIELDS | {"ph"}:
            out.append((item, frozenset({raw.group(1).lower()}), True))
            continue
        fields = _unit_fields(text, item.end) | _word_fields(before)
        out.append((item, fields, False))
    return out


def bound_fields(text: str) -> List[Tuple[NumberSpan, FrozenSet[str]]]:
    """Each number span with the set of fields it is bound to (empty = unbound).

    A number is bound by (union of):
    - a unit right after it (BINDING_TABLE "unit" rows);
    - a field word within the 4 words before it, not past a sentence break
      (BINDING_TABLE "word" rows, phrases count if they end inside the window);
    unless an explicit form is present, which is authoritative and binds
    exactly one field:
    - `pH` right before it: "pH 6.8", "pH of 6.8", "pH=6.8";
    - a raw field name and "=": "humidity_pct=71" (the stub's format).
    The result is a set on purpose ("humidity 62 %" is humidity or a moisture
    field), so a correct sentence is not flagged.
    """
    return [(item, fields) for item, fields, _raw in _bind(text)]


# --- scoped grounding ----------------------------------------------------

KINDS = ("unsupported", "wrong_scope", "wrong_field", "wrong_device")


class GroundingViolation(NamedTuple):
    """One number the sources do not ground at the right zone / field / device."""

    kind: str  # one of KINDS
    value: float
    start: int
    end: int
    fields: FrozenSet[str]  # the fields the number was bound to

    @property
    def span(self) -> Tuple[int, int]:
        return (self.start, self.end)


def _scope(
    source: Source, zone_id: Optional[str]
) -> Tuple[Optional[bool], Optional[str], Optional[str]]:
    """(in the zone?, field it states, device it came from); None = no such notion."""
    if isinstance(source, ReadingSource):
        return source.zone_id == zone_id, source.field, source.device_id
    if source.role not in ROLES:
        raise ValueError("unknown source role %r" % (source.role,))
    if source.role in _ZONELESS_ROLES:
        return None, None, None
    if source.role == "derived":
        return zone_id in source.zones, source.field, None
    return source.zone_id == zone_id, source.field, source.device_id  # reference


def _bound_kind(
    value: float,
    fields: FrozenSet[str],
    sources: Sequence[Source],
    zone_id: Optional[str],
    device_id: Optional[str],
) -> Optional[str]:
    """None if a source of this zone/field/device grounds it, else the kind."""
    kinds: Set[str] = set()
    for source in sources:
        if not _grounded(value, (source.value,)):
            continue
        in_zone, field, device = _scope(source, zone_id)
        if not in_zone:  # None (zoneless role) or False (another zone)
            kinds.add("wrong_scope")
        elif field is not None and field not in fields:
            kinds.add("wrong_field")
        elif device_id is not None and device is not None and device != device_id:
            kinds.add("wrong_device")
        else:
            return None
    for kind in ("wrong_device", "wrong_field", "wrong_scope"):
        if kind in kinds:
            return kind
    return "unsupported"


def grounding_violations(
    text: str,
    sources: Iterable[Source],
    zone_id: Optional[str],
    device_id: Optional[str] = None,
    exempt: Iterable[Tuple[str, float]] = (),
) -> List[GroundingViolation]:
    """One record per number in text that the sources do not ground, in order.

    - Unbound number (see bound_fields): today's rule, any source grounds it
      (0 and 1 always do); kind `unsupported` otherwise.
    - Bound number: needs a reading / reference / derived source of `zone_id`
      stating one of its bound fields (and `device_id`, when given and the
      source names a device). Otherwise the kind is, in this order:
      `wrong_device` (right zone and field, another device), `wrong_field`
      (this zone, another field), `wrong_scope` (another zone, or
      farm_context / instruction / rule_text / check_text), `unsupported`.
      0 and 1 are free only for unbound numbers.
    - `placeholder` sources ground nothing.
    - `exempt`: (field, value) pairs, e.g. [("soil_moisture_pct", 50.0)]. A
      violation is dropped only when the number was bound by the raw
      `field=value` form to that field and matches the value (same rounding as
      the check). "soil moisture 50", "soil_moisture_pct 50" and "moisture
      50 %" are bound by a word or unit, so they are not exempt. The caller builds the pairs from
      the case's placeholder fields.
    """
    live = [s for s in sources if not (isinstance(s, OtherSource) and s.role == "placeholder")]
    for source in live:
        _scope(source, zone_id)  # validates the role
    exempt = list(exempt)
    free = list(_ALWAYS_ALLOWED) + [s.value for s in live]
    violations: List[GroundingViolation] = []
    for item, fields, raw_form in _bind(text):
        if fields:
            kind = _bound_kind(item.value, fields, live, zone_id, device_id)
        else:
            kind = None if _grounded(item.value, free) else "unsupported"
        if kind is None:
            continue
        if raw_form and any(
            fields == frozenset({field}) and _grounded(item.value, (value,))
            for field, value in exempt
        ):
            continue
        violations.append(GroundingViolation(kind, item.value, item.start, item.end, fields))
    return violations


def format_number(value: float) -> str:
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return repr(value)
