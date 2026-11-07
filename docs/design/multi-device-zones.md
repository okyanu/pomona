# Multi-device zones: two or more devices reporting for one zone

Status: **slice 1 approved by the owner 2026-11-07** ("Yes, build slice 1"; open questions answered as recommended:
the 7-day memory is accepted, and slice 1 is built first, with slices 2 and 3 designed after). Draft v3 (2026-11-07). v2 was re-reviewed by a context-free reviewer: READY WITH FIXES. v3 applies every fix:

- the tomato reasoner gets the narrowed list;
- one 7-day window for partners and fields;
- first and last seen times, and a backfill;
- retention and the device cap leave slice 1;
- the dashboard history rule is exact;
- the missing files are listed.

Earlier history: The owner chose this direction on 2026-11-07 ("Multi-device zones") over putting a
second probe in one device's packet. v1 was reviewed by two context-free reviewers (gaps; fit with the code). Both
said NOT READY, and both advised a smaller first slice. v2 specifies **slice 1** fully and outlines slices 2 and 3,
each of which gets its own design section and owner OK before it is built.

Unblocks: `docs/design/slow-drift-pair-check.md`, which needs slices 1 and 3 plus the alert detail line (slice 2).

## Goal

Pomona supports one device per zone today (`HARDWARE_EVENT_CONTRACT.md` "One device per zone"; `silent-probe.md`
"Multi-device zones (limit)"). Real setups often have two nodes in one zone, for example:

- a climate node: air temperature, humidity;
- a substrate or drain node: pH, EC, moisture.

A second probe of the same field, which the slow-drift pair check needs, is another case.

With two devices in a zone today, three things go wrong:

1. **The router mixes both devices' history.** The 11-packet history is per zone (`store.prior_events`,
   `inprocess_pomona._history`). An offset between the probes looks like noise, a frozen probe is never "stuck", and
   the noise check uses the other device's sample interval. The false flags are stored in `event_trust` and keep
   readings out of the device's trusted reference.
2. **Missing fields alarm forever.** Every device gets `missing_*` for the fields it never carries. Those labels are
   in the `sensor_check` rule, so each device gets a `sensor_check` alert that never recovers.
3. **Views flip and data is evicted.** The dashboard, the latest reading and the zone views flip between devices.
   Retention is per zone, so a fast device evicts a slow one's rows.

**Slice 1** fixes 1 and 2 and the dashboard's own sensor checks (see 1.6); retention per device is a follow-up. That makes Core's
judgement per device correct: alerts, trust verdicts and the trusted reference. **Slice 2** makes the dashboard's
zone views (tiles, trust line, risk, evaluate, twin) zone-aware. **Slice 3** makes the simulator, scorer and game
multi-device.

**Rule 0: a zone with one device behaves exactly as today in slice 1.** All new behaviour switches on only when the
zone is multi-device (1.1). Every existing test, scenario, replay and parity output must stay byte-identical, apart
from the tests listed in "Tests that change". Slice 1 has no intended single-device change.

## Slice 1: each device judged on its own

### How the user meets it

1. A grower adds `climate-1` (air, humidity) to zone A, which already has `substrate-1` (pH, EC, moisture).
2. From `climate-1`'s first live full packet on, zone A is multi-device (1.1):
   - each device's sensor checks run on its own history;
   - each device is expected to report only the fields it has reported (1.3);
   - no device gets `missing_*` for fields it never had.
3. If `substrate-1`'s EC probe stops reporting, `substrate-1` gets `missing_ec` and the `sensor_check` alert, as
   today.
4. **Known limits until slice 2:**
   - The dashboard overview still shows the zone's newest packet, which flips between devices; tiles from the other
     device show "--".
   - The trust line describes that one packet.
   - "Evaluate current risk" reasons on that one device's packet.
   - The contract and the dashboard docs say this plainly.

### 1.1 When is a zone multi-device

