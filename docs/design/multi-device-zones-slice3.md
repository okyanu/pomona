# Multi-device zones, slice 3: the simulator, scorer and game speak devices

Status: **approved by the owner 2026-11-15** ("Yes, as recommended": open questions 1-5 answered as recommended; see
"Decisions"). Draft v3 (2026-11-15). The build needs its own owner go, after the abstention eval is merged (Build
order, step 0).
- v1 was reviewed by two context-free reviewers (gaps; fit with the code). Both said READY WITH FIXES.
- v2 applied every fix and was re-reviewed by a third context-free reviewer: READY WITH FIXES, no Rule-0 conflict.
- v3 applies those fixes (lists at the end).

Parent: `docs/design/multi-device-zones.md`. Its "Slice 3 (outline" section lists what this slice must answer; each
answer is marked **(S-n)** (list at the end).
Built on: slice 1 (merged 9c90800) and slice 2 (merged c9fab40, `docs/design/multi-device-zones-slice2.md`).
Lands after: the abstention eval set (`docs/design/abstention-eval-set.md`, branch `abstention-eval`), see 3.10.
Unblocks: `docs/design/slow-drift-pair-check.md` (v2). Section 3.9 says what it gets from this slice.

## Goal

Slices 1 and 2 made Core, the router, the alert monitor and the dashboard handle a zone with several devices. Nothing
can **produce** such a zone yet:

- the fake greenhouse gives every zone exactly one device (`ZoneConfig.device_id`), so the dashboard's zone views
  (slice 2) cannot be seen without hand-made packets;
- the scorer joins everything on (zone, sample time) and would mix two devices that report at the same tick;
- the in-process engine does not send the alert `detail` line that Core's feed sends in a multi-device zone;
- the slow-drift pair check needs two probes of one field in one zone, a truth label saying which probe drifted, and a
  scorer that can say whether the card landed on the drifted probe.

Slice 3 lets a scenario give a zone several devices, each with its own probes and its own faults, and makes the truth
log, the scorer and the in-process engine key everything by device.

**Rule 0: everything that runs today stays byte-identical.** A scenario without the new `devices` key, every existing
scenario, seeds 1-80, the abstention eval files, the replays, the parity drivers and the game produce the same bytes as
before (3.11 says how that is proven). New keys appear only in rows, reports and responses of multi-device zones.

## How the user meets it

1. The owner runs `SCENARIO=examples/simulators/scenarios/multi_device.json make fake-greenhouse` against the stack.
   Zone A now has two devices, `climate-1` (air, humidity) and `substrate-1` (pH, EC, moisture, substrate temperature).
   Zone B stays one device.
2. **Dashboard:** zone A's tiles show values from both devices with their source line (`climate-1 · 20 s`), the
   trends draw one line per device, and the trust line counts `(2 devices)`. This is slice 2's zone view, now fed by
   the simulator.
3. **Control page:** a zone with several devices lists each device under the zone (id, sensors, last packet). A fault
   row gets a device selector next to the field selector; it lists the devices that carry the chosen field. Events
   (heat spike, dry zone) have no device selector: they change the zone's truth, which every device sees.
4. The owner presses "Stuck sensor" on `climate-1` humidity. Only `climate-1`'s packets freeze. Its own history flags
   it (slice 1), the dashboard says `humidity (climate-1) not used`, and a `sensor_check` card is raised for
   `climate-1` with its check text in the `detail` line (slice 2).
5. **Scorer report:** in a multi-device zone the timeline's Zone column says `greenhouse-a · climate-1` for sensor
   faults and false alarms, and a real event names the device that raised its card. Single-device zones look as
   today.
6. **Pair zone:** `scenarios/slow_drift.json` gives zone A two climate devices and two moisture probes. Its slow
   drifts are scored **MISSED** today, honestly. They are the "before" picture the pair check must turn into
   "caught".
7. **The game** looks and plays exactly as today, and its code does not change (open question 2).

## Build order

0. **The abstention eval set is merged into `main`** (3.10). Check: `git log main` shows its merge commit, and
   `examples/simulators/sim_helpers.py` and `make abstention-eval-regen` exist on `main`. Until then nothing below
   starts, not even the baselines.
1. **Baselines** (3.11), from a clean worktree of that `main` commit.
2. One owner OK, three coder briefs, each with its own tests and review:
   - **3a, simulator and truth log (3.1-3.3, 3.7 scenario files).** Devices in `fake_greenhouse.py`, the control
     page, `/api/catalog` and `/api/state`, the two scenarios.
   - **3b, scorer (3.5).** `score_fake_greenhouse.py` keyed by device. It is the largest piece, so it has its own
     brief.
   - **3c, engine, checks and docs (3.4, 3.7 checks, 3.8, 3.12 docs).** The engine's `detail`, the
     `multi_device.json` comparison, the `slow_drift.json` run, the sweeps, the stack run with screenshots, the docs
     and the drift log.
   - If the budget runs short, the control page's device UI and the hidden-random device draw (3.1, 3.3) can move to
     a follow-up: nothing in 3.7-3.9 needs them. The API keys stay.

## Design

### 3.1 Simulator: devices in a zone (S-1)

**Where the devices come from.** A scenario may carry a top-level `devices` key:

```json
"devices": {
  "greenhouse-a": [
    {"device_id": "climate-1", "sensors": ["air_temperature_c", "humidity_pct"]},
    {"device_id": "substrate-1", "sensors": ["ec_ms_cm", "ph", "soil_moisture_pct", "substrate_temperature_c"]}
  ]
}
```

- A zone not named in `devices` (and every zone when the key is absent) has one device: the `ZoneConfig`'s
  `device_id` with all of its `sensors`. That is today's zone, byte for byte.
- `Simulation(..., scenario=...)` reads the key; `zones=` stays as it is. The CLI needs no new flag.
- `session_scenario()` adds `devices` **only when the scenario had the key**, so the game's `export()` and every
  existing saved scenario keep their bytes.

**Validation.** When the scenario has a `devices` key, it is checked in `Simulation.__init__`, before the first tick,
with a `ValueError` naming the problem (`load_scenario` keeps checking only what it checks today):

- shape: `devices` is an object of lists of objects; each device object has `device_id` and `sensors`, may have
  `offsets` and `wander`, and any other key (a typo such as `offset`) is refused;
- the zone exists; the list is not empty; at most 8 devices per zone (the dashboard's trend card plots at most 8 device lines);
- `device_id` matches `^[A-Za-z0-9_-][A-Za-z0-9._-]{0,63}$` (an MQTT topic segment: no `/`, `+`, `#`, and not `.`
  or `..`) and is unique within the zone;
- `sensors` is not empty, and each entry is one of the zone's `ZoneConfig.sensors`, or `substrate_moisture_pct` when
  the zone has `soil_moisture_pct` (see "Moisture names"); no probe twice in one device after `canonical()`;
- together, the zone's devices carry every field of its `ZoneConfig.sensors`. A zone without, say, an EC probe would
  still get `high_ec` in its truth, which no device could show;
- `offsets` and `wander` (below) are keyed by canonical names (`soil_moisture_pct`, never `substrate_moisture_pct`),
  name only probes the device carries, and hold finite numbers; `wander` values are ≥ 0;
- a zone listed with **one** device may not use `offsets`, `wander` or the alias-only `substrate_moisture_pct`: its
  rows carry no `sensors` or `device_offset` (3.2), so the difference would leave no trace in the truth log;
- **steps on the zones the layout lists** are checked against it: a step's `device` exists in the zone, a field
  fault's field (a `null` field counts as absent) is carried by that device (or, without `device`, by some device of
  the zone), and events carry no `device`.
- **Everything else keeps today's late failure:** a scenario without `devices`, and steps on zones the layout does
  not list, are checked only when their tick runs, as today (a step past `duration_ticks` never fails).
- **`device` on a one-device zone:** accepted when it equals the zone's only device id, refused otherwise (in a step
  and on the control page alike).

**Device state.** A new `Device` class holds what is per probe today:

