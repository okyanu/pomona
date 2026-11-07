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
| `MQTT_USERNAME` | empty (no login). `./scripts/sim.sh` and `make fake-greenhouse` read it from `.env` |
| `MQTT_PASSWORD` | empty. The Docker broker requires a login, so these two must match `.env` |
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

Short walkthrough, including grading Pomona against the truth log: [docs/FAKE_GREENHOUSE.md](../../docs/FAKE_GREENHOUSE.md).

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
| `--core-url` | off | POST events to this Core (REST, no broker) instead of MQTT; the truth log records `delivery`. Bearer key from `POMONA_API_KEY` or `API_KEY`. An error with `--dry-run` |
| `--fast` | off | Publish to MQTT without sleeping between ticks (an error with `--control-port`) |
| `--control-port` | off | Serve the control page and API on this port (0 = any free port) |
| `--control-host` | `127.0.0.1` | Control page bind address |

**Time-lapse warning.** The default is real time: a 30 s tick is 30 s of greenhouse time, so
Pomona's per-sample checks (sensor_quality.py compares pH/EC with the first of the last 11
packets) and wall-clock debounces (automation `raise_after_seconds`, 600-1800 s) see realistic
data. With `--sim-speed` above 1 (e.g. 120, one tick = one simulated hour) those checks no longer
see realistic data: a real nutrient ramp looks like a baseline drift and a short event never
outlasts a debounce. Results from a time-lapse run are not meaningful for Pomona's own checks;
use it only to look at the physics (a full simulated day in 12 minutes).

Topic: `pomona/{farm_id}/{zone_id}/sensor/{device_id}/state`. Event timestamps are always the
real wall clock at publish time; the simulated time appears only in the truth log.

### Control page

```bash
make fake-greenhouse        # demo scenario to MQTT, control page at http://127.0.0.1:8090/
make fake-greenhouse-dry    # no MQTT: events to data/fake_greenhouse/events.jsonl, control page at :8090
python3 examples/simulators/fake_greenhouse.py --dry-run --out /tmp/e.jsonl --control-port 8090
```

`--control-port` serves `control_page.html` (one self-contained page, no external files) plus a
small JSON API on a daemon thread; the tick loop stays in the main thread. The page shows the last
SENT reading per zone, the tick and the time to the next tick, and has a Start/Stop button for
every fault and event that applies to the zone (a field select for faults that take one, optional
JSON params). Top bar: **Hidden random** starts one random applicable fault or event that the page
shows only as "Hidden #n" with a Stop button; **Reveal hidden** (asks first) shows their real names
and ticks from then on; **Stop all**; and **Download session scenario**. Each zone card also has a
**Calibrate** button (see Calibration below).

The answer key stays hidden while running: the page and API never expose the true values or the
truth log's `expect`. Testers read the truth log after the run. The session download is the
exception: it contains the real names of hidden injections, so label it as answer key and keep it
away from testers until the run is over. Injections started by a loaded scenario are shown by name.

**There is no authentication. Keep `--control-host` on `127.0.0.1`; do not bind it wider.** POSTs
must be `Content-Type: application/json` (anything else is 415), so a page from another origin
cannot drive it without a CORS preflight, which is never answered, and foreign `Host` headers are
refused while bound to localhost.

With `--dry-run`, ticks sleep in real time when `--control-port` is given, so the page is usable
without a broker. Without it a dry run still skips sleeping.