- **The test:** a zone is multi-device for a reading when, besides the reading's own device, at least one other device
  of the same farm and zone has sent a **live full packet** within `retention_days` (7 d) before that reading's
  `received_at`. The device-fields table (1.3) answers this.
  - A live full packet is a `sensor_events` row that is `current_eligible` and not `mqtt_retained`.
  - Observation-only devices (`sensor_observations`, the modular per-sensor path), retained-only devices and devices
    whose packets were all ineligible (bad clock) do not count.
  - `MULTI_DEVICE_ZONES` (default 1) turns the whole feature off when set to 0: always single-device.
- **Why 7 days, the same as the field memory (1.3):** a v2 review found that a shorter window (24 h) flips a healthy
  device into false alarms. When the climate node dies for a day, the substrate node would suddenly be expected to
  carry air and humidity. With one window, a silent partner is forgotten only when its fields are, after 7 days. The
  remaining device is then expected to carry everything again and gets `missing_*`. That is the first signal a node
  dead for a week gives, because a whole-node silence alert is out of scope. The contract says so.
- **The clock is the reading's own `received_at`, not wall-clock time.** The table keeps a first-seen and a last-seen
  time per row. A row counts for reading R when `first_seen ≤ R.received_at` and
  `last_seen ≥ R.received_at − retention_days`.
  - **Exact when readings are judged in arrival order:** the in-process engine, replays, and a feed that keeps up.
  - **Approximate when Core's feed lags far behind ingest:** a sighting that arrived after R can stretch `last_seen`.
    This matters only at the edge of the 7-day window.
- **In-process engine:** it uses the reading's sample time as its clock, because it has no receipt time. It feeds
  readings in time order.

### 1.2 Per-device history

- **Core:** `store.prior_events(event, limit)` filters on the event's `device_id`. The ordering and the same-sample-time
  tie rule (store id) stay as they are. `OutcomeFeed._history` is unchanged apart from the docstring ("same stream").
- **In-process engine:** `inprocess_pomona.py` keys `_history` by (farm, zone, device).
- **Single-device zones:** the rows were all that device's already, so the history is byte-identical.
- **No switch:** per-device history applies in every zone. It is the same rows for one device and correct for two.

### 1.3 Expected fields per device

- **New Core table** `device_fields(farm_id, zone_id, device_id, field, first_seen, last_seen)`:
  - Primary key (farm_id, zone_id, device_id, field). Times are `received_at`.
  - **Rows written:** `store._add` upserts one row per field. On insert both times are set; on conflict
    `first_seen = min`, `last_seen = max`.
  - **Which packets:** only for `sensor_events` (not observations), inside the branch that stores a live current
    packet (`(eligible and not duplicate) or promoted`), and not for `mqtt_retained` packets. It runs in the same
    transaction.
  - **Which fields:** `schemas.READING_FIELDS` that hold a finite number. Context numbers (`zone_area_m2`, `crop_kc`)
    and nulls do not count. Field names are stored as sent.
  - A row for a pseudo-field `__packet__` records the device's live packets for 1.1.
  - **Cleanup:** rows whose `last_seen` is older than `retention_days` are deleted in `_add`, with the same cutoff as
    the event rows. They are not cleaned in `add_trust`, which runs only when the feed is enabled.
  - `store.clear()` clears the table too.
  - **Upgrade:** when the table is created on an existing database, it is backfilled once at start-up from the stored
    live `sensor_events` within `retention_days`. That is a one-time scan, bounded by `max_events` per zone. Without
    it, a probe that was already dead at upgrade would never be recorded and never reported missing.
- **What Core sends:** for a reading in a multi-device zone, Core's feed adds `device_fields` to the pipeline request.
  - Its value is the sorted list of this device's fields whose rows count for the reading, by the 1.1 rule.
  - In a single-device zone the key is absent, so the request is byte-identical.
  - The in-process engine keeps the same per-device field set in memory, keyed by the reading's sample time, and passes
    the same argument.
