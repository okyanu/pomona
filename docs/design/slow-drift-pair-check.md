# Slow drift: judge a probe against the other probes in its zone

Status: v5 APPROVED by the owner on 2026-11-16 ("Yes, as recommended"); see "Decisions". v5 is BUILT (2026-11-21,
uncommitted on branch `slow-drift-pair-check`, waiting for the owner's commit decision). The stack run is done, and the
zone-snapshot fix it found (drift log item 28) is in; see the "Drift log" at the end and the "Done when" items.
- v1 and v2 were reviewed as NOT READY. Pomona then supported one device per zone, so pairing separate devices first
  needed multi-device zones. The owner chose to build those (`docs/design/multi-device-zones.md`, slices 1-3).
- v3 rewrote this doc on top of what slices 1-3 built. Two fresh reviews (gaps; fit with the code) said READY WITH
  FIXES; v4 applied them. A re-review of v4 said READY WITH FIXES; v5 applies those. See the "Changes" sections at the
  end.
- Builds on slice 3 (branch `multi-device-slice3`). It is built only after slice 3 is merged into `main`.

Issue: `private/ISSUES.md` "Sensor check: neighbour/zone corroboration"; `docs/SENSOR_TEMPORAL_CHECKS.md` "Still MISSED
in the game: a slow drift of air temperature, humidity, substrate moisture or substrate temperature".

## Goal

A probe that slowly drifts (the game's "Drift" trick: 0.1 °C, 0.5 %RH or 0.5 % moisture per minute for 40 minutes) is
not caught while it drifts. It is noticed only when it ends and the reading snaps back, which the scorer counts as
missed (`caught_at_recovery`). Slice 3 measured this: in `slow_drift.json` all four drifts are MISSED today.

Comparing a probe with its own past cannot fix this. Real readings leave their own trusted 2-hour median by more than
the whole drift (air 3.3–8.7 °C on 1 % of readings, humidity 12.6–16.3 %RH; see `SENSOR_TEMPORAL_CHECKS.md`). A limit
that tight would flag real weather every day, and it would turn real events (dry zone, heat spike) into "can't confirm
the probe".

This design uses a **second device in the same zone**. Two probes in one space see the same weather, irrigation and
events, so the difference between them barely moves, even when both swing by 10 °C. A drift in one probe changes the
difference. A real event moves both and leaves the difference alone, so event cards are not withheld. A sudden shared
change (an irrigation pulse, a humidity step) is not judged on the reading where it happens, because the two probes'
readings are not taken at the same moment (Design 4, fast-change skip).

The check works only where a zone has two or more devices reporting the same field, each at least every 5 minutes
(open question 5). A zone with one probe keeps today's behaviour, and its drifts stay missed. The docs say so plainly.

## Evidence (real data, no fault labels)

"Moves" means how far the difference leaves its own trailing 2-hour median, the same reference Core uses for one stream.
Flagged readings are kept out of that median (as Core does), so the counts below are what the check would do.

**UF hydroponic chamber** (Mendeley rmvgvkg8vn, 10 s, CC BY 4.0, already credited in `LICENSE_AND_ATTRIBUTION.md`).
Air temperature and humidity at four positions in one chamber.

| Field | One probe vs its own 2 h median (p99.99) | Probe minus the median of the other three (p99.99, max) |
|---|---|---|
| Air temperature, 30 s | 11.0–12.0 °C (lights on and off) | 1.5–2.8 °C, max 2.8 |
| Humidity, 30 s | 22.8–27.4 %RH | 3.9–7.0 %RH, max 8.5 |
| Same at 5 min | same | same within 0.1 |

**Two devices do not sample at the same moment.** The rule below pairs a reading with each partner's latest earlier
reading.

- **Method:** each probe is paired with one partner whose reading is 0, 10 or 20 s older, at a 30 s cadence (308,000
  readings per pair, about 107 days).
- **Air at 3.0 °C:**
  - Sensor/upper pair: 28, 32 and 45 flagged readings; 1, 2 and 3 cards (lag 0, 10, 20 s).
  - Every other pair: 0.
- **Humidity at 10 %RH:**
  - Sensor/upper pair: 3, 5 and 7 flagged readings; 1 card each.
  - One more pair at 20 s lag: 4 readings, 1 card.
  - Every other pair: 0.
- The evidence script (Design 5) adds a lag of one full interval (30 s at 30 s, 5 min at 5 min) with the fast-change
  skip, because the rule below always uses a strictly earlier partner reading; devices with aligned clocks see exactly
  that lag.

**AGC2 cherry-tomato greenhouse** (4TU, in `make real-replay`, 5 min). Each compartment has two Grodan slab probes
(`GrodanSens.csv`). Slab 1 is compared with slab 2, about 45,000 readings per compartment.

| Field | One probe vs its own 2 h median (p99.99) | Slab 1 minus slab 2 (p99.99, max) |
|---|---|---|
| Substrate moisture | 6.0–12.7 % (Digilog 80: a glitch) | 3.2–6.3 %, max 6.7 (Digilog 24.5, max 91.8: glitches) |
| Substrate temperature | 1.8–3.7 °C | 0.6–2.6 °C (Digilog max 4.7). Not in this build, see Design 1 |

**Neighbouring compartments do not help.** AGC2's six compartments are run by different teams. One compartment minus the
others moves as much as one probe alone (air p99.99 5.9–10.9 °C, humidity 24.8–52.4 %RH). So pairs never cross zones.

### Limits and what they flag

| Field | Limit | Real readings flagged | Cards (3 in a row) | 40-min game drift caught after |
|---|---|---|---|---|
| Air temperature | 3.0 °C | UF: 0 with three partners; one pair 28–45 of 308,548 | 1–3 per about 107 days, one pair | 30 min (0.1 °C/min) |
| Humidity | 10 %RH | UF: 0 with three partners; one or two pairs 3–7 | 1, one or two pairs | 20 min (0.5 %RH/min) |
| Moisture (both names) | 8 % | AGC2: 0 in 5 compartments; Digilog 47 of 45,311 (0.10 %) | 4 (glitches), one compartment | 16 min (0.5 %/min) |

- **Card timing:** add 1 to 1.5 minutes at 30 s sampling for the 3 flagged readings in a row that make a card.
- **Assumption:** the times assume the pair reference has 2 h of drift-free history; with less, the median moves sooner
  (see Edge cases).
- **Accepted false cards** (open question 3), all on one pair or compartment, none elsewhere:
  - UF air, the sensor/upper pair: 1–3 cards in about 107 days (28–45 flagged readings).
  - UF humidity, one or two pairs: 1 card each in about 107 days.
  - AGC2 moisture, the Digilog compartment: 4 cards in about 157 days, from real slab-probe glitches (one slab reads
    24.5–91.8 % off). A glitch that lasts 3 readings deserves a "check both probes".
- **Headroom:** with three partners the worst UF probe reaches 2.8 °C (1.06× under the 3.0 °C limit). A two-probe zone
  is judged against one partner, and the worst real pair does cross the limit (the false cards above). There is no
  headroom for that pair; the limit is set by the game's drift (open question 3).
- **Thin evidence:** air and humidity come from one closed chamber, and the moisture pairs from one greenhouse site.

## How the user meets it

1. Zone A has two climate devices, `climate-1` and `climate-2`, each sending its own packets with the same `zone_id`.
   The dashboard shows one humidity tile for the zone, taken from the first device in slice 2's stable order, with the
   other device's value beside it.
2. `climate-1`'s humidity starts drifting downward at 0.5 %RH per minute.
3. After about 20 minutes the difference has moved by 10 %RH. The next reading to cross the limit is flagged
   `baseline_drift_possible` on `humidity_pct`. In a two-probe zone that reading can come from either device: with
   ordinary noise it is close to a coin flip which one crosses first (Edge cases). With three or more probes it is the
   drifting one.
4. **Check text, one partner** (Design 4): `pair check: humidity_pct on climate-1 is 10.4 %RH lower than usual against
   climate-2 (now -11.9, usually -1.5). Check both with a meter; calibrate only the one that was wrong.` If the
   difference rose, the text says "higher". It names both devices, because Core stores the text and the zone view
   passes it on to other devices' evaluations.
5. **Check text, three or more partners:** the same, but "against the median of 3 other probes in this zone".
6. Once that reading is vetoed, it no longer serves as a partner (Design 1). So the other device is not judged against
   it, and only the flagged device goes on being flagged.
7. After 3 flagged readings in a row, the existing `sensor_check` alert fires for that device: **one card**. The alert
   engine keeps one card per (farm, zone, device). The alert row shows the device and the check text (slice 2's alert
   `detail`).
8. **The zone view** (open question 1, recommended answer): while any device of the zone has a pair flag on humidity,
   the zone treats humidity as "can't confirm": the tile shows both values with "probes disagree", and the router is
   told the field is vetoed, so no advice uses either value. This holds whichever probe took the flag. (Without it,
   slice 2's rule would switch the tile to the other device, which is the drifted one when the good probe was flagged.)
9. The grower checks both probes with a meter and records a calibration for the wrong one. Any calibration of that
   field in the zone restarts the pair reference (Design 3).
10. A real event (dry zone, humid night) moves both probes. The difference stays put, nothing is flagged, and the event
    card appears as today. A sudden step in both (irrigation) is skipped on the reading where it happens and judged
    normally from the next one.

## Design

### 0. What already exists (slices 1-3)

Nothing in this section is built by this doc. It is listed so the builder relies on it and does not rebuild it.

- **Per-device history** (v2's step 0, done in slice 1): `store.prior_events` and `store.stream_history` filter by farm,
  zone and device; `inprocess_pomona.py` keeps `_history` per (farm, zone, device); `/v1/sensors/events` takes
  `device_id`.
- **Per-device trust rows and alerts:** `event_trust` holds each judged reading's vetoed fields and checks, keyed by
  (farm, zone, device, `sample_time`); the automation engine keys alerts by (farm, zone, device).
- **Alert check text:** Core's outcome feed sends `detail` (the router's `safe_next_checks`, without "continue routine
  monitoring", cut to 500 characters) and the in-process engine sends the same in multi-device zones (slice 3, 3.4,
  pinned by `services/core/tests/test_alert_detail_pin.py`).
- **Zone view** (slice 2): Core's `/v1/sensors/zone-snapshot` takes each field from the first non-vetoed device in a
  stable order, and lists the other devices' values as `others`. Other devices' stored checks reach an evaluation as
  `known_safe_next_checks`, and the router drops any such string longer than `MAX_KNOWN_CHECK_CHARS` (300).
- **Multi-device switch:** `settings.multi_device_zones` (`config.py`, default on). When it is off, `device_fields_for`
  returns None and zones behave as one stream; the pair check is then off too.
- **Simulator and scorer** (slice 3): zones with `devices`, per-device faults, offsets and wander; the truth log names
  the drifted device; the scorer joins by (zone, device, tick) in multi-device zones and has the passing outcome
  `caught_on_partner` (a sensor card on a partner of the faulted device).
- **`scenarios/slow_drift.json`** (slice 3, 3.7): seed 23, 1000 ticks at 30 s, zone A with `climate-1`/`climate-2` (air,
  humidity) and `substrate-1` (`soil_moisture_pct`)/`substrate-2` (`substrate_moisture_pct` only: the alias case), zone B
  with one device. 2 h of clean readings, then downward drifts at the game's rates. Today: every drift MISSED.
- **Sweep layouts** (slice 3, 3.8): seeds 1-80 of the `multi_device.json` and `slow_drift.json` device layouts, no steps,
  with the accepted rule "beyond the first packet, no higher sensor-check rate per packet than the single-device
  baseline".

**Facts from slice 3 that this design relies on:**
- In the simulator, all devices of a zone share the tick's sample time, and the earlier device in the zone's list is
  observed and stored first. One tick is one packet per device: a 30 s stream on every device.
- `multi_device.json` splits zone A into devices with **no field in common**, so it has no pairs. Its outputs must stay
  byte-identical.

### 1. Partners

- **Fields:** `air_temperature_c`, `humidity_pct`, `soil_moisture_pct`, `substrate_moisture_pct`.
  - `substrate_temperature_c` is left out. It has no calibration path (`schemas.py` `CalibrationEvent.measurement` and
    `MEASUREMENT_FIELDS` do not list it), so a flagged pair could never be cleared. Open question 2.
  - pH and EC are out of scope.
- **Matching:** a partner is another device with the same `farm_id` and `zone_id` reporting the field, matched through
  `ALIASES`. A device sending `substrate_moisture_pct` pairs with one sending `soil_moisture_pct`.
  - **A device sending both moisture names** is one probe. As a partner, its value is the one under the own reading's
    field name if present, else the other name. As the judged device, the pair is computed once, under the first of
    its names in `ALIASES` order, and the one check text names that field; the veto covers both names, as today.
- **Usable partner reading** for an own reading at sample time `t`:
  - Its sample time `s` is **strictly before** `t` and within `t − PAIR_MAX_AGE_S ≤ s`. Strictly before, the same rule
    `stream_history` uses for the own stream, makes the result independent of the order in which same-tick packets
    are stored, so no store id is needed. In the simulator every device is judged against the others' readings of the
    tick before.
  - It has been **judged**: an `event_trust` row exists for (farm, zone, device, `sample_time`). A reading the feed
    dropped or failed to judge has no row and is not used (unlike the own stream, where `stream_history` counts a
    missing row as not vetoed; that rule is unchanged).
  - The field is present and finite, and not in that row's `vetoed_fields`.
  - It passes the same filters as an own-stream reading in `stream_history` (no extra `current_eligible` or
    `mqtt_retained` rule, so own and partner rows are treated alike).
  - Duplicate sample times of one device: the row `event_trust` describes (one per sample time); the newest stored
    payload at that sample time gives the value.
- **Flat partners are not partners:** a device whose usable readings of the field in the current reading's window all
  have one value (at least `PAIR_MIN_N` of them) is skipped as a partner, and a flat own stream is not judged. The
  test is made once, as of the current reading. This keeps a hydroponic zone's
  constant moisture placeholder from being paired with a real slab probe.
- **Why vetoed partner readings are left out:** a fault already caught on device 1 (stuck, step, spike) must not make
  device 2 look wrong. If it did, the zone would lose the field on both devices for every fault.
- **Partner value:** for each partner device, take its latest usable reading. The partner value is the median over the
  partner devices (`statistics.median`: the mean of the middle two for an even count). At most
  `PAIR_MAX_PARTNERS = 8` devices are used: the first 8 by `device_id` among the devices that have a usable reading at
  that moment, so a dead device never takes a slot. Fewer than 1 partner means no partner value.
- **Partner set:** the sorted list of partner device ids that gave the partner value. It is stored with every offset
  (Design 2), so a partner going quiet or coming back never mixes offsets taken against different partners.
- **`PAIR_MAX_AGE_S`:** `2.5 ×` the median of the own stream's last 12 sample intervals (all stored own readings of the
  field, from `stream_history`), clamped to 60–750 s. With fewer than 2 own readings it is 750 s. It is computed once,
  at the current reading, and used for every offset in the window. 2.5 intervals means one missed partner packet does
  not drop the partner. At 30 s it is 75 s; at 5 min it is 750 s.
- **Supported cadence:** a stream whose median interval is over 5 minutes is not paired and not judged (open question
  5). Such a device can still be a partner when its readings are fresh enough for the other device's age limit.

### 2. Pair reference

- **Offsets:** for each own reading in the window, with sample time `≥` the pair start (Design 3; the same rule as
  `_Walk.push`), where the field was not vetoed and a partner value existed at that reading (Design 1, as of that
  reading, with partner readings also `≥` the pair start): `offset = own − partner value`, with its partner set.
- **Window:** own readings with sample time in [current − `window_s`, current), where `window_s` is the caller's (Core:
  `settings.trust_baseline_window_s`; the in-process engine: `DEFAULT_WINDOW_S`). It ends at the current reading, so no
  other anchor is needed. Core asks for partner rows from the window start minus `PAIR_MAX_AGE_S`.
- **Reference:** the median of the offsets whose partner set equals the current reading's partner set. `n` counts those
  offsets only. A changed partner set therefore starts collecting afresh.
- **`PAIR_MIN_N = 12`:** at least 12 such offsets are needed (6 min at 30 s, 1 h at 5 min). Separate from
  `TRUST_BASELINE_MIN_N` (6). A constant in `trusted_baseline.py`, enforced inside `pair_reference` (so by Core and the
  in-process engine alike); the router only checks that `n` is a positive whole number.
- **Lapse:** the pair reference follows the own reference's opt-in lapse (`TRUST_BASELINE_MAX_AGE_S`, passed as
  `lapse_s`): when it is set and the newest usable offset is older than it, there is no `pair` entry. Default: off, as
  for the own reference.
