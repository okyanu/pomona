#!/usr/bin/env python3
"""Fake greenhouse: a deterministic simulator with injectable sensor faults and real events.

The hidden TRUE state of two zones is advanced by a simple physical model. A SENSOR layer
(noise, quantisation, faults) turns it into the readings published over MQTT. A truth log
records, for every reading attempt, what the true state was and what a correct system should
conclude. Sensor faults change only what is sent (the truth is unchanged); real events change
the truth (the reading stays correct). The truth log is never sent over MQTT.

The model uses the standard library only; paho-mqtt is imported lazily by the MQTT publisher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import sys
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

# --- Thresholds the expected labels are computed from -------------------------------------
# These mirror services/model-router/app/tomato_reasoner.py (derive_tomato_risk and
# LOW_VPD_KPA). Keep them in step with that file. Only the four labels that a real event can
# cause are modelled: heat_stress, fungal_pressure, high_ec, water_level_risk.
HEAT_C = 30.0                 # air or substrate temperature >= this -> heat_stress
FUNGAL_HUMIDITY_PCT = 85.0    # humidity >= this -> fungal_pressure
LOW_VPD_KPA = 0.4             # VPD < this -> fungal_pressure
HIGH_EC_MS_CM = 4.5           # EC >= this -> high_ec
WATER_RISK_LOW_PCT = 10.0     # substrate moisture < this -> water_level_risk
WATER_RISK_HIGH_PCT = 85.0    # substrate moisture > this -> water_level_risk

# --- Normal (healthy) baseline: kept well away from every threshold above ------------------
AIR_RANGE_C = (19.5, 27.5)        # diurnal min near 05:00, max near 15:00
HUMIDITY_RANGE_PCT = (56.0, 69.0)  # inverse diurnal
SUBSTRATE_OFFSET_C = 1.5          # substrate runs this much cooler than air, with lag
FEED_EC = 2.6                     # nutrient solution EC applied by irrigation
IRRIGATED_PCT = 62.0              # a pulse closes 70 % of the gap between moisture and this
MOISTURE_CAP_PCT = 68.0
PULSE_HOURS = (6.0, 19.0)         # irrigation pulses only in daylight, every 30-90 min of sim time
PULSE_EC_STEP = 0.15              # max EC change per pulse (a slab's EC barely moves per pulse)
DRY_RESIDUAL_PCT = 3.0            # substrate never reads exactly 0 %: residual water the drying stops at
DRY_ZONE_PCT_PER_HOUR = 70.0      # dry_zone drying rate: fast on purpose, about 45 min from 60 % to <10 %
PLACEHOLDER_MOISTURE_PCT = 50.0   # hydroponic zone: Core's SensorEvent still requires the field

# Pomona's sensor checks look at the last 11 packets (services/model-router/app/sensor_quality.py),
# so wrong values linger in its history for this many samples after a sensor fault stops.
RECOVERY_SAMPLES = 11

SIM_EPOCH = date(2026, 6, 1)      # arbitrary calendar day for the simulated clock
DEAD_CLOCK_TIMESTAMP = "1970-01-01T00:00:00Z"

# Sensor layer: Gaussian noise sigma and quantisation step per field, then physical limits.
SENSOR_ORDER = ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph",
                "soil_moisture_pct", "substrate_temperature_c")
NOISE = {"air_temperature_c": 0.1, "humidity_pct": 0.8, "ec_ms_cm": 0.03, "ph": 0.02,
         "soil_moisture_pct": 0.5, "substrate_temperature_c": 0.1}
# Air temperature and humidity: SHT3x-class (0.01). Substrate temperature: DS18B20-class (0.0625).
STEP = {"air_temperature_c": 0.01, "substrate_temperature_c": 0.0625, "humidity_pct": 0.01,
        "ec_ms_cm": 0.01, "ph": 0.01, "soil_moisture_pct": 0.1}
LIMITS = {"air_temperature_c": (-40.0, 80.0), "substrate_temperature_c": (-40.0, 80.0),
          "humidity_pct": (0.0, 100.0), "ec_ms_cm": (0.0, 20.0), "ph": (0.0, 14.0),
          "soil_moisture_pct": (0.0, 100.0)}
# One moisture probe is published under two names (the tomato reasoner reads the second).
FIELD_ALIASES = {"substrate_moisture_pct": "soil_moisture_pct"}


@dataclass(frozen=True)
class ZoneConfig:
    zone_id: str
    device_id: str
    system_type: str
    sensors: Tuple[str, ...]
    has_substrate: bool


DEFAULT_ZONES = (
    ZoneConfig("greenhouse-a", "fake-substrate-01", "greenhouse_substrate", SENSOR_ORDER, True),
    ZoneConfig("greenhouse-b", "fake-hydro-01", "hydroponic_greenhouse",
               ("air_temperature_c", "humidity_pct", "ec_ms_cm", "ph"), False),
)


def vpd_kpa(air_temperature_c: float, humidity_pct: float) -> float:
    """Vapour-pressure deficit (FAO-56 eq. 11, Magnus form), as the reasoner computes it."""
    saturation = 0.6108 * math.exp(17.27 * air_temperature_c / (air_temperature_c + 237.3))
    return max(saturation * (1 - humidity_pct / 100), 0.0)


def diurnal(hour: float, low: float, high: float, t_min: float = 5.0, t_max: float = 15.0) -> float:
    """Smooth day curve: `low` at t_min, `high` at t_max (10 h rise, 14 h fall)."""
    hour %= 24.0
    rise = t_max - t_min
    if t_min <= hour <= t_max:
        shape = 0.5 - 0.5 * math.cos(math.pi * (hour - t_min) / rise)
    else:
        shape = 0.5 + 0.5 * math.cos(math.pi * ((hour - t_max) % 24.0) / (24.0 - rise))
    return low + (high - low) * shape


def quantise(field: str, value: float) -> float:
    """Round to the sensor step, clamp to its physical limits."""
    low, high = LIMITS[field]
    step = STEP[field]
    return round(min(max(round(value / step) * step, low), high), 2)


def canonical(field: Optional[str]) -> Optional[str]:
    return FIELD_ALIASES.get(field, field) if field else field


# --- Faults and events --------------------------------------------------------------------

class Injection:
    """Something switched on and off during a run, bound to one zone (and maybe a field)."""

    name = ""
    kind = ""
    description = ""
    default_field: Optional[str] = None
    needs_field = False
    default_params: Dict[str, float] = {}
    extra_params: Tuple[str, ...] = ()  # accepted params that have no fixed default
    source = "scenario"                 # who started it: scenario, manual or hidden
    hidden_id: Optional[int] = None

    def __init__(self, zone: "Zone", field: Optional[str], params: Dict[str, Any], tick: int, now: str):
        self.zone_id = zone.cfg.zone_id
        self.field = canonical(field) or self.default_field
        self.started_tick = tick
        self.started_at = now
        self.stopping = False
        unknown = sorted(set(params) - set(self.default_params) - set(self.extra_params))
        if unknown:
            accepted = sorted(set(self.default_params) | set(self.extra_params))
            raise ValueError(f"{self.name}: unknown params {unknown}; accepted {accepted}")
        for key, value in params.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"{self.name}: param {key} must be a number")
        self.params = {**self.default_params, **params}
        if self.field and not self.takes_field():
            raise ValueError(f"{self.name} takes no field")
        if self.needs_field and not self.field:
            raise ValueError(f"{self.name} needs a field")
        if self.field and self.field not in zone.cfg.sensors:
            raise ValueError(f"{self.name}: zone {self.zone_id} has no sensor field {self.field}")

    @classmethod
    def takes_field(cls) -> bool:
        return cls.needs_field or cls.default_field is not None

    @property
    def finished(self) -> bool:
        return self.stopping

    def stop(self) -> None:
        self.stopping = True

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "field": self.field, "started_at": self.started_at,
                "started_tick": self.started_tick, "source": self.source}


class Fault(Injection):
    """Sensor fault: changes what is sent, never the truth."""

    kind = "sensor_fault"
    detectable = True
    drops = False       # no packet is published
    dead_clock = False  # timestamp is the unset-RTC value
    elapsed_min = 0.0   # real minutes since the fault started (set by the simulation each tick)

    def noise_factor(self, field: str) -> float:
        return 1.0

    def apply(self, field: str, value: float, last_sent: Optional[float]) -> float:
        return value

    def wrong_fields(self) -> List[str]:
        if not self.field:
            return []
        return ["soil_moisture_pct", "substrate_moisture_pct"] if self.field == "soil_moisture_pct" else [self.field]


class Stuck(Fault):
    name, needs_field = "stuck", True
    description = "The field freezes at its last sent value."

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.frozen: Optional[float] = None

    def apply(self, field: str, value: float, last_sent: Optional[float]) -> float:
        if field != self.field:
            return value
        if self.frozen is None:
            self.frozen = value if last_sent is None else last_sent
        return self.frozen


DRIFT_PER_MIN = {"ec_ms_cm": 0.05, "ph": 0.02, "air_temperature_c": 0.1, "substrate_temperature_c": 0.1,
                 "humidity_pct": 0.5, "soil_moisture_pct": 0.5}


class Drift(Fault):
    """Linear drift; `rate_per_min` is in the field's unit per real minute."""

    name, default_field = "drift", "ec_ms_cm"
    description = "The field drifts linearly; rate_per_min per real minute (EC 0.05, pH 0.02 by default)."
    extra_params = ("rate_per_min",)

    def apply(self, field: str, value: float, last_sent: Optional[float]) -> float:
        if field != self.field:
            return value
        rate = float(self.params.get("rate_per_min", DRIFT_PER_MIN[field]))
        return value + rate * self.elapsed_min


