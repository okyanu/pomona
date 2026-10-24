"""Which sensor readings the guarded pipeline expects, chosen from the farm's system type."""

from __future__ import annotations

from typing import Any

BASE_EXPECTED_FIELDS = ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
# Same order as water_irrigation._moisture_field.
MOISTURE_FIELDS = ("substrate_moisture_pct", "root_zone_moisture_pct", "soil_moisture_pct")
# System types without a substrate moisture probe: recirculating solution, no growing medium to read.
NO_MOISTURE_SYSTEM_TYPES = {"controlled_greenhouse"}
NO_MOISTURE_MARKERS = ("hydropon", "aquapon", "nft", "dwc")


def has_moisture_probe(system_type: Any) -> bool:
    """Substrate/soil systems (and unknown ones, conservatively) are expected to report moisture."""
    if not isinstance(system_type, str):
        return True
    name = system_type.strip().lower()
    return not (name in NO_MOISTURE_SYSTEM_TYPES or any(marker in name for marker in NO_MOISTURE_MARKERS))


def expected_fields_for(farm_context: dict[str, Any], sensor: dict[str, Any]) -> list[str]:
    """Expected readings: the core four always, plus a moisture field only where the system has a probe.

    The moisture field is the first one the packet has a value for (Core packets carry the unused ones
    as null); when none has a value, substrate_moisture_pct, so a missing probe is reported missing.
    """
    fields = list(BASE_EXPECTED_FIELDS)
    if has_moisture_probe(farm_context.get("system_type")):
        fields.append(next((f for f in MOISTURE_FIELDS if sensor.get(f) is not None), MOISTURE_FIELDS[0]))
    return fields
