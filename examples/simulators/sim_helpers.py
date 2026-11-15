"""Small shared helpers for the fake greenhouse tests and the abstention eval (standard library only).

  make_clock          a fixed, stepping clock for `fake_greenhouse.Simulation(clock=...)`
  split_zone_packet   one zone packet as the two devices of a multi-device zone (docs/design/abstention-eval-set.md 4.2)
  holdout_scenario    a generated scenario for one holdout seed (docs/design/abstention-eval-set.md 4.4)
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

DEFAULT_CLOCK_START = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def make_clock(step_s: float = 30.0, start: Optional[datetime] = None) -> Callable[[], datetime]:
    """A clock that returns `start` (default 2026-06-01 12:00 UTC), then `step_s` seconds later on every call."""
    state = {"now": start or DEFAULT_CLOCK_START}

    def clock() -> datetime:
        now = state["now"]
        state["now"] = now + timedelta(seconds=step_s)
        return now

    return clock


# --- Split zones (4.2) ----------------------------------------------------------------------------------------

CLIMATE_DEVICE = "climate-1"
SUBSTRATE_DEVICE = "substrate-1"
# Which device owns which reading field. The moisture alias goes with the moisture probe.
SPLIT_OWNERS = {
    CLIMATE_DEVICE: ("air_temperature_c", "humidity_pct"),
    SUBSTRATE_DEVICE: ("ph", "ec_ms_cm", "soil_moisture_pct", "substrate_moisture_pct", "substrate_temperature_c"),
}
SPLIT_BOOT_SUFFIX = {CLIMATE_DEVICE: "-climate", SUBSTRATE_DEVICE: "-substrate"}
# Keys both devices carry (when the packet has them).
SPLIT_SHARED = ("farm_id", "zone_id", "crop", "growth_stage", "system_type", "timestamp", "schema_version", "weather",
                "zone_area_m2", "crop_kc", "npk_target", "sequence", "boot_id")


def split_zone_packet(event: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The packet of one zone as two device packets, `climate-1` first, `substrate-1` second.

    Same sample time and sequence for both; each device gets its own `boot_id` (the original with `-climate` /
    `-substrate` appended) so the two streams are never mistaken for one device. A field the original lacks (a probe
    dropout removed it) is absent from its owner's packet. The input is not changed.
    """
    packets = []
    for device_id, owned in SPLIT_OWNERS.items():
        packet: Dict[str, Any] = {"device_id": device_id}
        packet.update({key: event[key] for key in SPLIT_SHARED if key in event})
        packet.update({key: event[key] for key in owned if key in event})
        if "boot_id" in packet:
            packet["boot_id"] = f"{event['boot_id']}{SPLIT_BOOT_SUFFIX[device_id]}"
        packets.append(packet)
    return packets


# --- Holdout scenarios (4.4) ----------------------------------------------------------------------------------

HOLDOUT_TICKS = 900
HOLDOUT_ZONES = ("greenhouse-a", "greenhouse-b")
# Fields each zone has (fake_greenhouse.DEFAULT_ZONES): a has a substrate, b is hydroponic.
HOLDOUT_FIELDS = {
    "greenhouse-a": ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph", "soil_moisture_pct",
                     "substrate_temperature_c"),
    "greenhouse-b": ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph"),
}
HOLDOUT_EVENTS = {
    "greenhouse-a": ("heat_spike", "cold_night", "humid_night", "nutrient_over_concentration", "dry_zone"),
    "greenhouse-b": ("heat_spike", "cold_night", "humid_night", "nutrient_over_concentration"),
}
# The field a real event is decided on (where a probe dropout hides it).
EVENT_FIELD = {"heat_spike": "air_temperature_c", "cold_night": "air_temperature_c", "humid_night": "humidity_pct",
               "nutrient_over_concentration": "ec_ms_cm", "dry_zone": "soil_moisture_pct"}
# Offsets large enough to cross the smallest step allowance of the field (sensor_quality.STEP_LIMITS, and the
# pH/EC drift thresholds).
JUMP_OFFSETS = {"air_temperature_c": 5.0, "humidity_pct": 20.0, "soil_moisture_pct": 15.0,
                "substrate_temperature_c": 3.0, "ph": 1.5, "ec_ms_cm": 1.0}