class Jump(Fault):
    name, default_field = "jump", "ph"
    description = "The field is shifted by a constant offset (pH +1.5)."
    default_params = {"offset": 1.5}

    def apply(self, field: str, value: float, last_sent: Optional[float]) -> float:
        return value + self.params["offset"] if field == self.field else value


class Spike(Fault):
    """One absurd sample, then the fault removes itself."""

    name, default_field = "spike", "ph"
    description = "One absurd sample (pH 13.0), then it removes itself."
    default_params = {"value": 13.0}

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.fired = False

    @property
    def finished(self) -> bool:
        return self.stopping or self.fired

    def apply(self, field: str, value: float, last_sent: Optional[float]) -> float:
        if field != self.field:
            return value
        self.fired = True
        return self.params["value"]


class Noisy(Fault):
    name, needs_field = "noisy", True
    description = "Noise on the field is multiplied by factor."
    default_params = {"factor": 10.0}

    def noise_factor(self, field: str) -> float:
        return self.params["factor"] if field == self.field else 1.0


class Dropout(Fault):
    name, drops = "dropout", True
    description = "No packets are published for the zone."


class DeadClock(Fault):
    """The device stamps 1970-01-01. Core rejects the event; the right answer is rejected_by_core."""

    name, dead_clock = "dead_clock", True
    description = "The device stamps 1970-01-01; Core rejects the packet."


class PlausibleOffset(Fault):
    """Constant in-range offset. Pomona has no way to tell today, so detectable is false."""

    name, default_field, detectable = "plausible_offset", "ec_ms_cm", False
    description = "A constant in-range offset (EC +3.0); undetectable by Pomona today."
    default_params = {"offset": 3.0}

    def apply(self, field: str, value: float, last_sent: Optional[float]) -> float:
        return value + self.params["offset"] if field == self.field else value


class Event(Injection):
    """Real event: changes the truth. The readings stay correct."""

    kind = "real_event"
    level = 0.0  # 0..1 strength; ramps up while active and back down after stop

    def advance(self, wall_min: float) -> None:
        pass

    def overlay(self, field: str, value: float) -> float:
        return value

    def describe(self) -> Dict[str, Any]:
        return {**super().describe(), "level": round(self.level, 3), "stopping": self.stopping}


class RampEvent(Event):
    """Pulls one true value toward `target` as the level ramps (the state underneath is untouched).

    Ramps are in WALL minutes (`ramp_min` up, `recover_min` down, default the same), so they do
    not depend on --sim-speed and Pomona's per-sample and wall-clock checks see realistic timing.
    """

    true_field = ""
    extra_params = ("recover_min",)

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        if self.params["ramp_min"] <= 0 or self.params.get("recover_min", 1.0) <= 0:
            raise ValueError(f"{self.name}: ramp_min and recover_min must be positive")

    @property
    def finished(self) -> bool:
        return self.stopping and self.level <= 0.0

    def advance(self, wall_min: float) -> None:
        ramp = self.params["ramp_min"]
        if self.stopping:
            self.level = max(0.0, self.level - wall_min / self.params.get("recover_min", ramp))
        else:
            self.level = min(1.0, self.level + wall_min / ramp)

    def overlay(self, field: str, value: float) -> float:
        if field != self.true_field:
            return value
        return value + self.level * max(0.0, self.params["target"] - value)