| Today on `Zone` | Slice 3 |
|---|---|
| `boot_id`, `sequence`, `last_sent` | on `Device`. `boot_id` keeps its formula (`sha1("fake-greenhouse:{seed}:{device_id}")`), so the default device's id is unchanged |
| `faults`, `recovery`, `calibrations` | on `Device`: a fault is on one device, and its recovery tail counts that device's published packets |
| truth state, `events`, `truth_rng`, `sensor_rng` | stay on `Zone` |

**`Zone` keeps every attribute that code outside `fake_greenhouse.py` reads**, as read-only properties, for single-
and multi-device zones alike. The game (`zone.cfg`, `zone.placeholder_fields`, `zone.calibratable`) and the
abstention eval (`sim_zone.faults`) read them, and neither changes in slice 3:

- `cfg`, `events`: as today;
- `devices`: the list in scenario order (new);
- `faults`: every device's faults, in device order (for a one-device zone, exactly today's list);
- `placeholder_fields`: as today for a one-device zone; `[]` for a multi-device zone (see "Packets");
- `calibratable`: the probes of `CALIBRATABLE` that some device carries, in `CALIBRATABLE` order;
- `silent_fields()`: the union over devices;
- `boot_id`, `sequence`, `last_sent`, `recovery`, `calibrations`: the first device's (only meaningful for a one-device
  zone; code inside `fake_greenhouse.py` uses the devices directly).

**Readings: noise without shifting any draw.**

- The zone keeps its `sensor_rng` (`f"{seed}:{zone_id}:sensor"`) and, as today, draws one Gaussian for every field of
  `SENSOR_ORDER` on every tick.
- **The first device in the list that carries a field uses the zone's draw for it.** So a zone split into devices
  with disjoint probes sends exactly the values the one-device zone sends, field by field (this makes the
  `multi_device.json` check in 3.7 exact).
- **A later device carrying the same field** (a pair partner) uses its own draw. Every device after the first has its
  own `random.Random(f"{seed}:{zone_id}:{device_id}:sensor")` and draws one Gaussian for every field of
  `SENSOR_ORDER` on every tick, whatever it carries, so starting a fault never shifts a draw.
- **Per device and field, the value is computed as today with the zone's true value replaced by the probe's own:**
  `probe_true = true[field] + offset + wander` (both 0 by default), then noise (`sigma` times the faults'
  `noise_factor`), `quantise`, each fault's `apply` with the device's own `last_sent`, `quantise` again. `quantise`
  also clamps to `LIMITS`, as today.

**Partner realism: `offsets` and `wander`** (optional per device, both default to none; open question 5):

- `offsets: {field: number}`: a constant added to the probe's true value: where the probe hangs.
- `wander: {field: bound}`: a slow walk of its own. Each listed field starts at 0 and takes one `ou()` step per tick
  from tick 1 on (tick 0 has no step and draws nothing, like `Zone.advance`), with rate 0.5 per hour and sigma `0.4 × bound` per
  square-root hour. Its spread is then about `bound / 2.5`, and it is clipped to ±`bound`, which it rarely reaches
  (the same proportions as the existing `air_walk`). The draws come from
  `random.Random(f"{seed}:{zone_id}:{device_id}:wander")`, one per listed field per tick, in `SENSOR_ORDER` order.
- Why: two probes with identical truth make the pair check's normal-seed sweep a weak test (pair-check doc, stage 2
  "Docs"). With a wander, the difference between two probes moves a little, as in the real data (UF chamber, AGC2).
- Offsets and wander are facts about the probe, not faults: the truth row's `true` stays the zone's truth, and
  `expected_labels` is computed from it. The scenarios in 3.7 keep offset plus wander within 0.7 °C, 2.5 %RH and
  1.8 % moisture.

**Moisture names.** Today's substrate device sends the moisture probe under both names (`soil_moisture_pct` and
`substrate_moisture_pct`). A device listing `soil_moisture_pct` keeps doing that. A device listing
`substrate_moisture_pct` sends that name only, which gives the pair check its alias case. Internally the probe is
`soil_moisture_pct` (`canonical()`): faults, calibrations, offsets, the truth row's `sensors`, and the `sensors` lists
in `/api/catalog` and `/api/state` use that name, so the control page's "devices carrying this field" filter finds
`substrate-2`. Only the packet uses the alias name.

**Packets** (`build_event`, per device):

- reading fields: the device's own, after faults; a probe dropout removes the field as today;
- `device_id`, `boot_id`, `sequence`: the device's;
- context: every device of the zone sends the same `crop`, `growth_stage`, `system_type`, and in a substrate zone the
  same `zone_context()`. So slice 2's context rule finds no conflict;
- `source`, `schema_version`, `timestamp`: as today. All devices of a zone use the tick's timestamp; per-device rates
  and phases are out of scope;
- **the hydroponic moisture placeholder** (`PLACEHOLDER_MOISTURE_PCT`): substrate zones never send it (as today). A
  hydroponic zone sends it only when it has one device. A multi-device hydroponic zone sends none, and its truth rows
  say `placeholder_fields: []`. Core no longer needs a moisture field in every packet (partial packets, silent-probe
  build);
- MQTT topic: `pomona/{farm}/{zone}/sensor/{device_id}/state` (already per device).

**Order.** `step()` returns one `Reading` per device per tick: zones in config order, devices in list order. The
publishers and the truth log take them in that order. A one-device zone gives one `Reading` per tick, as today.

**Faults, events, calibrations and commands take a device** (S-1):

- **Injections know their device:** `Injection` gains a `device_id` attribute set at construction. `describe()` is
  unchanged, so the truth row's `active_faults` entries gain no `device` key (the row's own `device_id` says it).
  Catalog descriptions stay as they are (Rule 0), although `dropout`'s text says "zone".
- **Signatures.** `start`, `stop`, `calibrate`, `validate_start`, `queue_start`, `queue_stop` and `queue_calibrate`
  gain `device: Optional[str] = None` as a **keyword-only argument, last**. Every existing positional call (the game,
  `_apply_commands`, the tests) keeps working.
