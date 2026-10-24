# Simulators

MQTT simulators for local development without hardware.

## Greenhouse tomato simulator

Publishes pH, EC, humidity, temperature, and soil moisture for a demo tomato greenhouse.

### Prerequisites

1. Start the stack: `make up` (from repo root)
2. Install deps: `make install-sim`

### Run

```bash
make sim
```

Or manually:

```bash
MQTT_HOST=localhost python3 examples/simulators/greenhouse_tomato.py
```

Environment variables (see `.env.example`):

| Variable | Default |
|----------|---------|
| `MQTT_HOST` | `localhost` |
| `MQTT_PORT` | `1883` |
| `SIM_FARM_ID` | `demo-farm` |
| `SIM_ZONE_ID` | `greenhouse-a` |
| `SIM_DEVICE_ID` | `sim-greenhouse-01` |
| `SIM_INTERVAL_SEC` | `5` |

### Verify

```bash
make health
make events
docker compose logs -f core
```

## Fake greenhouse (faults, events and a truth log)

`fake_greenhouse.py` is a deterministic, physically plausible greenhouse for testing how
Pomona handles broken sensors versus real problems. It runs two zones of farm `demo-farm`:
`greenhouse-a` (`fake-substrate-01`, `greenhouse_substrate`) and `greenhouse-b`
(`fake-hydro-01`, `hydroponic_greenhouse`). `greenhouse_tomato.py` is unchanged.

A hidden TRUE state advances each tick (diurnal temperature and humidity, substrate drying and
irrigation, EC and pH drift). A sensor layer adds noise and quantisation and applies faults.
Every reading attempt is written to a truth log saying what was true and what a correct system
should conclude. The truth log is never sent over MQTT.

### Run

```bash
make fake-greenhouse                      # demo scenario to MQTT at MQTT_HOST:MQTT_PORT (default localhost:1883)
python3 examples/simulators/fake_greenhouse.py --dry-run --ticks 20            # JSON events to stdout
python3 examples/simulators/fake_greenhouse.py --dry-run --out /tmp/e.jsonl \
  --scenario examples/simulators/scenarios/demo.json                           # no MQTT, no sleeping
services/core/.venv/bin/python -m pytest examples/simulators/tests -q          # tests
```

| Flag | Default | Meaning |
|------|---------|---------|
| `--seed` | scenario's, else 42 | Same seed + scenario + clock gives byte-identical output |
| `--interval` | 30 | Real seconds between publishes |
| `--sim-speed` | 1 | Simulated seconds per real second. 1 is real time; above 1 is an opt-in time-lapse (see below) |
| `--start-hour` | 8 | Simulated hour of day at tick 0 |
| `--scenario` | none | JSON timeline; without it the sim runs normal forever |
| `--ticks` | scenario's `duration_ticks`, else forever | Stop after N ticks |
| `--truth-log` | `data/fake_greenhouse/truth.jsonl` | Truth log path (gitignored, overwritten each run) |
| `--farm-id` | `demo-farm` | Farm id in payloads and topic |
| `--dry-run` | off | Print events as JSON lines (or to `--out PATH`); no MQTT, no sleeping |
| `--fast` | off | Publish to MQTT without sleeping between ticks |

**Time-lapse warning.** The default is real time: a 30 s tick is 30 s of greenhouse time, so
Pomona's per-sample checks (sensor_quality.py compares pH/EC with the first of the last 11
packets) and wall-clock debounces (automation `raise_after_seconds`, 600-1800 s) see realistic
data. With `--sim-speed` above 1 (e.g. 120, one tick = one simulated hour) those checks no longer
see realistic data: a real nutrient ramp looks like a baseline drift and a short event never
outlasts a debounce. Results from a time-lapse run are not meaningful for Pomona's own checks;
use it only to look at the physics (a full simulated day in 12 minutes).

Topic: `pomona/{farm_id}/{zone_id}/sensor/{device_id}/state`. Event timestamps are always the
real wall clock at publish time; the simulated time appears only in the truth log.

### Scenarios

JSON, scheduled by tick (not wall time) so replays are exact:

```json
{"seed": 7, "duration_ticks": 40, "steps": [
  {"at_tick": 10, "start": "jump", "zone": "greenhouse-b", "field": "ph", "params": {"offset": 1.5}},
  {"at_tick": 20, "stop": "jump", "zone": "greenhouse-b"}]}
```

- `scenarios/demo.json`: 420 ticks, about 3.5 hours at the default interval, every fault and
  event, realistic timing. Items in the same zone are at least 12 ticks apart so Pomona's
  11-sample history is clean again, and the real events last long enough to pass the 30 minute
  humidity and 10 minute default debounces.
- `scenarios/quick.json`: 56 ticks (about 28 minutes): a few sensor faults and one fast
  `heat_spike` (`ramp_min` 5). Quick, but less realistic than the demo.
- `scenarios/smoke.json`: 12 ticks, used by the tests.