class HeatSpike(RampEvent):
    # Vent failure on a sunny day.
    name, true_field = "heat_spike", "air_temperature_c"
    description = "Air temperature ramps to about 33 C (vent failure on a sunny day)."
    default_params = {"ramp_min": 20.0, "target": 33.0}


class HumidNight(RampEvent):
    name, true_field = "humid_night", "humidity_pct"
    description = "Humidity ramps to about 90 %."
    default_params = {"ramp_min": 20.0, "target": 90.0}


class NutrientOverConcentration(RampEvent):
    # A doser or top-up error: about 3 mS/cm per hour.
    name, true_field = "nutrient_over_concentration", "ec_ms_cm"
    description = "EC ramps to about 5.0 mS/cm (doser or top-up error)."
    default_params = {"ramp_min": 60.0, "target": 5.0}


class DryZone(Event):
    """Irrigation fails in the substrate zone, so moisture keeps falling.

    Moisture falls at `drying_pct_per_hour` (default 70, so about 45 minutes from 60 % to under
    10 %). That is fast for demo purposes; real substrate takes many hours without irrigation.
    """

    name = "dry_zone"
    description = "Irrigation fails and substrate moisture falls fast (demo speed). Substrate zones only."
    default_params = {"drying_pct_per_hour": DRY_ZONE_PCT_PER_HOUR}

    def __init__(self, zone: "Zone", *args: Any, **kwargs: Any):
        if not zone.cfg.has_substrate:
            raise ValueError(f"dry_zone needs a substrate zone, {zone.cfg.zone_id} has none")
        super().__init__(zone, *args, **kwargs)
        if self.params["drying_pct_per_hour"] < 0:
            raise ValueError("dry_zone: drying_pct_per_hour must not be negative")
        self.level = 1.0


REGISTRY: Dict[str, type] = {cls.name: cls for cls in (
    Stuck, Drift, Jump, Spike, Noisy, Dropout, DeadClock, PlausibleOffset,
    DryZone, HeatSpike, HumidNight, NutrientOverConcentration)}


# --- Zone: true state and sensor layer ----------------------------------------------------

def ou(x: float, rate: float, sigma: float, draw: float, dt_h: float, bound: float) -> float:
    """One Ornstein-Uhlenbeck step around zero, clipped to +-bound."""
    x += -rate * x * dt_h + sigma * math.sqrt(dt_h) * draw
    return min(max(x, -bound), bound)