- **Router narrowing:**
  - `PipelineEvaluateRequest` gains optional `device_fields: list[str] | None`. The validator keeps only strings that
    are known sensor field names.
  - `evaluate_pipeline(...)` gains a `device_fields=None` argument, which the in-process engine and the Pyodide copy
    call directly.
  - `expected_fields.py` gains `narrow_to_device(fields, device_fields)`. It keeps `f` when `f` is in `device_fields`.
    A moisture field is kept when any of `MOISTURE_FIELDS` is in `device_fields`.
  - If the result is empty, the full list is returned. A device that carries no expected field gets today's
    behaviour, and the contract says such a device belongs in its own zone.
  - It applies only when the caller passed no explicit `expected_fields`.
  - **The tomato reasoner must see the narrowed list too.** `tomato_reasoner.missing_input_fields`
    (`tomato_reasoner.py:75-81`) hard-codes air, humidity, pH and EC, plus substrate temperature and moisture for
    `greenhouse_substrate`. It skips only vetoed fields. Without a change, every device in a multi-device zone would get
    `missing_critical_data`.
    - Change: when narrowing was applied, `pipeline.py` passes `not_expected_fields` (the full list minus the narrowed
      one, plus substrate temperature and moisture when the device has neither) in the crop input.
    - `missing_input_fields` skips those as it skips vetoed fields.
    - Without narrowing, the key is absent and the output is byte-identical.
    - The water and nutrient specialists already use `expected_fields`. The builder confirms this with a test.
- **A probe that stops reporting:**
  - It stays expected for 7 days (the retention window) after its last finite reading, so `missing_*` and the
    `sensor_check` alert stay up that long.
  - After 7 days the field drops out of the device's list. The alert then recovers while the probe is still dead,
    unless another device carries the field.
  - This is stated plainly in the contract: "in a multi-device zone a probe silent for 7 days is forgotten; remove it
    from the zone or fix it". A single-device zone keeps today's rule (missing forever).

### 1.4 Retention and indexes

- **Retention stays per (farm, zone) in slice 1.** The v2 review noted that per-device retention is not needed for
  correct verdicts. It also needs a cap on devices per zone, which cannot be reported back over MQTT.
  - The punch list gets "retention per device plus a device cap".
  - The contract says that a fast device in a shared zone shortens how far back a slow device's stored history reaches.
- **Index:** `CREATE INDEX IF NOT EXISTS sensor_events_device ON sensor_events(farm_id, zone_id, device_id, id)`, at
  start-up. It serves `stream_history` and the filter step of `prior_events`.

### 1.5 Device filter on Core endpoints

`device_id` becomes an optional filter on `/v1/sensors/events`, `/v1/sensors/events/latest`, `/v1/sensors/export.csv`
and `/v1/sensors/observations`.

- `_filters` gains an optional `device_id` argument, default None. Only those four endpoints pass it, so the
  calibration, corrected-observation and device listings are unchanged.
- Without it, results are as today.
- With it, everything in the response, `latest_event` included, is that device's only.
- The `/v1/sensors/events` response gains `zone_multi_device: bool` and `latest_device_fields: list[str] | null`. The
  latter is the `device_fields` value for the latest event, or null when single-device. The dashboard needs both
  (1.6).
- New keys in a JSON response are additive. Existing clients ignore them.

### 1.6 Dashboard: its own sensor checks per device

The dashboard runs its own pipeline call (`/api/pipeline`, used by "Evaluate current risk") and posts the result to
the alert monitor (`feed_alert_monitor`). With a zone-wide history and no narrowing, it would raise the same false
alerts Core no longer raises. In a multi-device zone (`zone_multi_device` true):

- **History:** it fetches `/v1/sensors/events?farm_id=<event farm>&zone_id=<event zone>&device_id=<event
  device>&limit=24`.
  - Farm, zone and device are taken from the evaluated event even when the request is unscoped. This is new
    behaviour, and only in this branch: today's unscoped history call has no filter at all.
  - It keeps the entries whose sample time is strictly earlier than the evaluated event's, sorts them by sample time
    (API order breaks ties), and keeps the newest 11.
  - It does not drop "the last by arrival".
- **Narrowing:** it passes `device_fields = latest_device_fields`.
- **Single-device zones:** the existing code path is used unchanged, including its "drop the last by arrival" rule.
  That rule is wrong for a late packet; it goes on the punch list as a separate fix and is not changed here.

### 1.7 Not in slice 1, and why

- **Zone snapshot, tiles, trust line, risk/safety/twin/explanation views, outcome tracking across devices:** slice 2.
  The risk, safety, twin and explanation views each read `overview().latest_event` and call different router
  endpoints (shared-chain, safety-triage). Each needs its own change.