- **Output:** the field's `stream_baseline` entry gains
  `"pair": {"offset": float, "n": int, "partner_value": float, "partners": int, "partner_device": str|null,
  "device": str}`.
  - `offset` and `partner_value` are rounded to 6 places (as `_summary` rounds `spread`); `partner_value`, `partners`
    and `partner_device` are as of the current reading; `partner_device` is set only when `partners == 1`; `device` is
    the own device id, for the check text.
  - The key is present only when the own entry exists, there is a partner value now, and `n ≥ PAIR_MIN_N`.
  - Without it, the entry, and the request body `outcome_feed._process` sends, are byte-identical to today.
- **One pure function** builds the `pair` entry:
  `pair_reference(own_rows, partner_rows, field, pair_start, current, window_s, lapse_s=None)` in
  `trusted_baseline.py`, standard library only (it runs in Pyodide).
  - `own_rows`: the own stream's stored readings before the current one, oldest first (as `stream_history` returns
    them, with `vetoed_fields`). `partner_rows`: judged partner readings, any order. `current`: the reading being
    judged (`device_id`, `sample_time`, field values). Rows are dicts with `device_id`, `sample_time`, the field
    value(s) and `vetoed_fields`.
  - `PAIR_MAX_AGE_S` is computed inside it from `own_rows` (Design 1); `lapse_s` is the lapse.
  - It returns the `pair` dict or None. It returns None also when the fast-change skip applies (Design 4), so the
    router never sees a pair entry for that reading.
  - Core calls it with rows from the store. The in-process engine calls it from a per-zone buffer of judged rows.
  - **Equality with the in-process engine** holds when every earlier reading was judged before the current one, which
    is how the in-process engine runs and how Core's feed runs while it keeps up. If Core's feed judges out of order
    (two ingest threads) or drops a reading, a partner reading may be missing at that moment; it is then not used,
    and the next reading uses it. A test builds the in-order case and checks equality; another test checks that a
    missing trust row makes a partner reading unusable.
  - `StreamBaseline` itself is not changed.