class Zone:
    def __init__(self, cfg: ZoneConfig, seed: int, start_hour: float):
        self.cfg = cfg
        self.truth_rng = random.Random(f"{seed}:{cfg.zone_id}:truth")
        self.sensor_rng = random.Random(f"{seed}:{cfg.zone_id}:sensor")
        self.boot_id = "boot-" + hashlib.sha1(f"fake-greenhouse:{seed}:{cfg.device_id}".encode()).hexdigest()[:8]
        self.sequence = 0
        self.last_sent: Dict[str, float] = {}
        self.faults: List[Fault] = []
        self.events: List[Event] = []
        self.air_walk = 0.0
        self.humidity_walk = 0.0
        self.ec = FEED_EC if cfg.has_substrate else 2.2
        self.ph = 6.1 if cfg.has_substrate else 6.0
        self.moisture = 60.0
        self.water_temp = 21.5
        self.irrigated = False
        self.dosed = False
        self.next_pulse_h = start_hour + 0.5
        self.recovery: List[List[Any]] = []  # [fault name, published samples left] after a sensor fault stops
        self.substrate_temp = self._air(start_hour) - SUBSTRATE_OFFSET_C

    # Truth ----------------------------------------------------------------------------

    def _overlaid(self, field: str, value: float) -> float:
        for event in self.events:
            value = event.overlay(field, value)
        return value

    def _air(self, hour: float) -> float:
        return self._overlaid("air_temperature_c", diurnal(hour, *AIR_RANGE_C) + self.air_walk)

    def _humidity(self, hour: float) -> float:
        low, high = HUMIDITY_RANGE_PCT
        return self._overlaid("humidity_pct", high - (diurnal(hour, 0.0, 1.0) * (high - low)) + self.humidity_walk)

    def advance(self, end_hour: float, dt_h: float, wall_min: float) -> None:
        """Advance the true state by dt_h simulated hours (wall_min real minutes) ending at end_hour.

        Long steps are split into sub-steps of <= 1 simulated hour.
        """
        steps = max(1, math.ceil(dt_h - 1e-9))
        sub = dt_h / steps
        self.irrigated = self.dosed = False
        for i in range(steps):
            abs_hour = end_hour - dt_h + sub * (i + 1)
            hour = abs_hour % 24.0
            g = [self.truth_rng.gauss(0.0, 1.0) for _ in range(8)]
            for event in self.events:
                event.advance(wall_min / steps)
            self.air_walk = ou(self.air_walk, 0.15, 0.25, g[0], sub, 1.2)
            self.humidity_walk = ou(self.humidity_walk, 0.15, 0.8, g[1], sub, 2.5)
            air = self._air(hour)
            humidity = self._humidity(hour)
            self.substrate_temp += (air - SUBSTRATE_OFFSET_C - self.substrate_temp) * (1 - math.exp(-sub / 2.0))
            self.water_temp += (21.5 + 0.25 * (air - 23.5) - self.water_temp) * (1 - math.exp(-sub / 12.0))
            if self.cfg.has_substrate:
                self._substrate_step(hour, abs_hour, air, humidity, sub, g)
            else:
                self._reservoir_step(sub, g)

    def _substrate_step(self, hour: float, abs_hour: float, air: float, humidity: float,
                        dt_h: float, g: List[float]) -> None:
        daylight = max(0.0, math.sin(math.pi * (hour - 6.0) / 12.0)) if 6.0 <= hour <= 18.0 else 0.0
        demand = min(max(vpd_kpa(air, humidity) / 1.2, 0.5), 1.6)
        rate = (0.3 + 2.4 * daylight) * demand * (1 + 0.1 * g[2])  # % moisture per hour
        dry = next((e for e in self.events if isinstance(e, DryZone)), None)
        if dry:
            rate = max(rate, dry.params["drying_pct_per_hour"])
        lost = min(rate * dt_h, max(self.moisture - DRY_RESIDUAL_PCT, 0.0))
        self.moisture -= lost
        self.ec += 0.015 * lost  # water leaves, salts stay
        if not dry and PULSE_HOURS[0] <= hour < PULSE_HOURS[1] and abs_hour >= self.next_pulse_h:
            # The refill is abrupt; the EC barely moves toward the feed EC.
            self.moisture = min(MOISTURE_CAP_PCT, self.moisture + 0.7 * (IRRIGATED_PCT - self.moisture))
            self.ec += min(max((FEED_EC + 0.1 * g[3] - self.ec) * 0.5, -PULSE_EC_STEP), PULSE_EC_STEP)
            self.next_pulse_h = abs_hour + min(max(0.75 + 0.3 * g[7], 0.5), 1.5)
            self.irrigated = True
        self.ec += 0.01 * math.sqrt(dt_h) * g[4]
        self.ph = 6.1 + ou(self.ph - 6.1, 0.02, 0.01, g[5], dt_h, 0.2)

    def _reservoir_step(self, dt_h: float, g: List[float]) -> None:
        self.ec = 2.2 + ou(self.ec - 2.2, 0.04, 0.02, g[3], dt_h, 0.4)
        self.ph += 0.012 * dt_h + 0.01 * math.sqrt(dt_h) * g[5]
        if self.ph > 6.2:  # occasional small dosing correction
            self.ph = 6.1 + 0.02 * g[6]
            self.dosed = True

    def true_values(self, hour: float) -> Dict[str, Any]:
        air = self._air(hour)
        humidity = self._humidity(hour)
        true: Dict[str, Any] = {
            "air_temperature_c": air,
            "humidity_pct": humidity,
            "ec_ms_cm": self._overlaid("ec_ms_cm", self.ec),
            "ph": self.ph,
            "vpd_kpa": vpd_kpa(air, humidity),
        }
        if self.cfg.has_substrate:
            true.update(substrate_temperature_c=self.substrate_temp, soil_moisture_pct=self.moisture,
                        substrate_moisture_pct=self.moisture, irrigated=self.irrigated)
        else:
            true.update(water_temperature_c=self.water_temp, dosed=self.dosed)
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in true.items()}

    # Sensors --------------------------------------------------------------------------

    def sample(self, true: Dict[str, Any]) -> Dict[str, float]:
        """Noisy, quantised, fault-altered readings. Draws are fixed per tick so faults never shift them."""
        draws = {field: self.sensor_rng.gauss(0.0, 1.0) for field in SENSOR_ORDER}
        sent: Dict[str, float] = {}
        for field in self.cfg.sensors:
            sigma = NOISE[field]
            for fault in self.faults:
                sigma *= fault.noise_factor(field)
            value = quantise(field, true[field] + draws[field] * sigma)
            for fault in self.faults:
                value = fault.apply(field, value, self.last_sent.get(field))
            sent[field] = quantise(field, value)
        return sent

    def build_event(self, sent: Dict[str, float], farm_id: str, timestamp: str) -> Dict[str, Any]:
        cfg = self.cfg
        event: Dict[str, Any] = {
            "device_id": cfg.device_id, "farm_id": farm_id, "zone_id": cfg.zone_id,
            "crop": "tomato", "growth_stage": "flowering", "system_type": cfg.system_type,
            "air_temperature_c": sent["air_temperature_c"],
            "humidity_pct": sent["humidity_pct"],
            "ec_ms_cm": sent["ec_ms_cm"],
            "ph": sent["ph"],
        }
        if cfg.has_substrate:
            event["soil_moisture_pct"] = sent["soil_moisture_pct"]
            event["substrate_temperature_c"] = sent["substrate_temperature_c"]
            event["substrate_moisture_pct"] = sent["soil_moisture_pct"]
            event.update(zone_context())
        else:
            event["soil_moisture_pct"] = PLACEHOLDER_MOISTURE_PCT
        event.update(timestamp=timestamp, source="fake_greenhouse", schema_version="1.0",
                     sequence=self.sequence, boot_id=self.boot_id)
        return event

    @property
    def placeholder_fields(self) -> List[str]:
        return [] if self.cfg.has_substrate else ["soil_moisture_pct"]


def zone_context() -> Dict[str, Any]:
    """Zone-level FAO-56/NPK context, same shape as greenhouse_tomato.py, held steady."""
    return {
        "weather": {"t_mean_c": 23.5, "t_min_c": AIR_RANGE_C[0], "t_max_c": AIR_RANGE_C[1],
                    "rh_mean_pct": 62.0, "wind_speed_2m_ms": 1.5, "solar_radiation_mj_m2_day": 17.0,
                    "elevation_m": 300.0},
        "zone_area_m2": 20.0,
        "crop_kc": 1.15,
        "npk_target": {"n_ppm": 150.0, "p_ppm": 50.0, "k_ppm": 200.0, "volume_liters": 100.0},
    }


def expected_labels(true: Dict[str, Any]) -> List[str]:
    """Labels a correct system should raise for the TRUE state (see the threshold block)."""
    labels = []
    if true["air_temperature_c"] >= HEAT_C or true.get("substrate_temperature_c", 0.0) >= HEAT_C:
        labels.append("heat_stress")
    if true["humidity_pct"] >= FUNGAL_HUMIDITY_PCT or true["vpd_kpa"] < LOW_VPD_KPA:
        labels.append("fungal_pressure")
    if true["ec_ms_cm"] >= HIGH_EC_MS_CM:
        labels.append("high_ec")
    moisture = true.get("substrate_moisture_pct")
    if moisture is not None and (moisture < WATER_RISK_LOW_PCT or moisture > WATER_RISK_HIGH_PCT):
        labels.append("water_level_risk")
    return labels


# --- Simulation ---------------------------------------------------------------------------

@dataclass
class Reading:
    topic: str
    event: Optional[Dict[str, Any]]  # None when nothing was published
    truth: Dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def load_scenario(path: Path) -> Dict[str, Any]:
    scenario = json.loads(Path(path).read_text())
    for step in scenario.get("steps", []):
        name = step.get("start") or step.get("stop")
        if name not in REGISTRY or "at_tick" not in step or "zone" not in step:
            raise ValueError(f"bad scenario step: {step}")
    return scenario