- **Alert `detail` line:** slice 2. It is needed only by the pair check.
- **Combined risks across devices** (heat on the climate node together with low moisture on the substrate node): Core's
  feed evaluates each device alone, so a label that needs fields from two devices is not raised automatically. This is
  a known limit in the contract; slice 2's on-demand snapshot is the first place that sees both. VPD needs air and
  humidity, which a climate node carries together.
- **`recalibrate_ranking`:** a device with no pH probe still ranks as "never calibrated". Punch-list item, not slice 1.

### 1.8 Edge cases

- **A second device sends one packet and goes away:** the zone is multi-device for 7 days. The first device's list holds
  all its fields, so nothing it expects changes. The other device's list holds what it sent.
- **A device that also sends `null` for fields it lacks** (Core packets may carry unused fields as null): null is not a
  finite number, so the field is not recorded.
- **Both devices carry the same field:** each is judged on its own history and expects it. The zone views stay as today
  until slice 2.
- **A zone returns to single-device after 7 days without the other device:** Core stops sending `device_fields`. The
  remaining device must then carry everything the system type expects, or it gets `missing_*`. Here that is the first
  signal that the other node has been dead for a week, and the contract says so.
- **Feed disabled** (empty router or automation URL): there are no trust rows, as today. The device-fields table is
  still filled at ingest. Nothing in slice 1 reads trust rows.
- **Clock-invalid packets:** not live, so they do not count for 1.1 or 1.3, consistent with `latest_event`.
- **Field renamed by firmware** (`soil_moisture_pct` to `substrate_moisture_pct`): both names count as moisture.

### 1.9 Files (slice 1)

- **Core:** `services/core/app/{store,outcome_feed,main,config,schemas}.py`. `SensorEventListResponse` gains
  `zone_multi_device` and `latest_device_fields`.
- **Router:**
  - `services/model-router/app/{main,pipeline,expected_fields,tomato_reasoner}.py`;
  - `trust_gate.py` only if the narrowed list must reach it (it receives `fields` from `pipeline.py` already).
- **Dashboard:** `services/dashboard/app/main.py`, including `OverviewResponse` if it passes the two new keys on.
- **In-process engine:** `examples/simulators/inprocess_pomona.py`.
- **Tests:** in `services/core/tests`, `services/model-router/tests`, `services/dashboard/tests` and `scripts/tests`.
- **Docs:** `HARDWARE_EVENT_CONTRACT.md`, `silent-probe.md` (limit note), `SENSOR_QUALITY_REASONER.md` (`device_fields`),
  this doc's drift log.
- **Vendored copies:** `make fool-space-check` rebuilds the copies the Space vendors (`spaces/try-to-fool-pomona/vendor/`
  and the `pomona.zip` hashes change: `inprocess_pomona.py` and the router app). These copies are in the diff. No
  re-upload.

### 1.10 Tests that change (intended)

- `services/core/tests/test_outcome_feed.py:265` `test_history_same_sample_time_uses_store_order`: it asserts that
  device "two" gets device "one"'s packet as history. Rewrite it for the tie rule within one device. The two packets
  then need different readings, or a `sequence` and `boot_id`: identical content at one sample time is a duplicate and
  is not stored. Add a test that the other device's packet is not in the history.
- `test_outcome_feed.py:112` and `:244`: keep. Adjust only if they rely on mixing devices; the builder reports it.
- `test_core_api.py:126`: unchanged (retention stays per zone).

### 1.11 Done when (slice 1)

- [x] **Before any code:** capture the outputs to compare against, with the exact commands in the builder's report, in a
      scratch folder:
  - `make fake-greenhouse-score` for each scenario in `examples/simulators/scenarios/`;
  - normal runs for seeds 1-80 (6 simulated hours at 30 s, as in `FAKE_GREENHOUSE.md`), with the exact loop written
    into the report;
  - `make real-replay` guard values. If datasets are missing and the replay skips them, report which ones; a baseline
    with nothing in it is not a check;
  - `make fault-replay`;
  - `make test-checker` and `make test-demo` parity results;
  - `make fool-space-check`.