- **Store (Core):**
  - The pair path runs only when `settings.pair_check` is on **and** `device_fields_for(event)` is not None (the same
    gate the feed already uses for `device_fields` and `detail`, so a pair flag always comes with its `detail` text).
  - New `zone_pair_devices(event, fields)`: the other devices of the zone that have carried any of the fields, from
    the `device_fields` table, with the same time rule as `device_fields_for` (`first_seen ≤` the event's
    `received_at`, `last_seen ≥` it minus the retention days). `device_fields_for` returns only the event's own device,
    so this is a new query.
  - New `zone_partner_history(event, devices, field_names, since)`: those devices' rows with sample time in
    [`since`, event time), joined to `event_trust` on (device, `sample_time`) as `stream_history` does, judged rows
    only, parsed once. It uses the existing zone-wide index `sensor_events_sample_zone (farm_id, zone_id, sample_epoch,
    id)`. Bound: the window by `sample_epoch` (about 240 rows per partner at 30 s, 24 at 5 min), with a hard cap of
    `trust_baseline_scan_limit` rows per partner.
  - New `zone_calibrations(farm_id, zone_id)`: the zone's newest 200 calibrations on any device, parsed in Python as
    `stream_calibrations` does (the measurement is only inside the JSON payload). The pair start is the newest one
    whose measurement covers the field through `MEASUREMENT_FIELDS` and whose parsed `performed_at` is `≤` the current
    reading's time, compared as datetimes, not strings. A calibration beyond the newest 200 of the zone is not seen;
    with 200 the oldest one is weeks back on any real farm.
  - **Settings:** new `pair_check: bool = True` (env `PAIR_CHECK`) in `config.py`. Off: no `pair` entry and no new
    query; multi-device zones are otherwise unchanged. The in-process engine takes `pair_check=True` as a constructor
    argument.
- **Only in multi-device zones:** the partner queries run only when `zone_pair_devices` returns a device. A one-device
  zone makes no new query and sends exactly the same request as today.
- **In-process engine:** the same three answers from its own state: its per-device field record (`_device_fields`, with
  the same rule it already uses to decide `device_fields`), a per-zone buffer of judged rows, and its calibration list.
  - The buffer exists only for zones with two or more devices carrying a pair field, so a single-device zone (the
    whole game) runs no new code.
  - It is bounded by the window and by `PAIR_BUFFER_MAX_ROWS = 4000` per zone.
  - Cost: one `pair_reference` call per reading and field, over at most the window's rows. The `slow_drift.json`
    offline run time is recorded before and after; the sweep must stay under 2× slice 3's time per seed.
- **Retention:** `max_events` is per zone (`store.py`, the zone trim), so two devices halve each stream's retained
  history. `HARDWARE_EVENT_CONTRACT.md` already says retention is per zone; it gains the per-device consequence. No
  change to the default.

### 3. Calibration

- **Pair start:** the newest calibration of the field (through `MEASUREMENT_FIELDS`, so a `soil_moisture_pct`
  calibration covers both names) on **any** device in the zone, with `performed_at ≤` the current reading's time.
  Offsets and partner readings both start at it.
- The own-stream reference keeps using `stream_calibrations` per device and is not affected.
- **Calibrating the good probe** restarts the pair too. The grower checked one probe with a meter, so the current
  offset is accepted. If the other probe is still drifted, that drift becomes the new normal. Today's single-stream
  check has the same property. The check text and the docs say: "calibrate only the one that was wrong".
- **After a restart** the pair is not judged until 12 new offsets exist.
- **In the simulator:** the control page's calibrate action records a calibration per device (slice 3). The in-process
  engine uses the newest calibration of the field on any device of the zone.

### 4. Router check

- **Where:** in `sensor_quality.apply_persistent_checks`, inside the existing loop over `stream_baseline` fields. Only
  Core's outcome feed and the in-process engine send `stream_baseline`.
- **Not mirrored in the browser checker:** `spaces/sensor-data-checker/persistent.js` mirrors this function, and the
  pair check is deliberately not mirrored (the checker judges one uploaded stream). The parity case generators never
  emit `pair`, so the parity tests are unaffected; a comment at the new code says so.
- **When:** for a field with a valid `pair` and a current finite reading:
  - `moved = (current − partner_value) − offset`.
  - If `|moved| ≥ PAIR_DRIFT_LIMITS[field]` (air 3.0, humidity 10.0, both moisture names 8.0), add
    `baseline_drift_possible`, the field as a suspect, and the check text.
  - There is no separate clear threshold: a flagged reading is vetoed and stays out of the offsets, so the reference
    does not follow the drift, and the flag holds for as long as `|moved|` stays over the limit.
- **Fast-change skip** (computed in `pair_reference`, which then returns no entry): the reading is not judged when its
  own step, `|current − previous own reading|` (the previous stored own reading of the field, vetoed or not), is at
  least `PAIR_FAST_STEP[field]` = a third of the limit (air 1.0 °C, humidity 3.3 %RH, moisture 2.7 %).
  - Why: the partner reading is always earlier, by up to one interval (a full interval when clocks are aligned, as in
    the simulator). A change shared by both probes shows up in the own reading before the partner has reported it.
    Skipping fast own steps bounds that error to a third of the limit.
  - A drift at the game's rates never triggers it (per reading: 0.05 °C, 0.25 %RH, 0.25 % at 30 s; 0.5 °C, 2.5 %RH,
    2.5 % at 5 min).
  - A shared step (an irrigation pulse of up to 7 %, a humidity step of 8–15 %RH at 5 min, a heat ramp of 2.5 °C per
    5 min): skipped on the reading with the step; on the next reading the partner has reported the step too and the
    difference is back to normal.
  - Offsets in the window are not filtered by it: a skipped reading still gives an offset if it was not vetoed (a
    shared step moves the offset by at most one reading, and the median ignores it).
- **Check text:**
  `pair check: <field> on <device> is <|moved|> <unit> <higher|lower> than usual against <partner> (now <d>, usually
  <offset>). Check both with a meter; calibrate only the one that was wrong.`
  - `<partner>` is `partner_device`, or `the median of <n> other probes in this zone`.
  - `<d>` is `current − partner_value`; numbers have 1 decimal place; units: °C, %RH, %.
  - Device ids in the text are cut to 32 characters (31 and "…") and have control characters removed, as `clean_detail`
    does. The text is then at most 260 characters, under `MAX_KNOWN_CHECK_CHARS` (300).
  - It does not reuse `CALIBRATION_HINT`, whose "calibrate this probe" contradicts "calibrate only the wrong one".
  - It is put first in `checks`, so the 500-character `detail` cut keeps it.
- **Duplicates:** labels are not added twice (`add_unique`); one pair text per alias group (Design 1).
- **Placement:** `PAIR_DRIFT_LIMITS` sits beside `STEP_LIMITS`, with a plain-words comment on the evidence. The limits do
  not scale with the sample rate; at 30 s and 5 min they flagged the same.
- **Validation:** `services/model-router/app/main.py` `validate_stream_baseline` validates `pair` the way it validates
  the other keys: a malformed `pair` raises `ValueError` (422), since only Core sends it and a bad one is a Core bug.
  `apply_persistent_checks` itself also ignores a malformed `pair` (for direct callers), as it does for other entries.

### 4b. Zone view while probes disagree (open question 1, recommended answer)

Built only if the owner picks the recommended answer to open question 1.

- **Router:** `sensor_quality`'s result gains `pair_disagreement_fields` (the fields the pair check flagged on this
  reading), present only when not empty, so every other output stays byte-identical.
- **Core feed:** `event_trust` gains a `pair_fields` column (JSON list, added with the existing `ALTER TABLE` pattern
  for trust columns), written from that key.