STALE_MIN_TICKS = 160  # long enough for the +75 minute re-run (150 ticks of 30 s) to fall inside the dropout


def holdout_scenario(seed: int) -> Dict[str, Any]:
    """A scenario drawn from `random.Random(f"holdout:{seed}")` from the same menu as scenarios/abstention.json.

    Per zone, from tick 30 on: real events with a probe dropout on their deciding field (probe_dropout steps carry a
    `group`: `coarse_only` or `silent`, the family their questions belong to), single sensor faults (stuck, noisy, jump,
    drift, spike, and the two undetectable ones), a probe dropout alone, and one whole-device dropout long enough for
    the stale re-runs. Faults and events of one zone never overlap. Deterministic: same seed, same dict.
    """
    rng = random.Random(f"holdout:{seed}")
    steps: List[Dict[str, Any]] = []

    def start(tick: int, name: str, zone: str, field: Optional[str] = None, params: Optional[Dict[str, Any]] = None,
              group: Optional[str] = None) -> None:
        step: Dict[str, Any] = {"at_tick": tick, "start": name, "zone": zone}
        if field:
            step["field"] = field
        if params:
            step["params"] = params
        if group:
            step["group"] = group
        steps.append(step)

    def stop(tick: int, name: str, zone: str) -> None:
        steps.append({"at_tick": tick, "stop": name, "zone": zone})

    for zone in HOLDOUT_ZONES:
        fields = HOLDOUT_FIELDS[zone]
        blocks = ["event", "event", "fault", "fault", "fault", "dropout_only", "stale"]
        rng.shuffle(blocks)
        cursor = rng.randint(30, 60)
        for block in blocks:
            if block == "event":
                length = rng.randint(110, 150)
                name = rng.choice(HOLDOUT_EVENTS[zone])
                field = EVENT_FIELD[name]
                params = {"recover_min": 10} if name == "nutrient_over_concentration" else None
                start(cursor, name, zone, params=params)
                if rng.random() < 0.85:
                    start(cursor + 6, "probe_dropout", zone, field, group=rng.choice(("coarse_only", "silent")))
                    stop(cursor + length, "probe_dropout", zone)
                stop(cursor + length, name, zone)
                cursor += length + rng.randint(20, 30)
            elif block == "fault":
                length = rng.randint(50, 70)
                kind = rng.choice(("stuck", "stuck", "noisy", "noisy", "jump", "drift", "spike", "plausible_offset"))
                if kind == "spike":
                    start(cursor, "spike", zone, "ph")
                    cursor += 12 + 20
                    continue
                if kind == "plausible_offset":
                    start(cursor, "plausible_offset", zone, "ec_ms_cm")
                elif kind == "drift":
                    field = rng.choice(("ec_ms_cm", "ph", "ph", "ec_ms_cm", "air_temperature_c", "humidity_pct"))
                    start(cursor, "drift", zone, field)
                    length = rng.randint(60, 80)
                elif kind == "jump":
                    field = rng.choice(fields)
                    start(cursor, "jump", zone, field, {"offset": JUMP_OFFSETS[field]})
                else:
                    start(cursor, kind, zone, rng.choice(fields))
                stop(cursor + length, kind, zone)
                cursor += length + rng.randint(15, 25)
            elif block == "dropout_only":
                length = rng.randint(60, 100)
                start(cursor, "probe_dropout", zone, rng.choice(fields), group=rng.choice(("coarse_only", "silent")))
                stop(cursor + length, "probe_dropout", zone)
                cursor += length + rng.randint(15, 25)
            else:
                length = rng.randint(STALE_MIN_TICKS, STALE_MIN_TICKS + 20)
                start(cursor, "dropout", zone)
                stop(cursor + length, "dropout", zone)
                cursor += length + rng.randint(15, 25)
    steps = [step for step in steps if step["at_tick"] < HOLDOUT_TICKS]
    steps.sort(key=lambda s: s["at_tick"])  # stable: a start and its stop keep their order
    return {"seed": seed, "duration_ticks": HOLDOUT_TICKS, "steps": steps}