- [x] **Byte-identical:** all captured outputs are byte-identical after the build, apart from timing fields.
- [x] **Core tests:**
  - multi-device window, using `received_at` and excluding observation-only, retained-only and ineligible devices;
  - per-device history;
  - the device-fields table: upsert with first and last seen, `READING_FIELDS` finite only, retained and ineligible
    packets skipped, cleanup in `_add`, `clear()`, start-up backfill;
  - `device_fields` sent only in multi-device zones;
  - the 7-day partner window, both ways (a partner silent for 6 days still counts; 8 days does not);
  - the device filter on the four endpoints, and other listings unchanged;
  - `zone_multi_device` and `latest_device_fields`.
- [x] **Two-device feed test (Core and in-process):**
  - A climate device (air, humidity) and a substrate device (pH, EC, moisture), 30 s each, 2 h, `greenhouse_substrate`:
    no `missing_*` labels, no `missing_critical_data`, no `sensor_check` alert, no noise or stuck flags.
  - The same with both devices carrying air temperature with a constant 1.5 °C offset: no noise flag.
  - Then EC disappears from the substrate device: `missing_ec` and a `sensor_check` alert on that device only.
- [x] **Router tests:**
  - `narrow_to_device` covers moisture names and the empty fallback;
  - a climate-only packet and a substrate-only packet with narrowing: no `missing_critical_data`;
  - an explicit `expected_fields` wins;
  - absent `device_fields` gives byte-identical output.
- [x] **Dashboard tests:**
  - multi-device: the history is per device, uses the event's farm and zone even when unscoped, and excludes the
    evaluated event and later samples; `device_fields` is passed;
  - single-device: the request is unchanged.
- [x] **Gates:** all make gates pass: `test-local`, `local-validation`, `fool-space-check`, `fool-space-pyodide-check`,
      `test-checker`, `test-demo`, `fault-replay`, `real-replay`.

## Slice 2 (outline: needs its own design section, review and owner OK)

Zone views for multi-device zones. The v1 reviews found these points; the slice-2 design must answer each one.

- **A zone snapshot (Core):** per field, the newest packet that carries the field from a device that is not stale.
  - Trust per device comes from `event_trust`.
  - **Define "pending" without a ceiling:** the feed may be disabled or fail, and then no trust row is ever written.
    Recommended: fall back to the dashboard evaluating that device's latest packet with its own history.
  - **Staleness:** Core returns `age_s`, and the dashboard applies its own `ZONE_STALE_AFTER_S` (0 = off). There is no
    second setting.
  - **Context fields** (`system_type`, `crop`, `weather`, ...): one rule for which device supplies them. Schema
    defaults make a climate node look like "tomato / greenhouse_substrate".
  - **Missing fields:** Core returns present fields only, and the router or dashboard decides what is missing (one
    expected-fields implementation).
- **Each dashboard view separately:**
  - **Views on `overview().latest_event`:** `/api/risk` (router shared-chain), `/api/safety` (safety-triage),
    `_digital_twin_preview` and `/api/explanation` each read it.
  - **Their requests:** the shared-chain and safety-triage requests gain `known_vetoed_fields`, or the dashboard masks
    vetoed fields before sending. The twin's own `expected_fields` must not hide a missing snapshot field.
- **Data-quality labels in the snapshot:** with no history, a stuck probe must still show on the badge and still
  create `sensor_check` suggestions from "Evaluate current risk".
- **Outcome tracking:** a snapshot suggestion has no single `device_id`, so `observe_outcomes` would fall back to the
  whole zone, and a climate node's clean readings could confirm an EC suggestion.
  - Today it already filters by the snapshot's `device_id` (`automation store.py` `own_device`). Only snapshot
    suggestions need more.
  - Fix: they record the devices behind their watched fields (`sources`), and only those devices' readings count.
- **Overview:**
  - Per-device fetches for the sparklines, so a fast device does not push out a slow one.
  - The trust-line wording that `trustLine()` really produces.
  - Device columns in the Alerts and Recent events tables.