class Simulation:
    def __init__(self, seed: int = 42, farm_id: str = "demo-farm", interval: float = 30.0,
                 sim_speed: float = 1.0, start_hour: float = 8.0,
                 clock: Callable[[], datetime] = utc_now, scenario: Optional[Dict[str, Any]] = None,
                 zones: Tuple[ZoneConfig, ...] = DEFAULT_ZONES):
        self.seed = seed
        self.farm_id = farm_id
        self.interval = interval
        self.sim_speed = sim_speed
        self.dt_h = interval * sim_speed / 3600.0
        self.start_hour = start_hour
        self.clock = clock
        self.steps = list((scenario or {}).get("steps", []))
        self.duration_ticks = (scenario or {}).get("duration_ticks")
        self.zones = {cfg.zone_id: Zone(cfg, seed, start_hour) for cfg in zones}
        self.tick = 0
        self.now = ""
        # Control page: commands queue up and apply at the start of the next step(), under the lock.
        self.lock = threading.RLock()
        self.pending: List[Dict[str, Any]] = []
        self.recorded: List[Dict[str, Any]] = []  # manual steps, replayable as a scenario
        self.hidden_rng = random.Random(f"{seed}:hidden")
        self.hidden_log: List[Dict[str, Any]] = []  # answer key: every hidden injection started
        self.revealed = False
        self.last_sent: Dict[str, Dict[str, Any]] = {}
        self.last_published: Dict[str, bool] = {}
        self.next_tick_due: Optional[float] = None  # time.monotonic() of the next tick, set by run()

    # Registry control (the scenario runner and the control page both use these) ----------

    def start(self, name: str, zone_id: str, field: Optional[str] = None, *, source: str = "scenario",
              **params: Any) -> Injection:
        """Start a fault or event. Starting one that is already active returns the active one.

        A hidden injection never merges with a visible one, so pressing a button cannot reveal it.
        """
        zone = self.zones[zone_id]
        injection = REGISTRY[name](zone, field, params, self.tick, self.now)
        injection.source = source
        for existing in zone.faults + zone.events:
            if (existing.name, existing.field, existing.source == "hidden") == (
                    injection.name, injection.field, source == "hidden"):
                existing.stopping = False  # restarting one that is still ramping down
                return existing
        (zone.faults if isinstance(injection, Fault) else zone.events).append(injection)
        return injection

    def stop(self, name: str, zone_id: str, field: Optional[str] = None, hidden: bool = False) -> int:
        """Stop matching injections (hidden ones only when `hidden`); returns how many were running."""
        zone = self.zones[zone_id]
        matched = 0
        for injection in zone.faults + zone.events:
            if (injection.name == name and (injection.source == "hidden") == hidden
                    and (field is None or injection.field == canonical(field)) and not injection.stopping):
                injection.stop()
                matched += 1
        self._prune()
        return matched

    def _prune(self, zone: Optional[Zone] = None) -> None:
        for z in [zone] if zone else self.zones.values():
            for fault in z.faults:
                if fault.finished and fault.wrong_fields():
                    z.recovery.append([fault.name, RECOVERY_SAMPLES])
            z.faults = [f for f in z.faults if not f.finished]
            z.events = [e for e in z.events if not e.finished]

    # Ticking -----------------------------------------------------------------------------

    def step(self) -> List[Reading]:
        """Run one tick: scenario steps, queued commands, physics, sensors. One Reading per zone."""
        with self.lock:
            return self._step()

    def _step(self) -> List[Reading]:
        tick = self.tick
        self.now = self.clock().astimezone(timezone.utc).isoformat()
        self._prune()
        for step in self.steps:
            if step["at_tick"] == tick:
                source = step.get("source", "scenario")
                if "start" in step:
                    self.start(step["start"], step["zone"], step.get("field"), source=source,
                               **step.get("params", {}))
                else:
                    self.stop(step["stop"], step["zone"], step.get("field"), hidden=source == "hidden")
        self._apply_commands(tick)
        sim_hours = self.start_hour + tick * self.dt_h
        readings = []
        for zone in self.zones.values():
            if tick > 0:
                zone.advance(sim_hours, self.dt_h, self.interval / 60.0)
                self._prune(zone)  # an event that has fully ramped down is over
            reading = self._read_zone(zone, tick, sim_hours)
            readings.append(reading)
            self.last_published[zone.cfg.zone_id] = reading.event is not None
            if reading.event is not None:
                self.last_sent[zone.cfg.zone_id] = reading.event
        self.tick += 1
        return readings

    # Control page ------------------------------------------------------------------------

    def validate_start(self, name: Any, zone_id: Any, field: Any, params: Any) -> Optional[str]:
        """Build a throwaway injection so a bad request fails here, never in the tick loop."""
        if not isinstance(name, str) or name not in REGISTRY:
            raise ValueError(f"unknown injection {name!r}; known: {sorted(REGISTRY)}")
        if not isinstance(zone_id, str) or zone_id not in self.zones:
            raise ValueError(f"unknown zone {zone_id!r}; known: {sorted(self.zones)}")
        if field is not None and not isinstance(field, str):
            raise ValueError("field must be a string")
        if params is not None and not isinstance(params, dict):
            raise ValueError("params must be an object")
        return REGISTRY[name](self.zones[zone_id], field, dict(params or {}), 0, "").field

    def applicable_zones(self, name: str) -> List[str]:
        cls = REGISTRY[name]
        zones = []
        for zone_id, zone in self.zones.items():
            field = cls.default_field or (zone.cfg.sensors[0] if cls.needs_field else None)
            try:
                cls(zone, field, {}, 0, "")
            except ValueError:
                continue
            zones.append(zone_id)
        return zones

    def queue_start(self, name: Any, zone_id: Any, field: Any = None, params: Any = None) -> None:
        self.validate_start(name, zone_id, field, params)
        self._queue({"op": "start", "name": name, "zone": zone_id, "field": field,
                     "params": dict(params or {}), "source": "manual"})

    def queue_stop(self, name: Any, zone_id: Any, field: Any = None) -> None:
        if not isinstance(name, str) or name not in REGISTRY:
            raise ValueError(f"unknown injection {name!r}")
        if not isinstance(zone_id, str) or zone_id not in self.zones:
            raise ValueError(f"unknown zone {zone_id!r}")
        if field is not None and not isinstance(field, str):
            raise ValueError("field must be a string")
        self._queue({"op": "stop", "name": name, "zone": zone_id, "field": field})

    def queue_stop_hidden(self, hidden_id: Any) -> None:
        with self.lock:
            if not any(entry["id"] == hidden_id for entry in self.hidden_log):
                raise ValueError(f"unknown hidden id {hidden_id!r}")
            self.pending.append({"op": "stop_hidden", "id": hidden_id})

    def queue_stop_all(self) -> None:
        self._queue({"op": "stop_all"})

    def queue_hidden(self) -> int:
        """Queue one random applicable injection from the dedicated hidden RNG; returns its id."""
        with self.lock:
            taken = {(i.name, i.zone_id) for z in self.zones.values() for i in z.faults + z.events
                     if i.source == "hidden"}
            taken |= {(c["name"], c["zone"]) for c in self.pending if c["op"] == "start" and c["source"] == "hidden"}
            candidates = [(name, zone_id) for name in REGISTRY for zone_id in self.applicable_zones(name)
                          if (name, zone_id) not in taken]
            if not candidates:
                raise ValueError("every applicable injection is already running hidden")
            name, zone_id = self.hidden_rng.choice(candidates)
            cls = REGISTRY[name]
            field = cls.default_field
            if cls.needs_field:
                field = self.hidden_rng.choice(list(self.zones[zone_id].cfg.sensors))
            hidden_id = len(self.hidden_log) + 1
            self.hidden_log.append({"id": hidden_id, "name": name, "zone": zone_id, "field": field,
                                    "queued_tick": self.tick, "started_tick": None})
            self.pending.append({"op": "start", "name": name, "zone": zone_id, "field": field, "params": {},
                                 "source": "hidden", "hidden_id": hidden_id})
            return hidden_id

    def reveal(self) -> List[Dict[str, Any]]:
        """From now on the state shows hidden injections by name. Returns every one started so far."""
        with self.lock:
            self.revealed = True
            return [{**entry, "active": any(i.hidden_id == entry["id"] for z in self.zones.values()
                                            for i in z.faults + z.events)} for entry in self.hidden_log]

    def _queue(self, command: Dict[str, Any]) -> None:
        with self.lock:
            self.pending.append(command)

    def _record(self, tick: int, op: str, name: str, zone_id: str, field: Optional[str],
                params: Optional[Dict[str, Any]], source: str) -> None:
        step: Dict[str, Any] = {"at_tick": tick, op: name, "zone": zone_id}
        if field:
            step["field"] = field
        if params:
            step["params"] = params
        step["source"] = source
        self.recorded.append(step)

    def _apply_commands(self, tick: int) -> None:
        """Apply queued commands (called under the lock, after the scenario steps) and record them."""
        commands, self.pending = self.pending, []
        for cmd in commands:
            if cmd["op"] == "start":
                try:
                    injection = self.start(cmd["name"], cmd["zone"], cmd["field"], source=cmd["source"],
                                           **cmd["params"])
                except ValueError:
                    continue
                if cmd["source"] == "hidden" and injection.hidden_id is None:
                    injection.hidden_id = cmd["hidden_id"]
                    self.hidden_log[cmd["hidden_id"] - 1]["started_tick"] = tick
                self._record(tick, "start", injection.name, cmd["zone"], injection.field, cmd["params"],
                             cmd["source"])
            elif cmd["op"] == "stop":
                if self.stop(cmd["name"], cmd["zone"], cmd["field"]):
                    self._record(tick, "stop", cmd["name"], cmd["zone"], cmd["field"], None, "manual")
            elif cmd["op"] == "stop_hidden":
                found = [i for z in self.zones.values() for i in z.faults + z.events
                         if i.hidden_id == cmd["id"] and not i.stopping]
                for injection in found:
                    if self.stop(injection.name, injection.zone_id, injection.field, hidden=True):
                        self._record(tick, "stop", injection.name, injection.zone_id, injection.field, None, "hidden")
            else:  # stop_all
                running = [(i.name, i.zone_id, i.field, i.source) for z in self.zones.values()
                           for i in z.faults + z.events if not i.stopping]
                for name, zone_id, field, source in running:
                    if self.stop(name, zone_id, field, hidden=source == "hidden"):
                        self._record(tick, "stop", name, zone_id, field, None, source)

    def catalog(self) -> Dict[str, Any]:
        return {
            "zones": [{"zone_id": z.cfg.zone_id, "device_id": z.cfg.device_id, "system_type": z.cfg.system_type,
                       "sensors": list(z.cfg.sensors)} for z in self.zones.values()],
            "injections": [{"name": name, "kind": cls.kind, "description": cls.description,
                            "takes_field": cls.takes_field(), "needs_field": cls.needs_field,
                            "default_field": cls.default_field, "zones": self.applicable_zones(name),
                            "default_params": cls.default_params} for name, cls in REGISTRY.items()],
        }

    def state(self) -> Dict[str, Any]:
        """What a tester may see while running: what was sent, never the truth or the expected answers."""
        with self.lock:
            zones = []
            for zone_id, zone in self.zones.items():
                running = [i for i in zone.faults + zone.events if i.source != "hidden"]
                zones.append({
                    "zone_id": zone_id, "device_id": zone.cfg.device_id, "system_type": zone.cfg.system_type,
                    "sequence": zone.sequence - 1 if zone.sequence else None,
                    "published": self.last_published.get(zone_id),
                    "last_sent": self.last_sent.get(zone_id),
                    "injections": [{"name": i.name, "field": i.field, "started_tick": i.started_tick,
                                    "stopping": i.stopping, "source": i.source} for i in running],
                })
            hidden = []
            for i in (i for z in self.zones.values() for i in z.faults + z.events if i.source == "hidden"):
                entry: Dict[str, Any] = {"hidden": True, "id": i.hidden_id}
                if self.revealed:
                    entry.update(name=i.name, zone=i.zone_id, field=i.field, started_tick=i.started_tick,
                                 stopping=i.stopping)
                hidden.append(entry)
            for cmd in self.pending:
                if cmd["op"] == "start" and cmd["source"] == "hidden":
                    entry = {"hidden": True, "id": cmd["hidden_id"], "queued": True}
                    if self.revealed:
                        entry.update(name=cmd["name"], zone=cmd["zone"], field=cmd["field"])
                    hidden.append(entry)
            due = None if self.next_tick_due is None else round(max(0.0, self.next_tick_due - time.monotonic()), 1)
            return {
                "tick": self.tick, "interval": self.interval, "seconds_to_next_tick": due,
                "revealed": self.revealed, "queued": len(self.pending), "recorded": len(self.recorded),
                "pending": [{"op": c["op"], "name": c["name"], "zone": c["zone"], "field": c["field"]}
                            for c in self.pending if c["op"] in ("start", "stop") and c.get("source") != "hidden"],
                "zones": zones, "hidden": hidden,
            }

    def session_scenario(self) -> Dict[str, Any]:
        """The original scenario steps merged with the manual ones. Contains the answer key."""
        with self.lock:
            steps = sorted([dict(s) for s in self.steps] + [dict(s) for s in self.recorded],
                           key=lambda s: s["at_tick"])  # stable: scenario steps stay before manual ones
            return {"seed": self.seed,
                    "duration_ticks": self.duration_ticks if self.duration_ticks is not None else self.tick,
                    "run": {"interval": self.interval, "sim_speed": self.sim_speed, "start_hour": self.start_hour},
                    "steps": steps}

    def _read_zone(self, zone: Zone, tick: int, sim_hours: float) -> Reading:
        cfg = zone.cfg
        hour = sim_hours % 24.0
        for fault in zone.faults:
            fault.elapsed_min = (tick - fault.started_tick) * self.interval / 60.0
        recovering = sorted({name for name, _ in zone.recovery})
        true = zone.true_values(hour)
        sent = zone.sample(true)
        dropout = any(f.drops for f in zone.faults)
        dead = any(f.dead_clock for f in zone.faults)
        event = None
        if not dropout:
            event = zone.build_event(sent, self.farm_id, DEAD_CLOCK_TIMESTAMP if dead else self.now)
            zone.sequence += 1
            zone.last_sent.update(sent)
            if not dead:  # Core keeps only accepted samples in the history
                for entry in zone.recovery:
                    entry[1] -= 1
                zone.recovery = [e for e in zone.recovery if e[1] > 0]

        wrong = sorted({name for f in zone.faults for name in f.wrong_fields()})
        onset_step = any(f.name == "plausible_offset" and 0 < f.started_tick and tick - f.started_tick < RECOVERY_SAMPLES
                         for f in zone.faults)
        sensor_faulty = any(f.wrong_fields() for f in zone.faults)
        if dropout:
            kind = "not_published"
        elif dead:
            kind = "rejected_by_core"
        elif sensor_faulty and zone.events:
            kind = "both"
        elif sensor_faulty:
            kind = "sensor_fault"
        elif zone.events:
            kind = "real_event"
        else:
            kind = "normal"

        sim_time = datetime(SIM_EPOCH.year, SIM_EPOCH.month, SIM_EPOCH.day) + timedelta(hours=sim_hours)
        truth = {
            "tick": tick,
            "wall_timestamp": self.now,
            "sim_time": sim_time.isoformat(timespec="seconds"),
            "sim_day": int(sim_hours // 24),
            "sim_hour": round(hour, 3),
            "zone_id": cfg.zone_id,
            "device_id": cfg.device_id,
            "published": event is not None,
            "reason": "dropout" if dropout else None,
            "sequence": event["sequence"] if event else None,
            "true": true,
            "sent": event,
            "active_faults": [f.describe() for f in zone.faults],
            "active_events": [e.describe() for e in zone.events],
            "placeholder_fields": zone.placeholder_fields,
            "expect": {
                "kind": kind,
                "expected_labels": expected_labels(true),
                "forbid_domain_cards_from": wrong,
                "detectable": all(f.detectable for f in zone.faults),
                "onset_step": onset_step,
                "recovering_from": recovering,
            },
        }
        topic = f"pomona/{self.farm_id}/{cfg.zone_id}/sensor/{cfg.device_id}/state"
        return Reading(topic, event, truth)


# --- Control page -------------------------------------------------------------------------

CONTROL_PAGE = Path(__file__).with_name("control_page.html")
MAX_BODY_BYTES = 65536


class ControlHandler(BaseHTTPRequestHandler):
    """Local control page and API. `sim` and `allowed_hosts` are set by start_control_server.

    There is no auth: bind it to localhost only. POSTs must be application/json, which a
    cross-origin page cannot send without a CORS preflight that this server never answers.
    """

    sim: Simulation
    allowed_hosts: Optional[set]

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _send(self, status: int, body: bytes, content_type: str, extra: Optional[Dict[str, str]] = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: Any, extra: Optional[Dict[str, str]] = None) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json", extra)

    def _host_ok(self) -> bool:
        """Refuse foreign Host headers (DNS rebinding) unless bound to all interfaces."""
        if self.allowed_hosts is None:
            return True
        header = self.headers.get("Host", "")
        host = header if header.endswith("]") or ":" not in header else header.rsplit(":", 1)[0]
        return host in self.allowed_hosts

    def do_GET(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "host not allowed"})
        path = self.path.split("?", 1)[0]
        if path == "/":
            return self._send(200, CONTROL_PAGE.read_bytes(), "text/html; charset=utf-8")
        if path == "/api/catalog":
            return self._json(200, self.sim.catalog())
        if path == "/api/state":
            return self._json(200, self.sim.state())
        if path == "/api/scenario":
            return self._json(200, self.sim.session_scenario(), {
                "Content-Disposition": 'attachment; filename="fake_greenhouse_session.json"'})
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._host_ok():
            return self._json(403, {"error": "host not allowed"})
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self._json(415, {"error": "Content-Type must be application/json"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if not 0 <= length <= MAX_BODY_BYTES:
                return self._json(413, {"error": "body too large"})
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            self._json(200, self._post(self.path.split("?", 1)[0], body))
        except LookupError:
            self._json(404, {"error": "not found"})
        except ValueError as error:  # includes bad JSON
            self._json(400, {"error": str(error)})

    def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        sim = self.sim
        if path == "/api/start":
            sim.queue_start(body.get("name"), body.get("zone"), body.get("field"), body.get("params"))
        elif path == "/api/stop":
            if "id" in body:
                sim.queue_stop_hidden(body["id"])
            else:
                sim.queue_stop(body.get("name"), body.get("zone"), body.get("field"))
        elif path == "/api/stop_all":
            sim.queue_stop_all()
        elif path == "/api/hidden":
            return {"ok": True, "id": sim.queue_hidden()}
        elif path == "/api/reveal":
            return {"ok": True, "hidden": sim.reveal()}
        else:
            raise LookupError(path)
        return {"ok": True, "queued": len(sim.pending)}


def start_control_server(sim: Simulation, host: str, port: int) -> ThreadingHTTPServer:
    """Serve the control page on a daemon thread; the tick loop stays in the caller's thread."""
    allowed = None if host in ("0.0.0.0", "::") else {"127.0.0.1", "localhost", "[::1]", host}
    handler = type("Handler", (ControlHandler,), {"sim": sim, "allowed_hosts": allowed})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    return server


# --- Publishers and runner ----------------------------------------------------------------

class MqttPublisher:
    def __init__(self, host: str, port: int):
        import paho.mqtt.client as mqtt  # lazy: the model and its tests do not need paho

        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

    def publish(self, topic: str, payload: str) -> None:
        self.client.publish(topic, payload, qos=0)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


class JsonlPublisher:
    """Dry run: write each event as one JSON line instead of publishing."""

    def __init__(self, handle: Any):
        self.handle = handle

    def publish(self, topic: str, payload: str) -> None:
        self.handle.write(payload + "\n")

    def close(self) -> None:
        self.handle.flush()


def summary_line(reading: Reading) -> str:
    truth, event = reading.truth, reading.event
    marks = [f"{f['name']}({f['field']})" if f["field"] else f["name"] for f in truth["active_faults"]]
    marks += [e["name"] for e in truth["active_events"]]
    suffix = f" [{', '.join(marks)}]" if marks else ""
    if event is None:
        return f"tick {truth['tick']} {truth['zone_id']} not published ({truth['reason']}){suffix}"
    return (f"tick {truth['tick']} {truth['zone_id']} seq={event['sequence']} "
            f"temp={event['air_temperature_c']} rh={event['humidity_pct']} ec={event['ec_ms_cm']} "
            f"ph={event['ph']} moisture={event['soil_moisture_pct']}{suffix}")


def run(sim: Simulation, publisher: Any, truth_handle: Any, ticks: Optional[int],
        sleep: Optional[Callable[[float], None]], log: Any = sys.stdout) -> None:
    """Tick until `ticks` is reached (forever when None), sleeping `interval` between ticks."""
    done = 0
    while ticks is None or done < ticks:
        for reading in sim.step():
            if reading.event is not None:
                publisher.publish(reading.topic, json.dumps(reading.event))
            truth_handle.write(json.dumps(reading.truth) + "\n")
            print(summary_line(reading), file=log)
        truth_handle.flush()
        done += 1
        if sleep and (ticks is None or done < ticks):
            sim.next_tick_due = time.monotonic() + sim.interval
            sleep(sim.interval)


def parse_args(argv: Optional[List[str]]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Deterministic fake greenhouse publishing Pomona sensor events.")
    p.add_argument("--seed", type=int, default=None, help="random seed (default: the scenario's, else 42)")
    p.add_argument("--interval", type=float, default=30.0, help="real seconds between publishes")
    p.add_argument("--sim-speed", type=float, default=1.0,
                   help="simulated seconds per real second; above 1 is a time-lapse that makes Pomona's "
                        "sample-count and wall-clock checks unrealistic")
    p.add_argument("--start-hour", type=float, default=8.0, help="simulated hour of day at tick 0")
    p.add_argument("--scenario", type=Path, help="JSON scenario of timed fault/event steps")
    p.add_argument("--ticks", type=int, help="stop after N ticks (default: scenario duration, else run forever)")
    p.add_argument("--truth-log", type=Path, default=Path("data/fake_greenhouse/truth.jsonl"))
    p.add_argument("--farm-id", default=os.getenv("SIM_FARM_ID", "demo-farm"))
    p.add_argument("--dry-run", action="store_true",
                   help="no MQTT; print events as JSON lines. No sleeping, unless --control-port is given")
    p.add_argument("--out", type=Path, help="with --dry-run, write the events here instead of stdout")
    p.add_argument("--fast", action="store_true", help="publish without sleeping between ticks")
    p.add_argument("--control-port", type=int, help="serve the control page and API on this port (0 = any free port)")
    p.add_argument("--control-host", default="127.0.0.1",
                   help="control page bind address; it has no auth, do not bind wider than localhost")
    args = p.parse_args(argv)
    if args.fast and args.control_port is not None:
        p.error("--fast cannot be combined with --control-port (the page needs real-time ticks)")
    return args


def main(argv: Optional[List[str]] = None, clock: Callable[[], datetime] = utc_now,
         sleep: Callable[[float], None] = time.sleep) -> int:
    args = parse_args(argv)
    scenario = load_scenario(args.scenario) if args.scenario else None
    seed = args.seed if args.seed is not None else (scenario or {}).get("seed", 42)
    ticks = args.ticks if args.ticks is not None else (scenario or {}).get("duration_ticks")
    sim = Simulation(seed=seed, farm_id=args.farm_id, interval=args.interval, sim_speed=args.sim_speed,
                     start_hour=args.start_hour, clock=clock, scenario=scenario)

    args.truth_log.parent.mkdir(parents=True, exist_ok=True)
    server = None
    if args.control_port is not None:
        server = start_control_server(sim, args.control_host, args.control_port)
        print(f"Control page: http://{args.control_host}:{server.server_address[1]}/")
    out_handle = None
    no_sleep = args.fast or (args.dry_run and args.control_port is None)
    log = sys.stdout
    if args.dry_run:
        out_handle = open(args.out, "w") if args.out else sys.stdout
        publisher: Any = JsonlPublisher(out_handle)
        log = sys.stdout if args.out else sys.stderr  # keep stdout clean for the JSON lines
    else:
        publisher = MqttPublisher(os.getenv("MQTT_HOST", "localhost"), int(os.getenv("MQTT_PORT", "1883")))
        print(f"Publishing to pomona/{args.farm_id}/+/sensor/+/state every {args.interval}s (Ctrl+C to stop)")
    try:
        with open(args.truth_log, "w") as truth_handle:
            run(sim, publisher, truth_handle, ticks, None if no_sleep else sleep, log)
    except KeyboardInterrupt:
        print("\nStopped.", file=log)
    finally:
        if server:
            server.shutdown()
            server.server_close()
        publisher.close()
        if out_handle and out_handle is not sys.stdout:
            out_handle.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