- **Zone snapshot** (slice 2's per-field rule, step 3): if any non-stale candidate device's latest judged trust row
  lists the field in `pair_fields`, the zone value is still the first candidate in the stable order, but it is marked
  vetoed for the router (as when every candidate vetoes the field), and `fields[f]` gains `"disagree": true`.
  - So no advice uses either value while the probes disagree, whichever probe took the flag.
  - It ends when no candidate's latest row lists the field: after a calibration restarts the pair, or when the
    difference comes back.
- **Dashboard:** the field's tile shows both values (from `others`) and "probes disagree: check both with a meter".
- **In-process engine:** no zone view (slice 3, owner decision 1), so nothing changes there.
- Files added by 4b: `services/core/app/store.py` (column, snapshot), `services/core/app/outcome_feed.py`,
  `services/model-router/app/sensor_quality.py`, `services/dashboard/app/main.py` and its template.

### 5. Evidence script

- **Script:** `scripts/analyze_pair_drift.py <UF folder> <AGC2 extracted folder>`, standard library only, not in any make
  target. It prints the tables above.
- **Partner rule:** the same as Design 1, 2 and 4, by importing `pair_reference` (with the fast-change skip).
  - UF: partner lag 0, 10 and 20 s at 30 s (to compare with the tables), plus one full interval: 30 s at 30 s, and
    5 min after resampling to 5 min.
  - AGC2: slab 2 is paired one row earlier (a full 5-minute interval, the aligned-clock case), and also with a 1 s
    offset.
- **Tolerance:** it must match this doc's numbers for lags 0-20 s to within 1 flagged reading per pair (a tie in medians
  can move one). The full-interval rows are new: if they flag more than the worst existing row of that table by over
  50 %, or add cards on a pair that had none, the builder stops and reports before going on.
- **Data:** AGC2 is already under `datasets/raw/`; its part is required. UF is not on the maintainer's machine; it is
  downloaded from Mendeley (link in `LICENSE_AND_ATTRIBUTION.md`) only after the owner's yes for that download. If the
  UF folder is missing, the script reports it skipped, prints the AGC2 tables only, and the UF numbers above stand as
  measured for v2. The build does not wait for the UF run.

### 6. Simulator results

No simulator or scorer code changes; the results change because the engine now sees pairs.

