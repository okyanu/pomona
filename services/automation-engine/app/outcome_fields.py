"""Which readings may confirm a suggestion's outcome in a multi-device zone (docs/design/multi-device-zones-slice2.md 2.7).

A zone-view suggestion names no single device. Its context carries `sources` (reading field to the devices that supply
it, or should), and the labels the suggestion watches map to the fields they are raised from. Only a reading from one of
those devices can show the problem went away. The map was checked against model-router `tomato_reasoner.py` and
`nutrient_ph_ec.py`.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Set

MOISTURE_FIELDS = ("substrate_moisture_pct", "root_zone_moisture_pct", "soil_moisture_pct")

LABEL_FIELDS: Dict[str, tuple] = {
    "high_ec": ("ec_ms_cm",),
    "low_ec": ("ec_ms_cm",),
    "high_ph": ("ph",),
    "low_ph": ("ph",),
    # the router raises both from either temperature reading
    "heat_stress": ("air_temperature_c", "substrate_temperature_c"),
    "cold_stress": ("air_temperature_c", "substrate_temperature_c"),
    # raised from humidity and from VPD (air temperature and humidity)
    "fungal_pressure": ("air_temperature_c", "humidity_pct"),
    "water_level_risk": MOISTURE_FIELDS,
}


def watched_fields(watched_labels: Iterable[str], context: Dict[str, Any]) -> Set[str]:
    """The reading fields behind the labels a suggestion watches. Every label not in LABEL_FIELDS (the sensor-check
    labels) stands for the suggestion's own `vetoed_fields` and `missing_fields`."""
    fields: Set[str] = set()
    for label in watched_labels:
        if label in LABEL_FIELDS:
            fields.update(LABEL_FIELDS[label])
        else:
            for key in ("vetoed_fields", "missing_fields"):
                value = context.get(key)
                if isinstance(value, list):
                    fields.update(name for name in value if isinstance(name, str))
    return fields


def counting_devices(sources: Dict[str, Any], fields: Iterable[str]) -> List[str]:
    """The union of `sources[f]` over the watched fields that appear in `sources`, sorted. Empty: nobody is expected to
    carry the watched field, so no reading counts."""
    devices: Set[str] = set()
    for name in fields:
        ids = sources.get(name)
        if isinstance(ids, list):
            devices.update(d for d in ids if isinstance(d, str))
    return sorted(devices)