- **Alert `detail`:** a column added with `ALTER TABLE` to both alert tables. It carries the router's sensor
  `safe_next_checks`, shown under the alert. This is the pair check's way to say which device to check. Decide whether
  it shows in single-device zones too.
- **Router `known_vetoed_fields`:** where its reason appears (the gate has one reason string, not one per field), and
  whether it takes part in companion groups and in the `cannot_confirm` test.

## Slice 3 (outline: needs its own design section, review and owner OK)

- **Simulator:** `fake_greenhouse.py` zones get devices: `DeviceConfig(device_id, sensors)`.
  - The first device keeps the existing seeds; extra devices get their own noise generators.
  - `step()` gives one Reading per device.
  - Faults, calibrations and commands take a device, and scenario steps accept `"device"`.
  - The truth log, `/state`, the control page and MQTT topics are per device.
- **Scorer:** `score_fake_greenhouse.py` keys every join by (zone, device, tick): `build_frames`, `by_sample`,
  `frame_info`, `find_check`, `find_raise`, `open_sensor_card`, `field_vetoed` and the silence logic.
  - A sensor card counts on the faulted device.
  - An event card on any device of the zone counts.
- **Game:** `spaces/try-to-fool-pomona/game.py` keys per-stream state by device. The game's default zones stay one
  device each.
- **Scenario:** `multi_device.json` (zone A split into a climate device and a substrate device) with a stated rule for
  matching its verdicts to `demo.json`.
- **Tests:** `scripts/tests/test_inprocess_pomona.py`, `scripts/tests/test_score_fake_greenhouse.py`,
  `examples/simulators/tests/`, `spaces/try-to-fool-pomona/tests/`.

## Out of scope (all slices)

- Zone-level de-duplication of condition alerts: two devices with EC give two `high_ec` alerts. Slice 2 shows the
  Device column.
- Per-device sample rates in the simulator.
- A device filter in the dashboard UI.
- A whole-node silence alert.
- Averaging or voting between two probes of one field (the pair check is its own doc).
- The browser sensor-data checker, which is already per device.
- `make real-replay` (single-stream sources).
- Re-uploading Spaces.

## Open questions (slice 1)

1. **One 7-day memory in multi-device zones** (1.1, 1.3):
   - A probe that stops reporting raises `missing_*` for 7 days, then is forgotten.
   - A partner node silent for 7 days is forgotten too, after which the remaining device is expected to carry
     everything.
   - Accept (recommended; the contract says so), or keep fields expected forever? Forever needs a "remove this probe
     or device" action, which does not exist.
2. **Build slice 1 now, then write slices 2 and 3 as their own designs** (recommended), or design all three before
   building anything?

## Review changes (v1 → v2)

- **Scope:** split into slices; only slice 1 is specified.
- **Rule 0:** made strict for slice 1, which has no single-device changes. The late-packet fix moves to the punch list.
- **Multi-device test:** counts live full packets only and uses the reading's `received_at` as its clock.
- **`device_fields`:**
  - comes from a table kept at ingest, with no payload scans;
  - fields stay expected for the 7-day retention window, not 24 h;
  - the router does the narrowing, with moisture names defined, and `evaluate_pipeline` gets the argument too.
- **Retention:** per-device retention and a device cap were added in v2, then moved to the punch list in v3.
- **Dashboard:** in slice 1 it handles only its own sensor checks and alert post. The views, snapshot, outcome
  tracking and alert detail move to the slice-2 outline with every reviewer finding listed.
- **Simulator, scorer and game:** moved to slice 3, with the real size listed.
- **References:** stale references fixed (the `stream_calibrations` index claim; the contract line numbers).

## Drift log

Slice 1, built 2026-11-07 in the worktree `pomona-multidevice` (branch `multi-device-slice1`, based on 57f7049, nothing
committed). Where the code differs from this doc, or the doc was silent:

