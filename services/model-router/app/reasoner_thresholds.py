"""pH/EC thresholds and system-type names shared by the tomato and nutrient reasoners.

Both reasoners read these numbers from here so they cannot drift apart. The safety-checker carries its own
copy of the tomato rules (services/safety-checker/app/tomato_rules.py: a separate image cannot import this
module); tests/test_tomato_vpd.py checks that the two give identical answers on and around every number below.
"""

from __future__ import annotations

from typing import Any

# Recirculating/no-substrate systems: covers naming drift between the
# platform ("controlled_greenhouse"), the training dataset
# ("hydroponic_greenhouse"), and the hardware event contract ("hydroponic").
HYDROPONIC_SYSTEM_TYPES = {"controlled_greenhouse", "hydroponic_greenhouse", "hydroponic"}
SUBSTRATE_SYSTEM_TYPE = "greenhouse_substrate"

# pH: at or below / at or above the anomaly limits is a probe problem, not a nutrient label.
PH_ANOMALY_LOW = 3.5
PH_ANOMALY_HIGH = 9.0
PH_HIGH = 7.2
PH_LOW = 5.3

# EC (mS/cm): outside the anomaly limits is a probe problem; EC_LOW_* is the low-EC label per system family.
EC_ANOMALY_LOW = 0.01
EC_ANOMALY_HIGH = 10
EC_HIGH = 4.5
EC_LOW_HYDROPONIC = 0.8
EC_LOW_SUBSTRATE = 0.05


def is_hydroponic(system_type: Any) -> bool:
    return isinstance(system_type, str) and system_type in HYDROPONIC_SYSTEM_TYPES