### Sensor faults (the truth is unchanged, the reading is wrong)

| Name | Effect |
|------|--------|
| `stuck` | The field freezes at its last sent value |
| `drift` | Linear drift, `rate_per_min` per real (wall) minute (default EC 0.05, pH 0.02) |
| `jump` | Constant step offset, default pH +1.5 |
| `spike` | One absurd sample (default pH 13.0), then removes itself |
| `noisy` | Noise on the field times `factor` (default 10) |
| `dropout` | No packet is published for the zone while active |
| `dead_clock` | Timestamp `1970-01-01T00:00:00Z`; Core rejects it (`rejected_by_core`) |
| `plausible_offset` | Constant in-range EC +3.0 (`offset`); undetectable by Pomona today (`detectable: false`) |

### Real events (the truth changes, the reading is correct)

| Name | Effect (default ramp, wall minutes) | Expected label |
|------|--------|----------------|
| `heat_spike` | Air temperature ramps to about 33 C in 20 min (vent failure on a sunny day) | `heat_stress` once true air or substrate temperature >= 30 |
| `humid_night` | Humidity ramps to about 90 % in 20 min | `fungal_pressure` once true humidity >= 85 % or VPD < 0.4 kPa |
| `nutrient_over_concentration` | EC ramps to about 5.0 mS/cm in 60 min (dosing or top-up error) | `high_ec` once true EC >= 4.5 |
| `dry_zone` | Irrigation is blocked in the substrate zone; moisture falls about 70 %/h (`drying_pct_per_hour`), roughly 45 min from 60 % to under 10 % | `water_level_risk` once true moisture < 10 % |

Faults and events take `zone`, an optional `field` and `params`. Ramp events take `ramp_min`
(up) and `recover_min` (down after stop, default the same); ramps are wall minutes, independent
of `--sim-speed`. `dry_zone` drying is fast on purpose so a demo reaches the threshold; real
substrate takes many hours. The registry is `REGISTRY` in `fake_greenhouse.py`, and
`Simulation.start(name, zone_id, field, **params)` / `Simulation.stop(...)` toggle them.

### Truth log

One JSON line per reading attempt, including dropped and dead-clock ones: `tick`,
`wall_timestamp`, `sim_time` / `sim_day` / `sim_hour`, `zone_id`, `device_id`, `published`
(with `reason` when false), `sequence`, `true` (all true state, including reservoir water
temperature), `sent` (exactly the payload, or null), `active_faults`, `active_events`,
`placeholder_fields`, and `expect`:

- `kind`: `normal`, `sensor_fault`, `real_event`, `both`, `rejected_by_core` or `not_published`
- `expected_labels`: labels a correct system should raise for the TRUE state, computed from true
  values crossing Pomona's thresholds (constants mirror `services/model-router/app/tomato_reasoner.py`)
- `forbid_domain_cards_from`: fields whose sent values are wrong; expect a sensor check or
  "cannot confirm" instead of a domain card built on them
- `detectable`: false while `plausible_offset` is active
- `onset_step`: true for the first 11 samples of a `plausible_offset` started mid-stream. It is
  then a +3 step that Pomona can flag as baseline drift while its history still holds pre-fault
  readings; after that the history has absorbed it and it is undetectable. `detectable` stays false
  throughout; a run from the start of the stream has no step.
- `recovering_from`: names of sensor faults that stopped within the last 11 published samples on
  that zone. Pomona's history still holds the bad values, so a sensor check on such a `normal`
  frame is expected lingering, not a false alarm.

### Limits

- The physics is a simple model, not a validated crop model. Dry-zone drying is deliberately
  fast so a demo reaches the threshold, and the demo ramps are quicker than many real causes.
- Normal background is built for 30 s samples: irrigation pulses run in daylight every 30-90
  minutes, moisture refills abruptly, and the EC changes by at most 0.15 mS/cm per pulse.
- Air temperature and humidity are quantised at 0.01 (SHT3x class); substrate temperature (and the
  truth-only reservoir water temperature) at 0.0625 (DS18B20 class). Air temperature noise is
  0.1 C, so three equal readings in a row still happen by chance now and then and can trip
  Pomona's stuck-value check on a normal frame (roughly one frame in several hundred per zone).
  That is a property of the check, not hidden by the simulator.
- The hydroponic zone cannot send water temperature (Core's `SensorEvent` has no field for it) and
  sends a neutral `soil_moisture_pct` of 50.0 because Core requires one; the truth log marks it a
  placeholder and keeps the true water temperature.
- `expected_labels` covers only the four labels above. Derived labels such as
  `nutrient_uptake_issue`, and pH, cold-stress or low-EC labels, are not listed.
- `plausible_offset` is by design not detectable from a single reading.
- Sequence numbers count published events, so a dropout leaves no gap in `sequence`.
- `spike` is consumed by the sample it hits, even if a `dropout` is active at the same time.