1. **`not_expected_fields` rule (1.3).** The doc says "the full list minus the narrowed one, plus substrate temperature and
   moisture when the device has neither". Built as: when narrowing shrinks the list, the system type's fields the device
   does not carry, plus `substrate_temperature_c` when the device has never sent it, plus `substrate_moisture_pct` when it
   sent none of `MOISTURE_FIELDS`. The doc's wording would still demand `substrate_temperature_c` from the 1.11 substrate
   device (pH, EC, moisture), which gives `missing_critical_data` and fails the done-when. When narrowing does not shrink
   the list (the device carries all of the expected fields, or none of them, which falls back to the full list), no
   `not_expected_fields` is built and the device keeps today's behaviour, including a missing substrate temperature.
2. **Known sensor field names (1.3 validator).** `KNOWN_SENSOR_FIELDS` in `expected_fields.py` is the four base fields, the
   three moisture names and `substrate_temperature_c`. The request validator drops other names (and non-strings) silently.
3. **Empty `device_fields`.** An empty list (or one with no known names) means no narrowing and no `not_expected_fields`,
   like an absent key. Core sends the key (possibly `[]`) in a multi-device zone; the router treats `[]` as absent.
4. **Vendored copies are not in the diff (1.9).** `spaces/try-to-fool-pomona/vendor/` and `pomona.zip` are gitignored and
   generated by `make fool-space-check`; they are rebuilt locally and are not part of the change. Nothing to re-upload.
5. **Cleanup in `_add` (1.3)** deletes old `device_fields` rows on every add, including observation adds (the doc says
   "in `_add`"); it is the same cutoff as the event rows.
6. **Backfill (1.3).** Selects `current_eligible=1` rows with `received_at >= cutoff`, skips payloads with
   `mqtt_retained`, and runs only when the table did not exist before the start-up (checked with `sqlite_master`). No extra
   per-zone bound: the stored rows are already bounded by `max_events` per zone.
7. **Switch (1.1).** `MULTI_DEVICE_ZONES` is read by Core only. The in-process engine always applies the rule, with a fixed
   7-day `RETENTION` constant (Core's default) instead of a setting.
8. **API keys on a single-device zone (1.5, 1.6).** `/v1/sensors/events` always carries `zone_multi_device` and
   `latest_device_fields` (false / null when single-device), and the dashboard's `/api/overview` passes them on. These two
   JSON responses are therefore **not byte-identical** for single-device zones (additive keys; existing clients ignore
   them). The request bodies Core and the dashboard send to the router, and every router and alert output, are unchanged.
9. **Core `latest_device_fields` clock (1.5).** It is evaluated with the latest event's own `received_at`, so an unfiltered
   listing can say "single-device" for a device's newest reading when that reading predates its partner's first packet.
10. **A retained `latest_event` (1.5).** `latest_event` can be a retained MQTT packet (stored, current-eligible, not live).
    Its own device may then have no live rows, so `device_fields_for` returns `[]` while `zone_multi_device` is true. The
    dashboard sends `device_fields: []` and the router does no narrowing (same as an absent key).
11. **The zone's first packet is judged alone.** A zone becomes multi-device at the second device's first live packet, so
    the very first packet of the zone (and any packet received before its partner existed) is judged as single-device. The
    tests exclude it. This follows from 1.1; the doc did not say it.
12. **`prior_events` same-sample-time quirk (found, not changed).** The tie rule looks up the event by (device, sample
    time) and takes the highest store id, so a packet that is processed after a later-stored packet with the same device and
    same sample time sees itself in its history. Not new (before, it was also true within one device); the 1.10 rewrite of
    `test_history_same_sample_time_uses_store_order` therefore processes each packet right after storing it. Punch-list item.
13. **Tests added beyond the list.** `services/core/tests/test_multi_device_feed.py` runs Core's real feed against the real
    model-router in a subprocess of the model-router venv (helper `router_vclock.py`: the router's clock follows each
    reading's sample time) and the real alert monitor; it is skipped when that venv is missing. The in-process twin is
    `scripts/tests/test_multi_device_engine.py`.
14. **Dashboard docs (How the user meets it, point 4).** `services/dashboard/README.md` got the plain statement of the
    slice-2 limits, besides the contract.
15. **Make in a git worktree.** `make fool-space-check` and `fool-space-pyodide-check` need `make -o
    spaces/try-to-fool-pomona/.venv/bin/python ...` in a fresh worktree (the checkout's file times make `make` try to rebuild
    the symlinked venv). No repo change.