- **`slow_drift.json`, expected after this build** (minutes from the drift's start tick to the card):

| Drift | Today | After |
|---|---|---|
| air on `climate-1`, −0.1 °C/min, ticks 240-320 | MISSED | caught or `caught_on_partner`, by minute 35 |
| air on zone B's single device | MISSED | MISSED (no partner; the docs say so) |
| humidity on `climate-2`, −0.5 %RH/min, ticks 400-480 | MISSED | caught or `caught_on_partner`, by minute 25 |
| moisture on `substrate-2` (`substrate_moisture_pct`), −0.5 %/min, ticks 560-640 | MISSED | caught or `caught_on_partner`, by minute 21 |

  - Both outcomes pass. Which device takes the card is close to a coin flip in a two-probe zone (Edge cases), so the
    drift log records it per drift, and the builder also runs `slow_drift.json` on seeds 1-20 offline and reports the
    share of drifts carded on the drifting device. This number is for the owner; it is not a pass/fail gate.
  - Everything else in its must-hold list still holds: 0 false alarms, 0 wrong cards, the stuck humidity caught, the
    humid night caught.
  - A pair flag on `climate-2` during `climate-1`'s stuck humidity (ticks 700-740), possible after the stuck flag lapses
    (Edge cases), would give a card on the partner of the faulted device: the scorer counts it `caught_on_partner`,
    not as a false alarm or a wrong card.
- **Sweeps:** seeds 1-80 of both slice 3 layouts: 0 false alarms and 0 normal frames with a card, and slice 3's
  accepted sensor-check rate rule still met. A pair flag on a normal frame shows up as a sensor-check frame there, so
  no new scorer count is needed; the builder lists any pair texts found in those frames.
  - **If a sweep fails** (a false alarm, a card on a normal frame, or the rate rule broken by pair flags), the builder
    does not change limits, seeds or layouts. It stops and reports the seed, device, field, `moved` and the readings
    around it; the owner decides (a real gap for the punch list, or a design change).
- **`multi_device.json` and every older scenario:** byte-identical (no pairs).
- **The game:** unchanged (one device per zone; no Space re-upload). `spaces/try-to-fool-pomona/vendor/` is gitignored
  and rebuilt by `make fool-space-check`, so nothing under it is committed. The Pyodide parity run covers single-device
  scenarios only, so it does not exercise the pair path; the in-process tests do.

### 7. Docs

- **`SENSOR_TEMPORAL_CHECKS.md`:** a new row. "Still MISSED" becomes: air, humidity and moisture drifts are caught with
  a second device in the zone (each at least every 5 minutes) and missed with one; substrate temperature drifts stay
  missed.
- **`SENSOR_QUALITY_REASONER.md`:** the `pair` entry and the check.
- **`HARDWARE_EVENT_CONTRACT.md`:**
  - A second device in a zone, reporting at least every 5 minutes, is how drift detection works.
  - Use one zone per shared air space.
  - Retention is per zone (already there): with two devices each keeps about half.
  - Calibrate only the probe that was wrong.
- **`FAKE_GREENHOUSE.md`:** `slow_drift.json`'s new outcomes; the game still has one probe per zone.
- **This doc:** the drift log.

### Files

- `services/core/app/{store,outcome_feed,trusted_baseline,config}.py`.
- `services/model-router/app/{sensor_quality,main}.py`.
- `examples/simulators/inprocess_pomona.py`.
- `scripts/analyze_pair_drift.py` (new).
- Tests in `services/core/tests`, `services/model-router/tests`, `examples/simulators/tests` and `scripts/tests`.
- Docs above.
- With 4b only: the files listed there (including the dashboard). Without 4b there is no dashboard change: the alert
  row and the device column already show what this check produces.

## Edge cases

- **Which probe crosses first (two probes):** each device is judged against the other's reading from before its own
  sample time. For a steady ramp on device 1, device 1's difference has moved by the drift now, and device 2's by the
  drift one reading ago. That one-reading step (0.05 °C, 0.25 %RH or 0.25 % at 30 s) is far smaller than ordinary noise
  (the layouts' wander, 0.3 °C and 1.0 %RH), so which device crosses first, and gets 3 in a row first, is close to a
  coin flip. Design 6 reports the share.
- **When the good probe is flagged first:** its veto stops it serving as a partner, so the drifter is not judged and
  stays trusted on its own device row.
  - The card lands on the good probe. The text names both devices and asks for a meter on both.
  - With 4b, the zone treats the field as "can't confirm", so no advice uses the drifted value. Without 4b, slice 2's
    rule switches the zone to the drifted probe until the grower checks. Open question 1.
- **Shared sudden change:** skipped on the reading where it happens (Design 4); judged normally from the next reading,
  once the partner has reported it too. A ramp that keeps stepping faster than the skip limit is skipped throughout.
- **Three or more probes:**
  - The drifter is compared with the median of the others, so it crosses first.
  - The others see it as one of several partners. With three probes, the median of two partners is their mean, so a
    good probe crosses only at twice the drift. Once the drifter is vetoed, the others' partner set changes, and they
    are not judged again until 12 offsets against the new set exist.
- **Partner silent, dropped, unjudged or vetoed:** not used. One missed packet is covered by the 2.5-interval age. With
  no usable partner there is no judgement, and the flag clears; the alert engine raises only on 3 flagged readings in
  a row, so an alert not yet raised is delayed, and one already raised stays until its clear window (15 min, the
  default `sensor_check` uses) passes. Open question 6. The silent-probe rule (`docs/design/silent-probe.md`) and the dashboard's device health report a quiet
  device. In `slow_drift.json`, `climate-1` has no partner during `climate-2`'s dropout (ticks 900-940).
- **Noise at the limit:** there is no separate clear threshold. A reading just under the limit between flagged ones
  restarts the 3-in-a-row count, which can delay a card by a few readings. The `slow_drift.json` times allow for it.
- **A stuck probe after its stuck flag lapses:** the router's stuck flag ends after about 4.5 minutes, once the frozen
  run fills the 11-packet window (slice 3 drift log, item 5). The frozen probe then becomes a usable partner again. If
  the real value moves by more than the limit while it stays frozen, the pair check flags one of the two. This is a
  bonus catch, not a goal; no test depends on it.
- **Slow devices:** a stream reporting less often than every 5 minutes is not paired (Design 1). A 15-minute substrate
  node (`HARDWARE_EVENT_CONTRACT.md`) would also need 3 hours for 12 offsets and 45 minutes of flags for a card. Open
  question 5.
- **Different sample rates:** each reading uses its own `PAIR_MAX_AGE_S`. A 30 s probe paired with a 5 min one is
  judged only when a partner reading is fresh enough (75 s), so mostly not; the 5 min probe is judged against the 30 s
  one at every reading.
- **Start-up, after a calibration, after a partner-set change:** no judgement until 12 offsets.
- **Constant offset** (position, shade; `climate-2`'s 0.4 °C and −1.5 %RH in `slow_drift.json`): fine. Only changes
  count.
- **Slow drifts:** a drift slower than about limit / 2 h (air 0.025 °C/min) moves the reference before it crosses, and
  is caught late or not at all. The docs give the rates that are caught.
- **Glitch:** one reading over the limit is vetoed. It gives no card unless it lasts 3 readings (the Digilog cards).
- **Both probes drift alike:** not caught, the same as a single probe.
- **Placeholder moisture:** a constant placeholder is a flat partner and is skipped (Design 1).
- **A device joins a zone:** the partner set changes for the device already there, and both collect 12 offsets before
  either is judged.

## Done when

- [x] **Before starting:**
  - The owner has approved this doc and answered open questions 1, 3, 5, 6 and 7 (they change what is built).
  - Slice 3 is merged into `main`.
  - The builder captures current outputs to compare against, in a folder outside any scratchpad, with slice 3's
    capture scripts (outside the repo; their location is in `private/AGENT_HANDOFF.md`; if they are gone, the
    builder writes the same captures by hand):
  - every offline scenario including `multi_device.json` and `slow_drift.json`, and seeds 1-80 of all three layouts;
  - `make real-replay` guard values and `make fault-replay` output;
  - `make abstention-eval` (frozen report) and the game checks;
  - the `slow_drift.json` offline run time and the sweep time per seed.
- [x] **Router unit tests:**
  - Flag at the limit, none just under, for each of the four fields.
  - A negative move gives "lower", a positive one "higher"; units and 1-decimal numbers as specified.
  - With no `pair` the output is unchanged; a malformed `pair` gives 422 at the endpoint and is ignored by
    `apply_persistent_checks` called directly.
  - One partner and three partners give the right text; a 128-character device id gives a text of at most 260
    characters; the pair text is first in `checks`.
  - A shared move (both probes) is not flagged.
  - A device carrying both moisture names gets one text.
  - With 4b: `pair_disagreement_fields` is present only when the pair check flagged a field.
- [x] **Core tests:**
  - The `pair` entry from Core's store path equals the in-process path's entry for the same rows, judged in order.
  - A partner reading without a trust row is not used.
  - Calibrating either probe restarts the pair, and neither restarts the other device's own reference.
  - A vetoed partner reading is not used; a flat partner is skipped.
  - The alias pair matches.
  - A partner reading at the same sample time as the own reading is not used.
  - A partner going quiet in a three-device zone changes the partner set, and offsets against the old set are not used.
  - A one-device zone sends a request byte-identical to today's and runs no partner query.
  - With `multi_device_zones` off, or with `pair_check` off, there is no `pair` entry and no partner query.
  - **Fast-change skip:** a shared one-reading step of 1.5× the limit on both devices (clocks aligned, 30 s and 5 min)
    gives 0 pair flags on either device; an own step just under `PAIR_FAST_STEP` is judged, one at it is not.
  - **Cadence boundary:** an own median interval of 300 s is paired, 301 s is not.
  - **Three devices:** an even partner count uses the mean of the middle two; a partner going quiet changes the set,
    and offsets against the old set are not used.
  - `PAIR_MIN_N` after a calibration restart: 11 new offsets give no entry, 12 give one.
  - A partner missing for one packet keeps the pair (2.5-interval age); missing for three intervals drops it.
  - The calibration lookup compares parsed datetimes (a `performed_at` with a +02:00 offset sorts correctly).
  - With 4b: the zone snapshot marks a field `disagree` and vetoed while any candidate's latest row has it in
    `pair_fields`, whichever device that is, and clears it when none does.
- [x] **Two-device in-process test** (hand-built readings, not a simulator scenario):
  - Readings are built from integer steps (value = base + i × step, never by adding repeatedly), so the limit is
    crossed on a known reading.
  - Air drift of 0.1 °C/min on device 1, starting after 2 h of clean readings at 30 s, no noise: flagged within
    30–33.5 minutes of the drift's start, a `sensor_check` alert, and the alert's `detail` starting with the pair text.
    With no noise the drifter crosses first (its move is one reading ahead), so the alert is for device 1.
  - The same readings with a heat ramp added to both devices: no sensor flag.
  - An alert already raised stays raised when the partner then goes quiet, until its clear window passes.
- [x] **`slow_drift.json`:** the table in Design 6 holds, offline and in one stack run with screenshots of the alert
  row and the zone view after the flag (with 4b: the "probes disagree" tile). The seeds 1-20 share of drifts carded on
  the drifting device is reported. (Offline seed 23 meets all three targets, item 17. The seeds 1-20 share is reported
  below: 40 of 60 drifts on the drifting device, 67 %. The 8-hour stack run agrees with offline, and the 4b stack demo
  showed the alert row and the "probes disagree" tile; both are in the final checks below, and item 28 is the bug the
  run found.)
- [x] **Sweeps:** seeds 1-80 of both slice 3 layouts: 0 false alarms, 0 normal frames with a card, slice 3's rate rule
  met, and the sweep time per seed under 2× the baseline. (Item 19: all 80 seeds of each layout are byte-identical to
  the baseline, so the counts and slice 3's rates are unchanged; time per seed 0.98 to 1.25 times the baseline.)
- [x] **Byte-identical:** every captured output above except `slow_drift.json`, its sweep and the game build-info line
  is byte-identical after the build, apart from timing fields. (Rule 0 in the final checks: 31 identical, 1 expected
  difference, 3 differences all explained: the game's zip size, the `fault-replay` wall-clock fields and the control
  page screenshots; items 19 and 26.)
- [x] **Evidence:** `scripts/analyze_pair_drift.py` reproduces the AGC2 table within the stated tolerance, and its
  full-interval rows are within the stated bound. The UF part runs only if the owner has said yes to that download.
- [x] **Gates**, on the Python 3.11 pinned environments (the main checkout's older venvs are 3.9): `make test-local`,
  `local-validation`, `fool-space-check` (with Pyodide parity), `test-checker`, `test-demo`, `fault-replay`,
  `real-replay` (unchanged) and `abstention-eval` (frozen report unchanged) all pass. (All passed on the 3.11
  environments; the Core group is 852 after item 28.)

## Later (not this build)

- **Real-data pair pass in `make real-replay`:** replay AGC2's slab 1 and slab 2 as two devices of a zone, with guards
  from the table above. Today `agc2_packets` reads slab 1 only, and the replays run in parallel workers, so this is
  new harness code of its own size (open question 7).
- **The game:** a second probe in zone A, so the game's Drift trick can be caught. This needs a Space re-upload, so it
  waits for its own owner yes.
- **Dashboard:** a pair-difference line on the pair tile. The alert row already says it; add the tile line only if
  growers miss it.

## Out of scope

- Pairs across zones.
- Single-probe drift.
- pH and EC pairs.
- Substrate temperature (open question 2).
- Streams slower than one reading per 5 minutes (open question 5).
- The browser checker (`persistent.js`), which judges one uploaded stream.
- Consistency inside one device (humidity against temperature).
- Space re-uploads.

## Decisions

Owner, 2026-11-16, "Yes, as recommended" (every open question takes its recommended answer):
1. The first device to cross gets the card, and the zone treats the field as "can't confirm" while probes disagree:
   **Design 4b is built.**
2. Substrate temperature stays out.
3. Limits 3.0 °C, 10 %RH, 8 %; the listed real-data false cards are accepted.
4. The label is `baseline_drift_possible` (reused).
5. Only streams reporting at least every 5 minutes are paired.
6. When the partner goes quiet the flag clears; a raised alert stays until its clear window passes.
7. The real-data pair pass in `make real-replay` is a later piece of its own.

Not covered by this approval: downloading the UF chamber dataset (its own yes), commits, merges and pushes.

## Open questions (answered above; kept for the record)

1. **Two probes disagree: what does the zone use?** In a two-probe zone it is close to a coin flip which probe takes
   the flag and the card.
   - **Recommended: the device that crosses first gets the card, and the zone treats the field as "can't confirm"
     (Design 4b).** No advice uses either value until the grower checks, whichever probe was flagged. It costs a small
     Core and dashboard change (a trust column, the snapshot rule, a tile line).
   - Alternative A: first to cross gets the card, and the zone view switches to the other probe (slice 2's rule, no
     extra build). When the good probe was flagged, the advice uses the drifted value until the grower checks.
   - Alternative B: flag both devices. This needs vetoed partner readings, so any fault on one probe (stuck, spike)
     would also withhold the healthy one, and gives two cards for one fault.
2. **Substrate temperature:** leave it out (recommended), or add `substrate_temperature_c` to the calibration schema
   (`CalibrationEvent.measurement`, `MEASUREMENT_FIELDS`, the Space's calibrate button) so a pair can be cleared?
3. **Limits and their false cards.** The limits come from one chamber and one greenhouse, and the worst real pair
   crosses them: about 1–3 false air cards and 1 humidity card per 107 days on one pair, and 4 moisture glitch cards
   per 157 days in one compartment (Evidence, "Accepted false cards").
   - Recommended: 3.0 °C, 10 %RH, 8 %, and accept those cards, each of which says "check both probes". At 3.5 °C the
     air drift is caught at 35 of 40 minutes, which leaves no room for the card.
   - Revisit when a real greenhouse with two air probes in one zone appears.
4. **Label:** reuse `baseline_drift_possible` (recommended: no change to rules, the gate, the JS mirrors or the scorer),
   or a new `probe_disagreement`?
5. **Slow devices:** pair only streams reporting at least every 5 minutes (recommended: the evidence is at 30 s and
   5 min, and a 15-minute node would need 45 minutes of flags for a card, longer than the game's 40-minute drift), or
   make the window and age limit scale with the cadence so the 15-minute substrate node is paired too?
6. **Partner goes quiet:** the flag clears and comes back with the partner (recommended: no hidden state, and an alert
   already raised stays until its clear window passes), or carry the last pair verdict while no partner is usable?
   Carrying needs Core to remember each stream's last pair verdict, which nothing stores today.
7. **Real-data pair pass:** later, as its own piece (recommended: it is new harness code, and the router tests, the Core
   tests, the evidence script and `slow_drift.json` carry the behaviour), or in this build?

## Changes v4 → v5

From a fresh re-review of v4 (READY WITH FIXES).
- **Fast-change skip** (Design 4): with a strictly earlier partner, a sudden shared change (irrigation pulse, humidity
  step) would have flagged both probes for up to two readings and withheld the event. A reading whose own step is at
  least a third of the limit is now not judged. The evidence script gains full-interval lag rows (30 s and 5 min) with
  the skip; tests pin it.
- **Evidence honesty:** the headroom claim now separates three partners (1.06×) from one partner (crosses the limit),
  and the UF air and humidity false cards are listed as accepted beside the Digilog ones (open question 3).
- **Coin flip:** which probe takes the card in a two-probe zone is close to a coin flip; the doc no longer contradicts
  itself. Design 6 accepts caught or `caught_on_partner` and reports the share over seeds 1-20.
- **Open question 1** now recommends Design 4b: the zone treats a disagreeing field as "can't confirm".
- **Calibration lookup:** the zone's newest 200, parsed and compared as datetimes (the measurement is in the payload).
- **Gate:** the pair path runs only when `device_fields_for(event)` is not None, so a pair flag always has `detail`;
  `zone_pair_devices` uses the same time rule.
- **`pair_reference`:** `current` and `lapse_s` named; the window ends at the current reading; the partner cap counts
  usable devices; the median of an even count; the flat test as of the current reading; `PAIR_MIN_N` enforced inside
  the shared function.
- **Kill switch:** `pair_check` setting in Core and the in-process engine.
- **Prerequisites:** owner answers before the build; capture scripts' location in the private handoff; the UF part of
  the evidence script waits for the owner's yes to download and does not block the build.
- **Tests added:** shared step, cadence boundary, three devices, restart, missing packet, raised alert with a quiet
  partner, calibration time zones; integer-step readings.
- **Sweep failure:** stop and report, never retune.
- **Gates** on the Python 3.11 pinned environments.

## Changes v3 → v4

From two fresh reviews (gaps; fit with the code), both READY WITH FIXES.
- **No store id:** a partner reading must be strictly earlier than the own reading and judged (have a trust row).
  This replaces the store-id rule, which Core could not get (`SensorEvent` has no id), and makes the result
  independent of same-tick storage order. The simulator's one-sided order is gone.
- **Unjudged partner readings** (dropped or failed by the feed) are not used; equality with the in-process engine is
  stated for in-order judging, with tests for both.
- **Partner set stored with each offset**, so a partner going quiet or coming back does not mix bases.
- **`PAIR_MAX_AGE_S`:** 2.5 intervals (one missed packet tolerated), clamped 60–750 s, computed once per reading.
  **Supported cadence:** at most 5 minutes (open question 5).
- **Window and signature:** `window_s` and the lapse are inputs; the anchor is `stream_baseline`'s; partner rows from
  the window start minus the age; offsets and partner readings both start at the pair start (`≥`, as `_Walk.push`).
- **Rounding:** 6 places in the output.
- **Alias:** which name is used for a device carrying both, as partner and as judged device; one text per alias group.
- **Flat partners skipped** (hydroponic moisture placeholder).
- **Check text:** names both devices, has units and the usual difference, cuts device ids to 32 characters, stays under
  300 characters (`MAX_KNOWN_CHECK_CHARS`), goes first in `checks`, and drops `CALIBRATION_HINT`.
- **No clear threshold**, and why; flag clearing when a partner goes quiet is open question 6.
- **Store:** `zone_pair_devices`, `zone_partner_history` (zone-wide index, real bound) and `zone_newest_calibration`;
  `multi_device_zones` off turns the check off.
- **In-process:** buffer only in zones with pairs, bounded by count; run time recorded.
- **Validator:** 422 on a malformed `pair`, matching the existing validator; `PAIR_MIN_N` enforced by Core only.
- **`persistent.js`** named as the mirror the check is not added to.
- **Expected device** per `slow_drift.json` drift; the stuck-lapse case scored `caught_on_partner`; no new scorer count
  (slice 3's rate rule covers pair flags); times counted from the drift's start tick.
- **Vendor folder** is gitignored; the Pyodide parity run does not cover the pair path.
- **Docs:** substrate temperature stays in "Still MISSED"; retention line already exists.
- **Accepted false cards:** the Digilog compartment's 4 glitch cards, stated.
- **Real-data pair pass** moved to "Later" (open question 7); the evidence script gains 30 s and 60 s lag rows.

## Changes v2 → v3

- Per-device history (v2's Design 0) was built in slice 1; stage 2 (simulator devices, scorer by device,
  `slow_drift.json`) was built in slice 3. Both are now listed under "What already exists".
- How the user meets it, edge cases, expected `slow_drift.json` outcomes and Done when were rewritten on top of slices
  1-3.

## Changes v1 → v2

- Per-device history added; simulator and scorer moved to a stage 2 outline; substrate temperature dropped; the
  calibration scope became a zone query; `PAIR_MIN_N` set to 12; one pure function shared by Core and the in-process
  engine; `PAIR_MAX_AGE_S` defined; vetoed, retained and clock-invalid partner rows excluded and the partner count
  capped; per-device cards with the partner named in the text; aliases; the `main.py` validator; lag re-measured;
  baselines first in Done when.

## Drift log

Built 2026-11-21 on branch `slow-drift-pair-check` from d08ed00 (slice 3 merged), uncommitted. Baselines were captured on the pristine commit on 2026-11-16/17. Evidence folders (baselines, checks and sweeps, evidence-script output) are on the maintainer's machine, outside the repository; their paths are left out here.

1. Row key (Design 2): the rows `pair_reference` takes use the key `timestamp`, which is what `stream_history` returns, not the doc's `sample_time`.
2. Pair start (Design 3): a helper `pair_start_time(calibrations, field, now)` in `trusted_baseline.py` picks the newest calibration that covers the field through `MEASUREMENT_FIELDS` and is not later than the current reading, comparing parsed times; it reuses the existing `_latest_calibrations`.
3. Own-row walk bound (Design 2): `pair_reference` walks the own rows newest first and stops once it is past the window and has seen 13 sample times (`PAIR_INTERVALS` + 1), so the up-to-5000-row history is not parsed. About 0.5 ms per call.
4. Duplicates (Design 1): when a device has several rows at one sample time, the last row given wins; own duplicate sample times are de-duplicated the same way.
5. Flatness and the pair start (Design 1): the own stream's flat test ignores the pair start. Partner readings before the pair start are not usable, so they are not counted for a partner's flat test either.
6. Both moisture names (Design 1): a device counts as carrying both names only when both are finite on the current reading. It is then judged under the first name in `ALIASES` order, and the second name returns None.
7. Fast-change skip, float boundary (Design 4): it runs after the cadence check, and the step is compared with the limit directly, without rounding. A step of exactly a third of the limit (for example 8/3) can compute just under it in floating point and then be judged.
8. Partner query index (Design 2): `zone_partner_history` runs one query per device on the existing per-device index `sensor_events_sample_device`, which SQLite picks, instead of one zone-wide query on `sensor_events_sample_zone`. The bounds are the same (the window, and `trust_baseline_scan_limit` rows per partner).
9. `zone_pair_devices` runs in every multi-device zone (Design 2, "Only in multi-device zones"): it is one cheap query and returns [] when `multi_device_zones` is off. The partner-history and calibration queries run only when it returns a device. A one-device zone still sends the same request as before.
10. Stdlib pin: the test that keeps `trusted_baseline.py` standard-library-only now allows `statistics` (the median of an even count). It still runs in Pyodide.
11. Router interpretations (Design 4):
    - A reading with two moisture names that both carry `pair`: the first flagged name, in the dict's order, speaks, and only it goes into `pair_disagreement_fields`.
    - `pair: null` is treated as absent (200), like the other optional keys. Numbers are strict: a numeric string or a bool makes the entry malformed.
    - `partners == 1` with `partner_device: null` gives the text "the median of 1 other probes" (Core always sets `partner_device` when `partners == 1`).
    - There is no cap on huge but finite numbers in the text; Core rounds them, and real values are small.
    - The router keeps its own alias map (`PAIR_ALIAS_GROUPS`) and its own copy of the limits. A pin test checks them against Core's `PAIR_DRIFT_LIMITS` and that `PAIR_FAST_STEP` is a third of each limit.
    - The pair check runs first in the per-field loop, and its text is inserted at the head of `checks`.
    - Router tests 592 + 12 xfail became 655 + 12 xfail; `make test-checker` passed (parity unchanged).
12. Design 4b (zone view), as built:
    - "Marked vetoed for the router" is done in the dashboard's device checks, not in the snapshot: the fields with `disagree` go into `known_vetoed_fields`, and the labels and checks of every live probe that took the flag reach the zone's badge even when that probe does not supply the field. The snapshot keeps `others[].vetoed` as the real per-device flags.
    - The `disagree` test counts live judged devices that carry the field or its moisture alias. A stale or pending row does not count.
    - The zone view has no moisture tiles (air, humidity, pH, EC and VPD only). A moisture disagreement vetoes the field and puts the pair text on the badge, with no tile line.
    - The trust line for a disagreeing field reads "Can't confirm: humidity (climate-1) not used" (the first candidate is named) with a partial badge; no new wording was added. The air and humidity tiles show both values and "probes disagree: check both with a meter".
    - The page script lives inside `services/dashboard/app/main.py`, so the doc's "and its template" is not a separate file.
    - The old-database column check in `test_zone_snapshot.py` was updated for the third new column (`pair_fields`).
13. In-process engine (Design 2): `PairBuffer` is a standard-library class that keeps judged rows per zone (`keep_s` is `DEFAULT_WINDOW_S` plus `PAIR_MAX_AGE_MAX_S`, passed in; at most 4000 rows per zone, the oldest overall dropped).
    - Pairing rule: a zone is paired when `pair_check` is on, the zone is multi-device and at least two of its devices carry ANY pair field, not necessarily the same one. The first build therefore ran wasted `pair_reference` calls in the `multi_device.json` layout (no common field); the speed-up in item 15 skips a field when no other device has a series for it. The pairing rule itself is unchanged.
    - Start-up difference: the buffer starts when the zone becomes paired. In the first 2 hours after that, the JOINING device's entries can differ from Core's (`n` up to 2 higher in Core, the first entry up to 2 readings earlier, the median off by less than a quarter of the limit in the test). The first device's entries are equal. With a full buffer the equality is exact: 1217 and 1794 entries equal in the test.
    - Not covered by a test: the cadence and flat paths when pre-buffer rows would matter (an irregular cadence early on, or a stream going flat in the first window).
    - Test-writing notes: a wave step under 0.01 C per reading trips the router's flatline check; the wave phase was chosen so the drifter crosses first; a shared ramp can advance the drift flag by up to 0.25 C.
14. Tests: Core group 750 to 852 (849 at the gates run, plus the 2 endpoint tests of item 28; the pair tests, the in-process equality tests and the zone-view tests, 7 dashboard tests and one node tile case among them), scripts 149 to 166 (including the evidence script's 6), simulator tests 178 (unchanged), router 655 + 12 xfail.
15. Series fast path and cost (Design 2): the first in-process build made `slow_drift.json` score 2.6 times slower (1.48 s to 3.82 s), over the 2 times budget. `pair_reference` gained optional keyword-only `own_series` and `partner_series` (per-device, per-field series, oldest first). The rows path that Core uses is unchanged; both share one core built on `bisect`, with an early return when there is no partner and early-exit flat tests. New helpers: `pair_row_entry`, `_as_series`, `_flat`. `PairBuffer` keeps the per-device, per-field series and rebuilds them after a late insert or a cap drop. Measured per seed after the change: slow_drift layout 1.57 s (1.21 times the baseline 1.298 s), `multi_device` 0.91 s (0.94 times), default 0.75 s (0.96 times); the `slow_drift.json` scenario score time 1.995 s (1.24 times 1.603 s). Under the 2 times budget. Outputs byte-identical to before the speed-up (scenarios and 5 seeds of each of 3 layouts), and the old and new `pair_reference` agreed on 12,000 random cases.
16. Evidence script (Design 5) results, AGC2 only:
    - The UF part was skipped: there is no UF data on the maintainer's machine, and the download needs the owner's yes. The script reports it skipped, and the UF numbers in this doc stand as measured when the check was designed.
    - Lag 0 reproduces within tolerance: Digilog 48 flagged readings of 45,311 (doc: 47) and 4 cards; 0 in the other five compartments. Small differences at the range edges: own p99.99 for Reference slab 2 is 12.9 (doc: 12.7); the pair p99.99 for IUACAAS is 3.1 (doc: 3.2); Digilog's p99.99 is 24.7 (doc: 24.5). These look like percentile-method noise. The trailing median needs at least 12 readings; with 6, Digilog flags 64.
    - The three full-interval clock cases for moisture, flagged readings and cards, both slabs: the five other compartments 0 and 0 in every case. Digilog: slab 2 stamped 300 s earlier, 63 flagged and 2 cards; stamped 1 s earlier, 52 and 4; identical stamps ("aligned", added by the builder, because "one row earlier" with strictly earlier partners is not a symmetric 5-minute lag), 63 and 1. The bound is 1.5 times 48 = 72 flagged readings: all within it, and no card was added where there had been none.
    - Observation: the fast-change skip does not veto the skipped reading, so the first reading of a glitch stays usable as a partner, and the other slab is then flagged too (Digilog slab 2: 25 to 26 flags). In the real system the router's step check (8 % moisture step) would veto such a glitch first; the script runs the pair rule alone. A 3-reading glitch can give 2 flags and no card, because the first reading is skipped.
    - Exit codes: 2 bound exceeded, 1 no data, 0 ok. About 70 s of CPU. 6 tests.
17. `slow_drift.json` offline (seed 23, 1000 ticks), minutes from the drift's start tick:
    - Air on `climate-1` (ticks 240-320): caught on the drifter, `climate-1`, at +32.0 min (the doc's bound: 35).
    - Air on zone B's single device: MISSED, as the design expects (no partner).
    - Humidity on `climate-2` (ticks 400-480): caught on the drifter, `climate-2`, at +21.5 min (bound: 25).
    - Moisture on `substrate-2` (`substrate_moisture_pct`, ticks 560-640): `caught_on_partner` at +17.5 min; `substrate-1` took the card (bound: 21).
    - The stuck humidity and the humid night are still caught; 0 false alarms, 0 wrong cards.
18. The 94 partner flags (reading level): normal frames with a sensor check outside tails went from 11 to 105 in `slow_drift.json`, 0 of them with a card. The 11 are the baseline's own noise. The 94 are all pair flags on the partner of a device faulted at that moment (88) or in its recovery tail (6): air on `climate-2` at ticks 308-321 (10), humidity on `climate-1` at 447-481 (35), moisture on `substrate-1` at 588-641 (51). There is no pair flag when nothing is faulted in the zone. Why: in a two-probe zone the flag locks onto one probe. A flagged reading is vetoed and stops serving as a partner, so the other probe has no usable partner and is not judged; it stays unvetoed and keeps serving as the partner, so the flagged probe stays flagged (the Edge case "When the good probe is flagged first"). The lock can switch once from the drifter to the good probe: when one drifter reading lands just under the limit, it is not vetoed, the good probe is judged against it and flagged, and from then on the good probe holds the flag while the drifter goes unjudged. In `slow_drift.json` seed 23 the good probe was flagged in near-continuous runs (humidity on `climate-1` about 35 readings, ticks 447-481; moisture on `substrate-1` about 51, ticks 588-641), with the drifter as partner reading 14-20 %RH low. The drifter's card, already raised, stays until its clear window passes; no wrong card resulted (the scorer: 0). With 4b both cases read "probes disagree". The scorer counts these frames as normal because its tail rule is per faulted device. No card came from any of them.
19. Sweeps and every other scenario: byte-identical to the baseline. All scenarios match except `slow_drift.json` (expected). Seeds 1-80 of the default, `multi_device` and `slow_drift` layouts: all 80 seeds of each were byte-identical, so no pair flag appears on any fault-free seed. The sweeps were rerun on the finished build, after the speed-up of item 15: all 80 seeds of each of the three layouts are again byte-identical, so no pair flag appears on any fault-free seed. Per seed (sim + score seconds), baseline to final: default 0.786 to 0.770 (0.98 times), `multi_device` 0.971 to 0.948 (0.98 times), `slow_drift` layout 1.298 to 1.622 (1.25 times); the `slow_drift.json` scenario score 1.603 to 2.005 s (1.25 times). Under the 2 times budget.
20. Baseline of record (d08ed00): suites sims 178, scripts 149, router 592 + 12 xfail, Space 77, datasets 14 + 1 skipped, Core group 750, automation 206; the capture log shows 0 failed steps. Per seed (sim + score seconds): default 0.054 + 0.732, `multi_device` 0.075 + 0.896, `slow_drift` 0.110 + 1.188; `slow_drift.json` offline sim 0.151 and score 1.603 s, all four drifts MISSED (noticed at the end, +2460 s), stuck caught at +90 s, humid night at +1830 s. The stack smoke and validation baseline was captured while the Mac slept (the smoke run took 5 h 20 min) and gave verdicts that differ from slice 3's with identical code, so it was set aside; a rerun under caffeinate was made on 2026-11-21 (its result is not recorded in this log).

21. The UF part of `scripts/analyze_pair_drift.py` is a stub: with a folder present it prints "UF not implemented without the data" and what the doc expects. The UF tables (Design 5) are still to be written once the owner says yes to the download.
22. The dashboard tile drops the "(not used)" suffix on the other probe's value while `disagree` is set (pinned by the node case in `services/dashboard/tests/check_rendering.cjs`).
23. The dashboard keeps its own copy of the moisture alias map (`services/dashboard/app/main.py`, `ALIASES`), now pinned to Core's by a test in `services/dashboard/tests/test_dashboard_api.py`.
24. The in-process tests live in `scripts/tests/test_inprocess_pair.py` (they need the router venv), not in `examples/simulators/tests` as the Files list says; the simulator suite count is unchanged (178).
25. The "no noise" in-process test uses a shared triangle wave of +-0.5 C on both probes: a noiseless stream is flat and not judged, so a literal "no noise" stream cannot be judged.
26. The game's vendored `pomona.zip` grew from 141 KB to 150 KB (the new engine code is vendored); the game's 77 tests, Pyodide parity and three recorded sessions are unchanged. Design 6 expected only the build-info line to differ.
27. The partner's own cadence is not tested: only the judged stream must report at least every 5 minutes; a partner reading is usable when it is recent enough for the judged stream (2.5 of the judged stream's median intervals, 60 to 750 s). A 10-minute partner can serve a 5-minute stream when its reading is fresh.

28. Bug found by the stack run, fixed: `GET /v1/sensors/zone-snapshot` dropped each field's `disagree` key. The response model `ZoneSnapshotField` (`services/core/app/schemas.py`) had no such attribute, so the model removed the key, and the dashboard never showed "probes disagree" in a real stack. Core's store set `disagree` and `pair_fields` correctly. The tests missed it because the 4b Core tests called the store directly and the dashboard tests used hand-made snapshots, so nothing went through the endpoint. Fix: `disagree: Optional[bool] = None` on `ZoneSnapshotField`. It is absent unless set, and the endpoint leaves unset keys out, so every other answer is unchanged. Two endpoint tests were added in `services/core/tests/test_pair_zone_view.py`: one fails without the fix (KeyError 'disagree'), the other pins the unchanged shape. Core group 850 to 852 with this fix (849 at the gates run, see the counts below). The 8-hour stack run below used the code from before this fix for the snapshot answer; its alerts and cards do not depend on it.

Final checks:
- Seeds 1-20 of `slow_drift.json`, offline (report only, not a gate). Caught by the pair check while the drift lasted (card text starting "pair check:", before 40 minutes): air 12 of 20 (10 on the drifter, 2 on the partner), humidity 17 (15 + 2), moisture 17 (15 + 2); 46 of 60 paired drifts, 40 on the drifting device (67 %), 6 on the partner (10 %). The other 14 were noticed only at the end: 10 carded at 40.0-40.5 minutes with the snap-back step text (the scorer calls them `caught` because the label run began before the drift's last reading, but they are not pair-check catches: air seeds 5, 6, 11, 17, 20; humidity 6, 13, 18; moisture 4, 12) and 4 `caught_at_recovery` (air 3, 16, 19; moisture 5). By the Design 6 target minute: air 12/20 by 35, humidity 15/20 by 25, moisture 17/20 by 21. Zone B's single probe: 20/20 missed (expected). All 20 seeds: 0 false alarms, 0 unmatched, 0 wrong cards, 0 normal frames with a card, stuck and humid night caught. Air is the weak field: the drift reaches 4.0 C at 40 minutes against a 3.0 C limit, so the noise between the two simulated air probes decides whether it crosses in time. Seed 23 (the scenario) meets all three targets.
- Stack run of `slow_drift.json` (8 hours real time, seed 23, 1000 ticks; Core, router and automation on their own ports; started 2026-11-21; the code from before item 28 for the snapshot answer, no reload, so alerts and cards are unaffected by the fix). The stack and an offline replay of the same events agree on every episode:
  - Air on `climate-1`: caught on the drifting probe after 64 samples (32.0 minutes at 30 s, the same as offline); the alert is `sensor_check` with the text "pair check: air_temperature_c on climate-1 is 3.0 °C lower than usual against climate-2 (now -3.6, usually -0.5)". The flag cleared before the drift ended (noise at the 3.0 C limit), and the snap-back at the end put the step text on the active alert. The partner had a short pair flag after the snap that raised no card.
  - Humidity on `climate-2`: caught on the drifting probe after 21.5 minutes. Moisture on `substrate-2`: caught on the partner (`substrate-1`) after 17.5 minutes. Zone B's single air probe: missed (noticed only at the end). Stuck humidity on `climate-1`: caught after 90 s. Humid night: caught (`high_humidity_fan`) after about 30 minutes. `climate-2`'s dropout: not published, as designed.
  - 0 false alarms, 0 unmatched events, 0 wrong cards, 0 normal frames with a card.
  - The ticks ran slow between ticks 240 and 400 (45 to 62 s instead of 30) because the machine was busy. The engine works in sample time, so the verdicts are counted in samples and match offline; the air catch took 52 minutes in wall time for that reason.
  - The run's own full-page screenshots were too short to show the alert table (the page grows to about 16,000 px with history). The alert rows were captured as JSON, and full-height captures were added by hand.
- 4b stack demo with the fixed code (2026-11-21, about 65 minutes, own ports; a copy of `slow_drift.json` with only the humidity drift on `climate-2`, ticks 30-110):
  - The snapshot carried `disagree: true` for humidity at ticks 80, 92 and 104 and dropped it after the drift (tick 120).
  - The dashboard's humidity tile showed both values ("65.2 %", "also climate-2: 48.67 %") and "probes disagree: check both with a meter". The trust line read "partial — Can't confirm: humidity (climate-1) not used". The alert row read "active · climate-1 · sensor_check" with "pair check: humidity_pct on climate-1 is 11.6 %RH higher than usual against climate-2 (now 15.4, usually 3.8). Check both with a meter; calibrate only the one that was wrong."
  - In this run the card landed on the good probe (the two-probe coin flip), scored `caught_on_partner`. Stack and offline agree: 0 wrong cards, 0 false alarms.
- Rule 0 (compare of every captured output against the d08ed00 baseline, 2026-11-21, Python 3.11 venvs, 0 failed steps): 31 identical, 1 expected difference (`slow_drift.json`), 3 differences, all explained. Game `fool-space-check` and Pyodide logs: only the vendor line and `pomona.zip` 141 to 150 KB (77 tests, parity OK, three recorded sessions byte-identical). `fault-replay`: only the 24 `max_detector_latency_ms` wall-clock fields. Control page screenshots: pixels only (page HTML, catalog, state and scenario are identical). Identical: all three 80-seed sweeps, every scenario except `slow_drift.json`, abstention eval and regeneration (frozen report unchanged), `real-replay`, `test-checker`, `test-demo`, stack smoke and stack validation. Timing: see item 19.
- Gates on the Python 3.11 pinned environments (`make test-local`, `local-validation`, `fool-space-check` with Pyodide parity, `test-checker`, `test-demo`, `fault-replay`, `real-replay`, `abstention-eval`): all passed. No baseline test id is missing; 259 new results, all in the pair test files. Counts: simulators 178, scripts 166, router 655 + 12 xfail, Space 77, datasets 14 + 1 skipped, Core group 849 at that run (852 after item 28), automation 206.
- `mkdocs build --strict` (mkdocs-material 9.7.7, fresh Python 3.11 venv): exit 0, run 2026-11-21 before the last edit of this log; rerun after it by the orchestrator.
- Reviewer's drift check (2026-11-21): verdict no code bug; the code matches the doc. Its findings and what was done:
  - Item 18's wording was too loose ("now and then"): reworded to the lock mechanism.
  - Items 21-27 were added: the UF stub, the tile suffix, the dashboard alias copy and its pin test, the in-process test location, the "no noise" wave, the zip size, the partner cadence.
  - The cadence wording in `SENSOR_TEMPORAL_CHECKS.md` and `HARDWARE_EVENT_CONTRACT.md` was changed to match the code.
  - Stale text was updated in `PROJECT_STATUS.md` and `examples/simulators/README.md`.
  - A small pin test was added for the dashboard's moisture alias map.