- Scenario steps and the control endpoints accept an optional `"device"`.
- **Field faults** (stuck, drift, jump, spike, noisy, probe_dropout, plausible_offset): without `device`, the first
  device in the list that carries the field (the fault's `default_field` when no field is given). With `device`,
  that device must carry it.
- **Whole-device faults** (dropout, dead_clock): without `device`, the zone's first device.
- **Events** reject a `device` key: they change the zone's truth.
- **Restart instead of duplicate:** `start` today returns an already running injection with the same
  `(name, field, hidden)`; the key becomes `(device, name, field, hidden)`, so stuck humidity on `climate-1` and on
  `climate-2` are two faults.
- **Stop** without `device` stops every matching injection in the zone (today's meaning); with `device`, only that
  device's.
- **`stop_all` and `stop_hidden`** stop each running injection on its own device, and the recorded stop step carries
  that `device` when the zone has more than one device. Recorded steps in a one-device zone never carry `device`.
- **Calibrate** without `device`: the first device carrying the field. The calibration rides on that device's truth
  row and is posted to Core with that `device_id` (already done by `run()` and `CorePublisher.calibrate`). Its
  `reference` is the **probe's own true value** (`probe_true` above): a meter held next to that probe reads what is
  there, so the raw reading and the reference differ only by noise, as today.
- **Recorded manual steps** (`_record`) carry `device` when the zone has more than one device, including the device a
  hidden start drew. In a one-device zone they never do.
- **Hidden random** (`queue_hidden`):
  1. **A simulation with no multi-device zone runs today's algorithm, draw for draw.**
  2. **With a multi-device zone,** candidates are `(name, zone, device)` triples: for every hideable injection and
     every zone it applies to, each device of that zone that can take it (carries the fault's `default_field`, or any
     field for a fault that needs one; every device for dropout and dead_clock). One-device zones give one triple per
     pair. `taken` (running and queued hidden injections) is keyed by the same triple. One `hidden_rng.choice` picks a
     triple; a fault that needs a field then draws it among **that device's** sensors (one draw, as today). No other
     draw.
  3. When no triple is left, `ValueError("every applicable injection is already running hidden")`, as today.
  4. `hidden_log` entries, `reveal()` and the revealed `/api/state` hidden entries gain `device` only for a
     multi-device zone.
  - `applicable_zones` is unchanged (a zone qualifies when some device can take the fault).

### 3.2 Truth log: one row per device per tick (S-1)

- One row per `Reading`: per device per tick. In a one-device zone the row is today's row, byte for byte, in every log
  (also in a log whose other zone is multi-device).
- `true`, `sim_*`, `wall_timestamp`, `active_events` and `expect.expected_labels` are the zone's and repeat on every
  device row of the tick.
- `device_id`, `published`, `reason`, `sequence`, `sent`, `active_faults`, `placeholder_fields`, `calibrations`,
  `expect.kind`, `expect.forbid_domain_cards_from`, `expect.detectable`, `expect.onset_step`,
  `expect.recovering_from` and `expect.silent_fields` are the device's. `kind` uses the device's faults and the zone's
  events (`both`, `sensor_fault`, `real_event`, `normal`, ...).
- **Rows of multi-device zones only** gain, after all of today's keys:
  - `sensors` (row level, after `placeholder_fields`): the device's probes, canonical names, in `SENSOR_ORDER` order.
    The scorer needs them when a packet is missing;
  - `device_offset` (row level, after `sensors`): `{field: offset + this tick's wander}`, rounded to 4 places like
    `true`, only for a device with `offsets` or `wander`;
  - `expect.device_labels` (after `expect.recovering_from`, before the conditional `silent_fields`): the labels of the
    true state that this device's own probes could show, `expected_labels(true, fields=sensors)`.
- **`expected_labels(true, fields=None)`.** Without `fields`, today's result. With a set of canonical names, a label
  counts only through fields in the set: heat or cold through `air_temperature_c` or `substrate_temperature_c`;
  fungal pressure through humidity ≥ 85 (needs `humidity_pct`) or low VPD (needs both air and humidity); `high_ec`
  through `ec_ms_cm`; `water_level_risk` through `soil_moisture_pct`, which reads the truth's
  `substrate_moisture_pct` value (the same number). A device whose probes can show none of the labels gets `[]`.
- **Which probe drifted** is plain in the log: the fault is listed on the device row that carries it, and only there.

### 3.3 Control page and `/api/state` (S-1)

- `/api/catalog` zones keep their keys (`device_id` is the first device, `sensors` the zone's) and gain
  `devices: [{device_id, sensors, calibratable}]` only for a zone with more than one device.
- `/api/state` zones keep their keys, describing the first device (`device_id`, `sequence`, `published`,
  `last_sent`), and gain `devices: [{device_id, sequence, published, last_sent, injections}]` only for a multi-device
  zone. The zone-level `injections` then lists the zone's events plus every device's faults, each fault with a
  `device` key. `pending` entries gain `device` when the command named one.
- `/api/start`, `/api/stop` and `/api/calibrate` accept `device`. **The 400 comes from `queue_start` /
  `queue_calibrate`, which check that the device exists and carries the field**: `_apply_commands` swallows a
  `ValueError` at apply time, so the check cannot wait until then.
- `control_page.html`: when `zone.devices` exists, the panel lists the devices with their sensors and last values,
  fault rows get a device selector (filtered to devices carrying the selected field), and the calibrate row gets one
  too. Without `devices` the page takes today's code path.
- `summary_line` (the CLI log) adds ` device=<id>` only for rows of multi-device zones.

### 3.4 In-process engine (S-3)

Slice 1 already made `inprocess_pomona.py` per device (history, trusted reference, device fields, alert stream). One
gap is left: **Core's feed sends the alert `detail` line in a multi-device zone (slice 2, 2.6); the engine does not.**

- **Where:** the engine's one `self.monitor.observe(...)` call, which runs after the pipeline result is final (on
  `main` today and after the abstention refactor alike). The `capture` contract (the pipeline input) is untouched.
- When `device_fields` is not `None` (a multi-device zone), that call passes `detail=alert_detail(result)` (left out
  when empty) and `data_quality_labels=` the reading's `sensor_quality.data_quality_labels`. Core's feed passes the
  labels on every reading (`outcome_feed._process`), but the monitor uses them only together with a `detail`, so
  passing them only in multi-device zones gives the same alerts and keeps the single-device call exactly as today.
- `alert_detail` is copied into the engine from `services/core/app/outcome_feed.py` (the engine cannot import Core's
  package next to the router's, the same reason `pipeline_risk_labels` is copied). The test that pins the copy to the
  original runs in the Core venv, in `services/core/tests/` (as `test_multi_device_feed.py` already imports both
  `inprocess_pomona` and `app.outcome_feed`).
- In a single-device zone the monitor call is exactly today's, so its events and states are unchanged.
- In a multi-device zone the monitor's events and states now carry `detail` for sensor alerts. The abstention eval
  reads the pipeline input and result, not alert events, so its files do not change (checked by its regen gate,
  3.11).
- **No zone view in the engine** (open question 1). It judges each device's packets as Core's feed does.
- **Order of readings:** callers feed devices in the simulator's order. `score_fake_greenhouse.replay_offline` sorts
  rows by `(tick, zone_id)` with Python's stable sort, which keeps the truth log's device order. The key must not add
  `device_id`: an alphabetical order would differ from the order the stack stores packets in.

### 3.5 Scorer: every join keyed by device (S-2)

`scripts/score_fake_greenhouse.py`.

**Streams and the single-stream rule.**

- A **stream** is (zone, device), with device `row.get("device_id")`.
- A zone is **multi-device** when its rows carry more than one distinct device id. Otherwise it is a
  **single-stream zone**.
- **In a single-stream zone the device is ignored in every join**, exactly as today. That keeps the existing callers
  and tests working unchanged: the scorer tests' events without `device_id`, the game's rows without `device_id`,
  the parity driver, the stack mock's stored events without `device_id`, and `frame_info` keys of the form
  `(zone, tick)`.
- In a multi-device zone, joins use the device. An alert event, a stored Core event or a `frame_info` key without a
  device, in a multi-device zone, is unmatched (events) or an error (a 2-tuple `frame_info` key raises `ValueError`).
- New report keys appear only when the log has a multi-device zone, and only on that zone's items (like the blind-spot
  keys today). Zone B's episodes in a mixed log keep today's keys and text.

**The Grader's two frame structures:**

- `self.streams[(zone, device)]`: the frames of one stream, by tick. Used by the stream-level questions:
  `run_began_by`, `find_check_during`, `open_sensor_card`, `_grade_fault` (fault runs, `sensor_check_frames`),
  `silent_runs`, `silent_since`, `flagged_reading`, `reading_level`, `core_check`.
- `self.zones[zone]`: the zone timeline (below). Used by the zone-level questions: `real_episodes`, `event_windows`,
  `silent_probe_blocked`, `field_vetoed` (all streams of the zone), the `by_sample` lookup of a single-stream zone.
- In a single-stream zone both are today's flat frame list, so every method sees exactly what it sees today.
- `self.raises` sorts by `(time, rule, device)` (device `""` when absent), so two devices raising one rule at one
  sample time have a fixed order; in a single-stream zone that is today's order.

**Frames and joins:**

- `build_frames` builds both structures; `Frame` gains `device`.
- `by_sample`: `(zone, device, sample)` in multi-device zones, `(zone, sample)` in single-stream zones.
- `frame_info`: `replay_offline` writes `(zone, device, tick)` keys for multi-device zones and `(zone, tick)` for
  single-stream zones. The Grader reads both forms by the same rule.
- Each raise records its `device` (and `detail` when the event has one). A recovery closes the open incident of the
  same zone, device and rule.
- **Zone timeline:** for each zone and tick, the list of that tick's device frames. Truth, events and
  `expected_labels` are read from the first frame in the list (all device rows of a tick agree on them). For a
  single-stream zone the timeline is that device's frames.

**Real events (zone level):**

- Episodes come from the zone timeline, as today.
- **A card on any device of the zone counts** (`find_raise` over the zone's streams). `raised` gains `device` in a
  multi-device zone.
- `field_vetoed`: a vetoed field on any stream of the zone, in the window (every `frame_info` entry of the zone).
- `caught_cant_confirm` in a multi-device zone needs the sensor card on a device that carries one of the label's
  fields (`LABEL_FIELDS`, through the rows' `sensors`).
- `silent_probe_blocked`: a tick counts as "reporting the field" when some device frame of that tick is accepted,
  carries one of the label's fields (`sensors`), and has no `probe_dropout` on it. The episode is a blind spot when the
  reporting ticks span less than `raise_after`, as today.

**Sensor faults (stream level):**

- Fault episodes are found per stream: a fault on `climate-1` is `climate-1`'s episode. In a multi-device zone the
  episode gains `device` and `partners` (the other devices of the zone whose `sensors` hold the fault's field).
- `run_began_by` counts the readings of the raise's own stream (the monitor counts `raise_after_samples` per stream).
- `sensor_check_frames` and `flagged_active` read the episode's own stream in `frame_info`.
- **A sensor card counts on the faulted device** (`find_check_during` and `open_sensor_card` on the episode's stream).
- **New outcome `caught_on_partner`** (multi-device zones only; open question 3): no sensor card on the faulted device
  while the fault ran, but a sensor-family card **raised** on one of its `partners` inside the episode window whose
  label run began no later than the fault's last reading (the same `run_began_by` test on the partner's stream). An
  already open card on a partner does not count.
  - **Offline, the card must be about the fault's field:** some partner reading in that label run has the field (or
    its alias) in `vetoed_fields`, or the field's missing label (`MISSING_LABEL`), in `frame_info`. A chance card on
    the healthy probe for another field is not a catch.
  - **Stack mode** has no per-reading results, so this check is skipped there and any sensor-family card on a partner
    counts; the report says so in `metric_definitions`.
- **Precedence**, first match wins: `undetectable` (plausible_offset), `wrong_card`, `caught`, `caught_on_partner`,
  `caught_at_recovery`, `too_short_to_raise`, `missed`.
- `caught_on_partner` episodes count in `sensor_fault_episodes.total` and in their own entry
  `sensor_check_caught_on_partner`, never in `sensor_check_caught` or `missed`. `--fail-on-miss` does not fail on
  them. The markdown verdict reads "caught on the partner probe (the card asks to check both)".
- **Wrong card:** a domain card built on the faulted field, raised on the **faulted device**, as today. A domain card
  on a healthy partner is judged by the false-alarm rule below.

**False alarms:**

- A real event exempts raises on every device of its zone, as today.
- A fault episode exempts every raise of its own device, and sensor-family raises on its partners. In a single-stream
  zone that is today's rule (the device is the zone).
- A silent run exempts raises on its own device, as today.
- So in a multi-device zone, a card on an unrelated device during a fault is a false alarm unless something else
  explains it. Today a fault anywhere in the zone hid it.

**Blind spots:** silent runs are per (zone, device, field). The event's card on any device of the zone counts as
"alerted" (another probe still showed it). The sensor card, `flagged_reading` and `silent_since` use the silent
device's own stream.

**Reading level (offline):** counts per device frame. In a multi-device zone, `normal_with_card` and `wrong_cards`
compare against `expect.device_labels` instead of `expected_labels`, so a climate device is not blamed for not
raising `high_ec`.

**Stack mode:** `fetch_alerts` is unchanged (alert items and events carry `device_id`). `fetch_core_events` keeps
each stored event's `device_id` when present, and `core_check` compares per stream in multi-device zones and per zone
otherwise.

**Report (multi-device logs only):**

- `metric_definitions` gains `stream`, `partners`, `caught_on_partner` and `device_labels`;
- `summary.sensor_fault_episodes` gains `sensor_check_caught_on_partner`;
- `summary.multi_device: {"zones": {zone: [device, ...]}}`;
- markdown: the Zone column reads `zone · device` for fault episodes and false alarms of multi-device zones, a real
  event's "Pomona raised" names the device, and the summary adds "caught on the partner probe N";
- `print_summary` adds one line.

### 3.6 Game and the Space (S-4)

- **The game's zones stay one device each**, and `game.py` does not change. By the single-stream rule (3.5) the
  Grader reads its rows without `device_id` and its `(zone, tick)` `frame_info` as today (open question 2).
- `spaces/try-to-fool-pomona/tests/` (`parity_driver.py`, `test_engine.py`) do not change for the same reason.
- **Vendored copies:** `make fool-space-check` rebuilds `vendor/` and `pomona.zip` locally (gitignored, slice 1 drift
  note 4). `fake_greenhouse.py`, `inprocess_pomona.py` and `score_fake_greenhouse.py` gain no import outside the
  vendored file list, so `scripts/build_fool_space.py` keeps its list.
- **Parity:** `make fool-space-check` passes with the same test count, `make fool-space-pyodide-check` says
  `PARITY OK` with the same cases, and recorded game sessions export the same bytes (3.11).
- **No re-upload.** The live Space copy is already stale for other reasons; refreshing it is a separate owner item.

### 3.7 Scenarios (S-5)

**`scenarios/multi_device.json`: `demo.json` with zone A on two devices.**

- `seed`, `duration_ticks` and every step of `demo.json`, unchanged. Zone A's steps need no `device` (each fault's field
  has one owner: pH and EC on `substrate-1`, air on `climate-1`).
- `devices`: zone A = `climate-1` (air, humidity), then `substrate-1` (EC, pH, `soil_moisture_pct`, substrate
  temperature). Zone B is not listed.
- **The rule for matching its verdicts to `demo.json`** (S-5):
  1. **Inputs, exact:** for every tick, zone A's true state is equal, and the union of the two devices' reading fields
     equals `demo.json`'s zone A packet, value for value (the first-carrier rule in 3.1). Context and sequence are
     equal; `device_id` and `boot_id` differ. Zone B's rows are byte-identical.
  2. **Episodes:** the same real episodes (zone, label, start and end tick) and the same fault episodes (fault, field,
     ticks), with the same outcome each. Fault episodes now name their device.
  3. **Delays:** equal, except `heat_stress_check` and `cold_stress_check`, which read air on one device and
     substrate temperature on the other. Their first raise across the zone may come later than `demo.json`'s, never
     earlier. A delay that differs because the automation engine keeps one alert card per device (a card no longer shared
     across the zone's devices) is expected (owner decision 7).
  4. **False alarms:** 0 in both.
  5. **Not compared:** reading-level counts (zone A has two frames per tick, and the zone's very first packet is
     judged before the second device exists, slice 1 drift item 11).
  6. **Any other difference:** the builder traces it to its cause. If the cause is a named check that reads fields
     the split put on two devices (for example a sensor-quality check that compares air with substrate temperature),
     the builder records it in the drift log and continues; the owner sees it in the review. Any difference without
     such a cause is a bug and is fixed before the build is reported done.

**`scenarios/slow_drift.json`: the pair zone** (open question 4).

- `seed` 23, `duration_ticks` 1000 (8 h 20 min at 30 s; the simulator's default start hour 8, so tick 240 is 10:00).
- Zone A devices:
  - `substrate-1`: EC, pH, `soil_moisture_pct`, substrate temperature;
  - `substrate-2`: `substrate_moisture_pct` only (the alias case), `offsets {soil_moisture_pct: 1.0}`,
    `wander {soil_moisture_pct: 0.8}`;
  - `climate-1`: air, humidity;
  - `climate-2`: air, humidity, `offsets {air_temperature_c: 0.4, humidity_pct: -1.5}`,
    `wander {air_temperature_c: 0.3, humidity_pct: 1.0}`.
- Zone B: one device, as today.
- **Drifts go down**, at the game's rates (`rate_per_min` negative): a rise of 4 °C, 20 %RH or 20 % from the day's
  values could cross a label threshold (heat at 30 °C, fungal pressure at 85 %RH, water risk at 85 %), which would
  turn a sensor fault into a wrong card by chance. Going down there is room: air about 23-24 °C at 10:00 minus 4 °C
  and the walk stays well above the 16 °C cold limit; humidity has no low label; moisture about 55-68 % minus 20 %
  stays far above 10 %.
- Steps (the first 240 ticks, 2 h, are clean, as the pair check's tests require):

| Ticks | Step | Today's honest expectation |
|---|---|---|
| 240-320 | drift `air_temperature_c` on `climate-1`, `rate_per_min` −0.1 (40 min) | MISSED (noticed only when it ended, or not at all) |
| 240-320 | drift `air_temperature_c` on zone B's single device, −0.1 | MISSED, and still missed after the pair check (no partner) |
| 400-480 | drift `humidity_pct` on `climate-2`, −0.5 | MISSED |
| 560-640 | drift `soil_moisture_pct` on `substrate-2`, −0.5 | MISSED |
| 700-740 | stuck `humidity_pct` on `climate-1` (20 min) | caught on `climate-1` (the zone view answers from `climate-2`) |
| 780-880 | humid night (zone A, both climate devices see it) | caught: the humidity card, on either device |
| 900-940 | dropout of `climate-2` (20 min) | not scored; the dashboard shows `climate-2` quiet |

- **Before running it, the builder checks the margins** on seed 23: the lowest drifted air reading stays ≥ 18 °C, the
  lowest moisture reading ≥ 20 %, and no label of `expected_labels` holds on a tick of a drift window. If a margin
  fails, the builder moves that drift's start by up to ±60 ticks (rates unchanged) and records it.
- **What must hold today:** no false alarm, no wrong card, `caught_on_partner` 0, the stuck probe caught, the humid
  night caught. The drift outcomes are recorded as measured in the drift log: they are the pair check's "before".
- **If a must-hold item fails** after the margin check, the builder stops and reports the cause; the owner decides
  between changing the scenario and accepting the result.

### 3.8 Multi-device seed sweeps

The existing gate is seeds 1-80, 6 simulated hours at 30 s, no faults, 0 false alarms (`FAKE_GREENHOUSE.md`). Slice 3
adds the same sweep for the two new layouts (the `devices` of `multi_device.json` and of `slow_drift.json`, without
their steps), offline:

- 0 false alarms and 0 normal frames with a card, in every run;
- sensor-check frames on normal readings: the zone's first packet of each run (judged before the zone is
  multi-device), and beyond it no higher rate per packet than the single-device baseline at the base commit, from the
  same noise checks (owner decision 6; the first wording, "only the first packet", could not hold: today's single-device
  seeds already carry such frames);
- run through `heavy-run --priority 80` (nobody waits on it). Estimate: today's single-device sweep runs 80 × 720 ticks
  with 2 packets per tick; the two layouts have 3 and 5 packets per tick, so about 1.5× and 2.5× that run's time.
- **A failing seed** (a chance false alarm from a new partner noise stream, like the moisture stuck case in
  `FAKE_GREENHOUSE.md`) is not hidden by changing seeds. The builder reports which seed, which device and which
  label, and stops; the owner decides whether it is a real gap (punch list) or the layout needs a change.

### 3.9 What the slow-drift pair check gets from this slice

The pair-check doc (v2) lists a stage 2: simulator devices, scorer by device, `slow_drift.json`, a two-stream
real-replay harness, the live game. After slice 3:

- **Done by slice 3:**
  - simulator devices with their own noise, offsets and wander (3.1), and faults per device;
  - truth rows per device, with `sensors` and the fault on the drifted device's row only (3.2): "which probe drifted";
  - the scorer keyed by device, with `partners`, `caught_on_partner` and partner-aware false alarms (3.5);
  - `slow_drift.json` with today's honest MISSED numbers (3.7);
  - the in-process engine's alert `detail` in multi-device zones (3.4), so the pair check's "verify ... on device-2"
    text reaches the engine's alerts as it reaches Core's;
  - a sweep layout (3.8) that the pair check reruns to show its limits raise no false alarm.
- **Left to the pair check:** the pair reference, the router check, `analyze_pair_drift.py`, the two-stream
  `real-replay` harness, and a second probe in the game (Space re-upload, its own owner yes).
- **Facts the pair check must design around:**
  - all devices of a zone share the tick's sample time, and the earlier device in the list is observed and stored
    first. With the pair doc's as-of rule (store id below the own reading's, ties in sample time to the higher id),
    `climate-1`'s same-tick reading is a usable partner for `climate-2`, but not the other way round;
  - one simulated tick is one packet per device, so a 30 s stream on every device;
  - the dashboard-before-feed `detail` race (slice 2, 2.6) does not exist offline, where only the engine posts.
- The pair-check doc's stage 2 section is updated in the 3c docs step to point here.

### 3.10 Merge order with the abstention eval set

The abstention eval set (branch `abstention-eval`, uncommitted on top of c9fab40 when this was written) changes some
of the same files:

- `examples/simulators/inprocess_pomona.py`: `observe(capture=...)`, `_evaluate`, `evaluate_input`;
- `examples/simulators/sim_helpers.py` (new): `make_clock`, `split_zone_packet`, `holdout_scenario`;
- `scripts/eval_abstention.py` (new), which reads `sim.zones[zone].faults` from the simulator;
- `examples/simulators/tests/test_blind_spot.py` (imports `make_clock`), `scripts/tests/test_inprocess_pomona.py`,
  `examples/simulators/README.md`, `Makefile` (the `abstention-eval*` targets).

So:

1. **The abstention eval lands first** (Build order, step 0). Slice 3 is built on a branch cut from `main` after that
   merge, and its baselines are captured on that commit. If the abstention merge slips, slice 3 waits.
2. Slice 3 adds its `detail` call after the pipeline returns, so the abstention `capture` contract is untouched.
3. `sim_helpers.split_zone_packet` is frozen (its output is pinned in the eval's MANIFEST). Slice 3 does not change it
   and does not move the eval's split path to native devices; that is the eval's own v0.2 decision.
4. `Zone.faults` stays readable (3.1), so `eval_abstention.py` runs unchanged.
5. Slice 3's tests use `sim_helpers.make_clock`.
6. `make abstention-eval-regen` and `make abstention-eval` are Rule-0 gates (3.11).
7. The file and line references to the abstention code in this doc were checked against its worktree; the builder
   re-checks them on `main` after the merge and notes any change in the baseline README.

### 3.11 Rule 0: how it is proven

**Before any code**, a coder captures baselines into one stable folder outside any session scratchpad (a scratchpad
can be wiped, as slice 2 found), from a clean detached worktree of the `main` commit slice 3 branches from. The folder
gets a `README.md` with the exact commands and the scripts used; the builder's report names the folder. All captures
go through `~/.claude/bin/heavy-run --group pomona` (seed sweeps at priority 80).

- **Every scenario offline** (`abstention`, `blind_spot`, `cold`, `demo`, `quick`, `smoke`, `validation`): a small
  scratch script runs `fake_greenhouse.Simulation(seed=<scenario seed>, clock=sim_helpers.make_clock(), scenario=...)`
  for the scenario's ticks, writes the truth log and the events, then runs `score_fake_greenhouse.py --offline --json
  --report`. A fixed clock is needed: the CLI's `--dry-run` stamps the wall clock, which is not reproducible. Each
  truth log is written to the same relative path before and after, so the `truth` key and the report's truth line
  match; otherwise both are stripped before comparing.
- **Seeds 1-80:** the same script, default zones, no scenario, 720 ticks (6 h at 30 s), one truth log and JSON report
  per seed.
- **Stack:** `make fake-greenhouse-score` with `SCENARIO=.../smoke.json` and `.../validation.json` (real time; the
  script's own ports 18190/18191/18195, never the owner's). Compared after removing timing fields (wall times, sample
  times, delays, the truth path): verdicts, counts and rule ids.
- **Control page:** `/api/catalog` and `/api/state` JSON after 5 ticks of `demo.json` (from a test), and a screenshot of
  the page for that state, compared by eye.
- **Game:** `make fool-space-check` (test count), `make fool-space-pyodide-check` (its case list and `PARITY OK`), and
  the `export()` JSON of three recorded game sessions built with `game.Session.build` (one with lie tricks, one with
  hurt tricks and a calibration, one with hidden tricks and a reveal).
- **Abstention eval:** `make abstention-eval-regen` (byte check against its MANIFEST) and `make abstention-eval`
  (frozen baseline UNCHANGED).
- **Other gates:** `make real-replay` guard values, `make fault-replay`, `make test-checker`, `make test-demo`.
- **Suites:** simulators, scripts, router and the Space tests, with their counts.

**After the build:** every capture is byte-identical, apart from the stack's removed timing fields. The new code paths
are covered by their own tests (Done when).

### 3.12 Files

- **Simulator:** `examples/simulators/fake_greenhouse.py` (`Device`, layout and step validation, per-device sampling,
  offsets and wander, faults and commands, truth rows, catalog and state, CLI line),
  `examples/simulators/control_page.html`, `examples/simulators/scenarios/{multi_device,slow_drift}.json`.
- **Engine:** `examples/simulators/inprocess_pomona.py` (`alert_detail` copy, the multi-device monitor call), and the
  pin test in `services/core/tests/` (a new test in, or next to, `test_multi_device_feed.py`).
- **Scorer:** `scripts/score_fake_greenhouse.py`.
- **Tests:** a new `examples/simulators/tests/test_multi_device_sim.py`; extended
  `scripts/tests/test_score_fake_greenhouse.py`, `scripts/tests/test_inprocess_pomona.py` and
  `scripts/tests/test_multi_device_engine.py`.
- **Docs:** `docs/FAKE_GREENHOUSE.md` (multi-device zones, the two scenarios, honest limits for pair drifts),
  `examples/simulators/README.md` (`devices`, the step `device`, the scenarios), the parent doc's slice-3 outline
  (pointed here), the pair-check doc's stage 2 (3.9), this doc's drift log.
- **Checked, unchanged:** `spaces/try-to-fool-pomona/game.py` and its tests (`parity_driver.py`, `test_engine.py`),
  `scripts/run_fake_greenhouse_score.sh` and `scripts/run_local_validation.sh` (they call the scorer with the truth
  log; nothing in their arguments changes), `scripts/build_fool_space.py`, `scripts/eval_abstention.py`,
  `sim_helpers.py`, Core, router, automation engine, dashboard, `greenhouse_tomato.py`.

**Tests that change (intended):** none expected. The `Zone` properties (3.1) keep every attribute existing code reads,
and the single-stream rule (3.5) keeps every existing scorer join. A v1 review found no test in
`examples/simulators/tests/` that reads the moved attributes. If the builder finds one that must change, it lists it
with the reason; no asserted value may change.

## Edge cases

- **A layout that names zone B (hydroponic) with two devices:** allowed. No moisture placeholder; the reasoner's
  expected fields for `hydroponic_greenhouse` decide what is missing, as for any multi-device zone.
- **Two devices with the same probe and no offset or wander:** allowed; they differ only by white noise.
- **A fault on a field the named device does not carry:** 400 on the control page (from `queue_start`), `ValueError`
  at `Simulation(...)` for a scenario.
- **A whole-device dropout of the only carrier of a field:** the zone view has no value for it (slice 2: stale device,
  then "not reported"); the truth still expects its labels, and a real episode on it is scored as today
  (`silent_probe_blocked` decides blind spot or miss).
- **Dead clock on one device:** only that device's packets are refused; `rejected_by_core` is per stream.
- **A hidden random fault in a multi-device zone:** the reveal names the device.
- **A recorded session replayed by an older simulator:** its `load_scenario` ignores the unknown top-level `devices`
  key, and steps with `device` land on the zone's only device. Scenarios with `devices` need slice 3 or later;
  `FAKE_GREENHOUSE.md` says so.
- **Callers of `step()` outside the repo that assume one `Reading` per zone:** a single-device layout still gives one
  per zone; a multi-device layout gives one per device. The README says so.
- **More than 8 devices:** refused.
- **Running `multi_device.json` against a stack that already holds a one-device run** (for example the owner's local
  stack): the old `fake-substrate-01` packets of zone A stay inside Core's 7-day window, so zone A shows a third,
  quiet device until then. Use a fresh database for a clean picture; `FAKE_GREENHOUSE.md` says so.
- **The zone's very first packet:** judged before the other device exists (slice 1 drift item 11). The sweeps and the
  `multi_device.json` rule allow exactly that.

## Out of scope

- A zone view (slice 2's snapshot and merge) inside the in-process engine (open question 1).
- A multi-device game (open question 2): no second probe, no device UI, no Space re-upload.
- Per-device sample rates and phase offsets (all devices of a zone use the tick's timestamp).
- The pair reference, the router check and the two-stream `real-replay` harness (pair-check doc).
- Moving the abstention eval's split path to native devices (its own v0.2).
- `greenhouse_tomato.py`, the browser checker and demo, `make real-replay` sources.
- Re-uploading any Space.

## Done when

- [ ] **The abstention eval set is merged into `main`** (Build order, step 0).
- [ ] **Before any code:** the baselines of 3.11 are captured, with the exact commands in the folder's README and in
      the builder's report.
- [ ] **Byte-identical after the build:** every 3.11 capture, apart from the stack's timing fields.
- [ ] **Simulator tests** (`test_multi_device_sim.py`):
  - layout and step validation: each rule of 3.1 refused with its message; a missing `devices` key gives today's
    zones; `session_scenario` has `devices` only when the scenario did;
  - first-carrier noise: a split zone's fields equal the one-device zone's, value for value, over 200 ticks;
  - a partner's values differ by its own noise, offset and wander; over 20,000 ticks the wander's standard deviation
    is between 0.3 and 0.5 × `bound` and it never leaves ±`bound`; tick 0 draws nothing; starting a fault on one device changes no other device's values and no later draw;
  - per-device faults, recovery tails, sequences and boot ids; a whole-device dropout stops only that device;
  - the same fault on two devices is two faults; step `device` defaults (field faults, whole-device faults, calibrate,
    stop); events refuse `device`; `stop_all` and `stop_hidden` record the device;
  - a calibration's reference is the probe's own true value;
  - hidden random in a multi-device zone names a device; a single-device layout draws as before;
  - the `Zone` properties of 3.1 for one- and multi-device zones;
  - truth rows: one per device per tick, shared truth, `sensors`, `device_labels` (including the moisture alias),
    `device_offset` only where due, key order as in 3.2;
  - the moisture alias device sends `substrate_moisture_pct` only; a multi-device hydroponic zone sends no
    placeholder;
  - catalog, state and the three control endpoints with `device`, and the 400s from `queue_*`.
- [ ] **Engine tests:** in a two-device zone a sensor alert carries `detail`, and only rules matched through a
      data-quality label get it; a single-device zone's events are unchanged; the `alert_detail` copy equals Core's on
      sample results.
- [ ] **Scorer tests** (hand-built rows): two devices at the same tick do not collide; an event without `device_id`
      joins in a single-stream zone and is unmatched in a multi-device zone; `(zone, tick)` `frame_info` keys work for
      single-stream zones; a card on any device catches a real event; a sensor card counts on the faulted device;
      `caught_on_partner` and its precedence, and an unrelated partner card (another field) is not one; partner-aware false alarms (a card on an unrelated device during a
      fault is a false alarm, on a partner it is not); per-stream blind spots and `silent_probe_blocked`;
      `device_labels` in the reading level; per-stream `core_check`; no new key on single-stream zones, also in a
      mixed log.
- [ ] **`multi_device.json` against `demo.json`:** the six-point rule of 3.7 holds; the comparison script and its
      output are in the builder's report.
- [ ] **`slow_drift.json`:** the margin check, then an offline report meeting 3.7's must-hold items; the drift
      outcomes recorded in the drift log.
- [x] **Sweeps (3.8):** 2 layouts × seeds 1-80, 0 false alarms, 0 normal frames with a card, sensor-check frames beyond
      each run's first packet at no higher rate per packet than the single-device baseline (decision 6).
- [ ] **Stack and dashboard,** on a scratch stack that never touches ports 3000/8080/8081/8085/8090:
  - start Core, the router and the automation engine as `scripts/run_fake_greenhouse_score.sh` does (ports
    18190/18191/18195), and the dashboard with `CORE_URL=http://127.0.0.1:18190 MODEL_ROUTER_URL=http://127.0.0.1:18191
    AUTOMATION_ENGINE_URL=http://127.0.0.1:18195` and `uvicorn app.main:app --app-dir services/dashboard --port
    18196`;
  - run `fake_greenhouse.py --core-url http://127.0.0.1:18190 --scenario scenarios/slow_drift.json --control-port
    18197 --truth-log <scratch>` in real time for about 45 minutes. Its scripted steps start at tick 240, so during
    this run the builder injects from the control page (the device selector is under test): stuck humidity on
    `climate-1` from about minute 5 for at least 15 minutes (long enough for its card), then a dropout of `climate-2`
    for 15 minutes;
  - screenshots of the dashboard's zone A: tiles with sources from more than one device, a pair tile
    (`also climate-2`), a two-line trend, `humidity (climate-1) not used` with its `detail` line, and `climate-2`
    shown quiet during its dropout; and the control page with the device selector;
  - after stopping the simulator (Ctrl+C), score the truth log in stack mode
    (`score_fake_greenhouse.py --truth <scratch> --automation-url http://127.0.0.1:18195 --core-url
    http://127.0.0.1:18190`): the stuck probe is caught on `climate-1`, no false alarm, and `core_check` finds nothing
    missing;
  - one `make fake-greenhouse-score SCENARIO=.../multi_device.json` run (about 3.8 hours, priority 80): the stack and
    offline reports agree on which rules raised, on which device.
- [ ] **Game:** `make fool-space-check` and `make fool-space-pyodide-check` as in the baseline; the three exports
      byte-identical; `git diff` shows no change under `spaces/`.
- [ ] **Gates:** `test-local`, `local-validation`, `fool-space-check`, `fool-space-pyodide-check`, `test-checker`,
      `test-demo`, `fault-replay`, `real-replay`, `abstention-eval-regen`, `abstention-eval`.
- [ ] **Cleanup:** the scratch stack stopped, its temporary folders and any build output deleted; the baseline folder
      deleted after the merge, as slice 2 did.

## Decisions (owner, 2026-11-15)

The owner approved the recommended answer to each open question ("Yes, as recommended"):

1. **No zone view inside the in-process engine.** The abstention eval's v0.2 builds its zone-view cases on Core's real
   snapshot and the dashboard's view functions in one process.
2. **The game stays unchanged** until the pair check gives it a second probe (with that Space re-upload).
3. **`caught_on_partner` is its own passing outcome**, counted neither as caught nor as missed.
4. **Slice 3 ships `slow_drift.json`**, scored honestly as MISSED today.
5. **Partner probes get optional `offsets` and `wander`.**
6. **Sweep rule (3.8), after the build, owner "Yes, accept both":** beyond the first packet, no higher rate per packet
   than the single-device baseline.
7. **`multi_device.json` vs `demo.json`, point 3, same answer:** delays that differ through per-device alert cards are
   expected.

## Open questions (answered above; kept for the record)

1. **A zone view inside the in-process engine?** The abstention eval doc (4.3) assumed "slice 3 (which gives the
   in-process engine zone views)"; the parent outline does not list it.
   - Recommended: **not in slice 3.** It would be a third copy of Core's snapshot and the dashboard's merge, and the
     game and the scorer do not need it. When the abstention eval's v0.2 needs zone-view cases, it runs Core's real
     store and snapshot and the dashboard's view functions in one process, as slice 2's two-device check does, and
     that harness is designed in v0.2.
   - The alternative: an engine zone view in slice 3, about doubling this slice, with its own parity tests against
     Core and the dashboard.
2. **The game: leave it unchanged now, or key its state by device?** The outline said "keys per-stream state by
   device".
   - Recommended: **leave `game.py` unchanged.** Its zones stay one device each, the single-stream rule (3.5) keeps the
     shared scorer working for it, and per-device views would be code nobody can see until the pair check gives the
     game a second probe. Do it then, with that Space re-upload.
   - The alternative: per-device state and views now, unused by the live game, with changes to its parity tests.
3. **How the scorer counts a sensor card that lands on the partner probe (`caught_on_partner`).**
   - Recommended: **its own outcome and summary entry, a pass but not "caught"**, never in missed; `--fail-on-miss`
     does not fail on it. The pair check's card text asks to check both probes, and its doc accepts that about half
     the cards land on the good probe.
   - Alternatives: count it as caught (hides how often it lands on the wrong probe), or as missed (punishes the answer
     the pair-check doc chose).
4. **Ship `slow_drift.json` in slice 3, or leave it to the pair check?**
   - Recommended: **slice 3.** It is pure simulator data, it scores honestly as MISSED today, and the pair check then
     has a fixed "before" to turn into "caught". The pair-check doc's stage 2 item points here.
   - The alternative: slice 3 ships only `multi_device.json`, and the pair check writes its own scenario.
5. **Offsets and wander for partner probes.**
   - Recommended: **yes, both, optional per device.** Without them two probes differ only by white noise, which the
     pair-check doc itself calls a weak test; with them the sweeps can show the pair limits raise no false alarm.
   - The alternative: identical truth for partners, and the pair check adds realism later.

## Outline answers (S-n)

- **S-1** simulator devices, own noise, `step()` per device, faults/calibrations/commands with a device, scenario
  `"device"`, truth log, `/state`, control page, MQTT topics: 3.1, 3.2, 3.3.
- **S-2** scorer keyed by (zone, device, tick) in `build_frames`, `by_sample`, `frame_info`, `find_check`,
  `find_raise`, `open_sensor_card`, `field_vetoed` and the silence logic; a sensor card counts on the faulted device;
  an event card on any device of the zone counts: 3.5.
- **S-3** in-process engine (tests in `scripts/tests/test_inprocess_pomona.py`): 3.4.
- **S-4** game keyed by device, default zones one device each: 3.6, open question 2.
- **S-5** `multi_device.json` and the rule for matching its verdicts to `demo.json`: 3.7.

## Review changes (v1 → v2)

- **Scorer joins:** the single-stream rule (device ignored in a zone with one stream), so existing scorer tests, the
  game, the parity driver and the stack mock keep working; `(zone, tick)` `frame_info` keys stay valid there.
- **Game:** no change to `game.py` or its tests (was "two lines").
- **`Zone` properties:** mandatory read-only `faults`, `placeholder_fields`, `calibratable`, `cfg`, ... for code that
  does not change (game, abstention eval).
- **Commands:** keyword-only `device`; restart key includes the device; `stop_all` / `stop_hidden` record it; hidden
  random's exact draw rule; `session_scenario` adds `devices` only when present; step validation at construction; the
  control-page 400 from `queue_*`.
- **Probe values:** order of offset, wander, noise, quantise and faults; wander sigma `0.4 × bound`, first step at tick
  1; calibration reference is the probe's own true value; offsets keyed by canonical names.
- **Truth rows:** key order; `expected_labels(fields=...)` with the moisture alias; `placeholder_fields: []` in a
  multi-device hydroponic zone.
- **Scorer:** zone timeline defined; `caught_on_partner` precedence, totals and partner open-card rule; which
  `frame_info` stream each check reads; mixed logs.
- **`slow_drift.json`:** seed 23, downward drifts with margins, a margin pre-check and a stop-and-ask fallback.
- **`multi_device.json`:** an explained cross-device difference is recorded, not a stop.
- **Sweeps:** time estimate and what happens on a failing seed.
- **Stack check:** a doable 45-minute run with control-page injections, the dashboard's start command, stack scoring
  after the run, and one full `multi_device.json` stack run.
- **Build order:** step 0 (abstention merged) as a checked item; the scorer has its own brief; cuttable parts named.
- **Housekeeping:** no private paths or machine paths in the doc; the run scripts listed as checked and unchanged.

## Review changes (v2 → v3)

- **Hidden random:** exact algorithm with `(name, zone, device)` triples when a zone is multi-device; today's
  algorithm otherwise.
- **Scorer:** `self.streams` and `self.zones` defined, with the methods that use each; `self.raises` sort key;
  `caught_on_partner` must be about the fault's field offline (skipped in stack mode).
- **Validation:** only for scenarios with `devices` and the zones they list; shape errors and unknown keys refused;
  one-device layouts cannot use offsets, wander or the alias-only name; `device` on a one-device zone.
- **Engine:** the insertion point named in terms that survive the abstention merge; the pin test moves to Core's tests;
  the `data_quality_labels` wording.
- **Smaller:** canonical names in catalog and state; `Injection.device_id`; wander tick-0 rule, rounding and a test
  tolerance; the stuck injection's duration in the stack run; a stale third device on an old stack.
- **To re-check after the abstention merge:** 3.4 and 3.10 refer to abstention code that is not on `main` yet; the
  builder re-checks them on `main` (3.10 point 7).

## Drift log

Built 2026-11-15 on branch multi-device-slice3 from 3013bc3. Evidence folders (baselines, checks and sweeps, stack run) are on the maintainer's machine, outside the repository; their paths are left out here.

1. Files (3.12): the engine tests went into `scripts/tests/test_multi_device_engine.py` only (`test_inprocess_pomona.py` unchanged); the alert_detail pin test is a new file `services/core/tests/test_alert_detail_pin.py` next to `test_multi_device_feed.py` (that file is skipped whole when the router venv is missing; the pin needs no router).
2. `multi_device.json` vs `demo.json` (3.7, six points): points 1, 2 and 4 hold exactly (zone A union of the two devices equals demo's packet value for value on all 460 ticks, zone B byte-identical; the 4 real and 6 fault episodes and their outcomes equal; 0 false alarms). Point 3: heat delay equal (570 s, on `climate-1`); two sensor-fault delays differ: stuck air temperature on `climate-1` is caught at +90 s (demo: already active, -390 s) and plausible_offset EC on `substrate-1` at +60 s (demo: -1440 s). Traced (point 6) to per-device alert state: the automation engine keys alerts by (farm, zone, device), so in demo one sensor_check card opened by the EC drift stayed open over the later faults, while in the split zone each device raises its own card (4 extra alert events: two raises, two recoveries). Not a cross-device check and not a slice 3 bug; owner to accept. The one extra normal frame with a sensor check is the zone's first packet (`climate-1`, missing_ec/missing_moisture/missing_ph), as point 5 and slice 1 expect. Owner accepted (decision 7).
3. `slow_drift.json` (seed 23, 1000 ticks, offline): every must-hold item holds: 0 false alarms, 0 wrong cards, `caught_on_partner` 0, stuck humidity on `climate-1` caught at +90 s (3 samples), humid night raises `high_humidity_fan` on `climate-1` at +1830 s (61 samples). No drift start moved (lowest drifted air 20.23 °C on `climate-1`, 20.47 °C on zone B; lowest moisture 38.4 %). The drifts: air on `climate-1` (ticks 240-320), air on zone B (240-320), humidity on `climate-2` (400-480), moisture on `substrate-2` (560-640): each MISSED, noticed only at recovery (+2460 s, 82 samples). Partners listed; none caught on a partner. Reading level: 11 normal frames with a sensor check outside tails (1 first packet; noise stuck_value/flatline_possible on 4; 6 substrate-2 sensor_drift_possible just after its drift's recovery tail).
4. Sweeps (3.8), seeds 1-80, 720 ticks: 0 false alarms and 0 normal frames with a card in every run of both layouts. The rule "sensor-check frames only on the zone's very first packet" is NOT met as written, and could not be: today's single-device zones at 3013bc3 already have 181 such noise frames (63 of 80 seeds, max 7). Beyond the first packet: multi_device 181 frames (63 seeds, max 7; exactly the baseline's frames on the new devices), slow_drift 293 (74 seeds, max 12; the baseline's plus 112 from the two partner probes). Rate per packet beyond the first: baseline 0.157 %, multi_device 0.105 %, slow_drift 0.102 %; partner probes match their counterparts (climate-2 0.132 % vs climate-1 0.134 %; substrate-2 0.062 % vs substrate-1 0.064 %). Labels: stuck_value and flatline_possible on air temperature, humidity and moisture. Plus the zone's first packet in every seed (80 frames). Proposed wording for the owner: "beyond the first packet, no higher rate per packet than the single-device baseline, from the same noise checks". Runtime about 1.5 s per seed, far under the estimate. Owner accepted the proposed wording (decision 6); 3.8 and Done when updated.
5. Stack and dashboard (46 min of `slow_drift.json`, ports 18190-18197): a stuck humidity on `climate-1` started from the control page was caught at +90 s in stack mode and offline (two runs), 0 false alarms, `core_check` nothing missing (by stream 92/92/92/61, climate-2 short by its 15-minute dropout). Observations: (a) "humidity (climate-1) not used" appears in the trust line only once climate-2 is stale; while both climate probes report, the zone uses climate-2's humidity (slice 2's pair rule) and the pair tile shows "(not used)"; (b) the router's stuck flag lapses after about 4.5 minutes, once the frozen run fills its 11-packet window, and returns only with the 30-minute persistent check, so a stuck probe's value is shown as trusted for the rest of a 15-minute fault (by design, worth a grower-facing note); (c) a quiet climate-2 shows under Device health (silent) and by leaving the tiles, not in the trust line; (d) the "(not used)" pair-tile screenshot was lost; the state was seen live. The 3.8-hour `multi_device.json` stack run is recorded in item 11.
6. Builder calls in 3.1-3.3 (within the doc): a calibration's reference is `true[field]` exactly for a probe without offset or wander, else the probe value rounded to 4 places; `/api/state` `zones[].devices[]` also carry `sensors`; hidden random gives an event one (name, zone, None) triple; stop/queue_stop refuse a device for an event or an unknown device; the control page shows one Stop button per running fault instance in multi-device zones; `devices: null` is refused.
7. Builder calls in 3.5: in a multi-device zone the zone timeline is the first device's frame per tick, every frame stays in the per-stream lists; a multi-device row without `sensors` carries nothing; `" on <device>"` in "Pomona raised" only for real events; a single-stream zone also accepts a (zone, device, tick) frame_info key; a missing device_id counts as no device; `core_check` gains `by_stream` in multi-device zones; the blind-spot table also shows zone · device; `raised_on_partner` is recorded even when a higher-precedence outcome wins.
8. Not done here: the pair-check doc's stage 2 (3.9). `docs/design/slow-drift-pair-check.md` is untracked in the main checkout and not on this branch, so it is left to its owner as a follow-up.
9. Tests: no existing assertion changed. One test helper changed: `FakeStack` in scripts/tests/test_score_fake_greenhouse.py now also accepts a dict as a stored event, so a `device_id` can ride along; string items behave as before.
10. The control page for a zone without `devices` builds the same DOM as before (a review found an empty device list appended to every zone, a 6 px shift; fixed).
11. `multi_device.json` stack run (`make fake-greenhouse-score`, 460 ticks, 2026-11-15/16): stack and offline agree on every rule and device. Both: 1380 frames (1355 accepted by Core, the truth log agrees), real episodes 4 caught 4, sensor faults 5 (sensor_check caught 3, too short 1, missed 1 noticed only at recovery), wrong cards 0, undetectable 1, dead clock rejected 1/1, false alarms 0, caught on the partner probe 0. One delay differs: `humid_night` in `greenhouse-b` (a one-device zone) raised `high_humidity_fan` at +11038 s (61 samples) in the stack and +3527 s (1 sample) offline. The Mac slept during ticks 162-188, so samples arrived 3 to 60 minutes apart; the stack's automation engine resets persistence after a gap over `alert_max_gap_seconds` (1800 s), and the in-process engine never set that option (unchanged from 3013bc3). Not caused by slice 3; a follow-up could pass the same gap setting to the in-process engine.