| Endpoint | Purpose |
|----------|---------|
| `GET /` | The page |
| `GET /api/catalog` | Zones (system type, sensor fields) and every injection: name, kind, description, `takes_field` / `needs_field` / `default_field`, applicable zones (found by trying to build it per zone), default params |
| `GET /api/state` | `tick`, `interval`, `seconds_to_next_tick`, `queued`, `recorded`, `pending`, `revealed`; per zone the last sent reading (or null), `sequence`, whether the last tick `published`, and its running injections; a `hidden` list of `{"hidden": true, "id": n}` |
| `POST /api/start` | `{name, zone, field?, params?}` |
| `POST /api/stop` | `{name, zone, field?}`, or `{id}` for a hidden one |
| `POST /api/stop_all` | Stop everything, hidden included |
| `POST /api/hidden` | Start a random applicable injection from `random.Random(f"{seed}:hidden")`; returns its id |
| `POST /api/reveal` | Show hidden injections by name from now on; returns them |
| `GET /api/scenario` | The recorded session as scenario JSON (attachment). Contains the answer key |

Requests are validated when they arrive (a throwaway injection is built, bad requests get 400),
then queued and applied at the start of the next tick, after the scenario steps, so replays are
exact. Each applied command is recorded as a scenario step with `"source": "manual"` (or
`"hidden"`, under its real name). The download merges those with the original scenario steps and
the seed; replaying it with the same seed, `--interval`, `--sim-speed`, `--start-hour` and clock
gives a byte-identical truth log (`run` in the file lists them). Truth log injections carry
`source`: `scenario`, `manual` or `hidden`. A hidden injection never merges with a visible one of
the same name, and a button's Stop never stops a hidden one.

### Scenarios

JSON, scheduled by tick (not wall time) so replays are exact:

```json
{"seed": 7, "duration_ticks": 40, "steps": [
  {"at_tick": 10, "start": "jump", "zone": "greenhouse-b", "field": "ph", "params": {"offset": 1.5}},
  {"at_tick": 20, "stop": "jump", "zone": "greenhouse-b"}]}
```

- `scenarios/demo.json`: 460 ticks, about 3.8 hours at the default interval, every fault and
  event except `cold_night`, realistic timing, plus a `calibrate` of greenhouse-b EC after the nutrient ramp so the
  demo shows the full flow (can't confirm, calibrate, high_ec card). Items in the same zone are
  at least 12 ticks apart, and the real events last long enough to pass the 30 minute humidity
  and 10 minute default debounces.
- `scenarios/cold.json`: 440 ticks (about 3.7 hours): one `cold_night` per zone, 70 minutes each, to
  grade the `cold_stress_check` card on its own (the demo's verdicts stay as they were).
- `scenarios/quick.json`: 60 ticks (about 30 minutes): a few sensor faults and one fast `dry_zone`
  (400 %/h) that stays dry long enough for the 10 minute water-level debounce. Quick, but less
  realistic than the demo (a real EC ramp is too slow for a quick run: a fast one trips Pomona's
  baseline-drift veto).
- `scenarios/blind_spot.json`: 620 ticks (about 5.2 hours): the false-reassurance cases. A real event runs
  and, 3 minutes after it starts, the probe that would show it goes silent (`probe_dropout`): dry zone +
  moisture probe, heat spike + air temperature probe (both zones), nutrient over-concentration + EC probe
  (both zones), humid night + humidity probe, and one control (heat spike + the optional substrate
  temperature probe, while the air probe still shows the heat). The scorer grades each under "Blind spots"
  (see [FAKE_GREENHOUSE.md](../../docs/FAKE_GREENHOUSE.md#blind-spots-a-real-fault-and-a-silent-probe)).
- `scenarios/validation.json`: 15 ticks at `--interval 1`, used by `make local-validation`.
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
| `probe_dropout` | One probe goes silent: its field is absent from every packet (the key is missing, not null; soil moisture drops both of its names). Nothing wrong is sent, so there is no recovery tail. Core accepts the partial packet (a probe that did not report is absent or `null`; only a packet with no reading at all is refused), so Pomona sees the missing reading and says "can't confirm". The truth log's `expect` then has `silent_fields`. Not picked by "Hidden random" |

### Real events (the truth changes, the reading is correct)

| Name | Effect (default ramp, wall minutes) | Expected label |
|------|--------|----------------|
| `heat_spike` | Air temperature ramps to about 33 C in 20 min (vent failure on a sunny day) | `heat_stress` once true air or substrate temperature >= 30 (card: `heat_stress_check`) |
| `cold_night` | Air temperature ramps down to about 13 C in 30 min (heating failure on a cold night) | `cold_stress` once true air or substrate temperature <= 16 (card: `cold_stress_check`) |
| `humid_night` | Humidity ramps to about 90 % in 20 min | `fungal_pressure` once true humidity >= 85 % or VPD < 0.4 kPa |
| `nutrient_over_concentration` | EC ramps to about 5.0 mS/cm in 60 min (dosing or top-up error) | `high_ec` once true EC >= 4.5 |
| `dry_zone` | Irrigation is blocked in the substrate zone; moisture falls about 70 %/h (`drying_pct_per_hour`), roughly 45 min from 60 % to under 10 % | `water_level_risk` once true moisture < 10 % |

Faults and events take `zone`, an optional `field` and `params`. Ramp events take `ramp_min`
(up) and `recover_min` (down after stop, default the same); ramps are wall minutes, independent
of `--sim-speed`. `dry_zone` drying is fast on purpose so a demo reaches the threshold; real
substrate takes many hours. The registry is `REGISTRY` in `fake_greenhouse.py`, and
`Simulation.start(name, zone_id, field, **params)` / `Simulation.stop(...)` toggle them.

### Calibration (a meter confirms a probe)

A calibration is not a fault or an event: the truth does not change. It says that a person checked
a probe with a meter, which makes Pomona accept the probe's current level as the new normal (Core
keeps a trusted reference per probe, and a calibration resets it). Without one, a probe whose level
really changed (a nutrient overdose) stays flagged "can't confirm". Add a scenario step
`{"at_tick": 395, "calibrate": "ec_ms_cm", "zone": "greenhouse-b"}`, or press **Calibrate** on the
control page (recorded as a manual step in the session download). Probes: `ph`, `ec_ms_cm`,
`air_temperature_c`, `humidity_pct`, `soil_moisture_pct` (substrate zone only; there is no
calibration for substrate temperature). The truth line of that tick carries
`calibrations: [{field, at, source}]`; with `--core-url` the simulator also posts a CalibrationEvent
(method `fake_greenhouse_confirm`, timestamp = that tick's wall time) to Core before the tick's
reading and records `delivery` in the entry.

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

With `--core-url` each truth line also has `delivery`: `{"status": 201}` for what Core answered
(422 for a dead clock), or the error status and message.

### Scoring Pomona

`scripts/score_fake_greenhouse.py --truth PATH` grades the alerts Pomona raised against the truth
log: `--automation-url URL [--core-url URL]` reads a running stack, `--offline` replays the
Core-accepted events through the real pipeline and alert monitor in-process (model-router venv).
`--json PATH` writes the full report (with metric definitions), `--report PATH` a markdown
timeline of episodes next to Pomona's cards, `--fail-on-miss` exits 1 on a missed real episode or a
wrong card. `make fake-greenhouse-score` runs a no-Docker stack and scores it both ways; see
[docs/FAKE_GREENHOUSE.md](../../docs/FAKE_GREENHOUSE.md).

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
- `expected_labels` covers only the five labels above (heat, cold, fungal, high EC, water level). Derived
  labels such as `nutrient_uptake_issue`, and pH or low-EC labels, are not listed.
- `plausible_offset` is by design not detectable from a single reading.
- Sequence numbers count published events, so a dropout leaves no gap in `sequence`.
- The control page has no auth and only a Host-header guard; it is a local test tool.
- A hidden injection shows up after the next tick, not at the click; `queued` counts it meanwhile.
- A `--scenario` run (and so the control page) ends at the scenario's `duration_ticks`.
- `spike` is consumed by the sample it hits, even if a `dropout` is active at the same time.
