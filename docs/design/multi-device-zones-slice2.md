# Multi-device zones, slice 2: one zone view built from every device

Status: **approved by the owner 2026-11-14** ("Yes, as recommended": open questions 1-3 answered as recommended).
Draft v3 (2026-11-14).
- v1 was reviewed by two context-free reviewers (gaps; fit with the code). Both said READY WITH FIXES.
- v2 applied every fix and was re-reviewed by a third context-free reviewer: READY WITH FIXES.
- v3 applies those fixes (list at the end).
- The doc proceeds on the recommended answer to each open question unless the owner says otherwise.

Parent: `docs/design/multi-device-zones.md` (slice 1 built and merged: 8c23e0c, merge 9c90800). This doc answers every
bullet of that doc's "Slice 2 (outline" section; each answer is marked **(O-n)** (list at the end).
Unblocks: slice 3 (simulator, scorer, game) and `docs/design/slow-drift-pair-check.md` (needs the alert `detail` line).

## Goal

After slice 1, Core judges each device of a zone on its own. The dashboard still shows the zone's newest packet. In a
zone with a climate node (air, humidity) and a substrate node (pH, EC, moisture) that packet flips every few seconds:

- the tiles show air and humidity, then "--" for them and pH/EC instead;
- the trust line, "Guarded risk status", the twin and the agronomist note describe one device only;
- "Evaluate current risk" reasons on one device, and its suggestions are tracked against the whole zone;
- alerts show no device and no check text, so the pair check has nowhere to say which probe to check.

Slice 2 gives the dashboard **one zone view**. Each field comes from one device, each device's own sensor-check result
is carried in, and every view reasons on that view. Alerts get a Device column and a `detail` line.

**Rule 0: a zone with one device behaves exactly as today.** Everything new switches on only when Core says the zone
is multi-device (`zone_multi_device`, slice 1 section 1.1). In a single-device zone:

- every request body the dashboard, Core and the automation engine send is byte-identical;
- the page renders identically;
- the only differences are the additive keys and columns in the allow-list of 2.10.

## How the user meets it

1. Zone A has `climate-1` (air, humidity) and `substrate-1` (pH, EC, moisture). The grower opens the zone.
2. **Tiles** (air, humidity, pH, EC, VPD; there is no moisture tile today and slice 2 adds none) all show a value at
   once. Under each value a small line says where it came from, for example `climate-1 · 40 s`. When two devices carry
   a field (a pair), the tile shows the zone's value and `also climate-2: 23.6 °C`.
3. **Sensor trends** draw one line per device in each card, against sample time, so a 5-minute device is not pushed
   out by a 30-second one.
4. **Sensor trust line** describes the zone:
   - `trusted · All readings passed the sensor check (2 devices)`, or
   - `partial · Can't confirm: humidity (climate-1) not used; EC not reported by any device in this zone`.
5. `climate-1` (one packet every 30 s) is quiet for 15 min, longer than its stale limit (2.1: the larger of
   `ZONE_STALE_AFTER_S`, default 10 min, and 3 × its own interval). Its readings leave the zone view and
   the trust line says `Can't confirm: air temperature, humidity not reported: no reading from climate-1 for 15 min`.
   A substrate node that reports every 15 min is not stale at 15 min: its limit is 45 min.
   When **every** device is quiet, today's line appears: `no reading from this zone for 15 min`.
6. `climate-1`'s humidity probe sticks. Core's feed flags it on `climate-1`'s own history (slice 1). The zone view
   carries that result in:
   - the Sensor quality badge says `stuck_value`;
   - humidity is "not used";
   - "Evaluate current risk" creates the `sensor_check` suggestion.
7. **Alerts** have a Device column. Under a sensor alert a grey `detail` line shows the router's own check text, for
   example `inspect humidity_pct: near-zero variance may indicate a stuck or clipped probe`. Later, the pair check
   will put `verify humidity_pct ... on device-2` there.
8. The grower approves an EC suggestion. Only `substrate-1`'s readings decide whether it recovered; `climate-1`'s clean
   readings no longer confirm it.

## Build order

One owner OK, three coder briefs, each with its own tests and review:

- **2a, alert `detail` (2.6).** Automation engine, plus Core's feed sending it. Independent of the rest; it is the only
  part the pair check needs.
- **2b-1, Core and router (2.1-2.3).** Core snapshot and `event_trust` columns, router `known_*` and the shared
  chain's `device_fields`.
- **2b-2, dashboard views and outcomes (2.4, 2.5, 2.7).** `_zone_view()`, device checks, the six views, outcome
  `sources`. If it runs long, the first cut is the dashboard's own judging of pending devices (2.4): a pending device
  would then carry no vetoes and the trust line would say `<device>: not yet checked`.
- **2c, page (2.8).** Tiles, trends, trust line, Device columns.

## Design

### 2.1 Core: the zone snapshot (O-1)

New endpoint `GET /v1/sensors/zone-snapshot?farm_id=&zone_id=&stale_after_s=0`.
- `farm_id` and `zone_id` are required; without them it answers 422.
- `stale_after_s` is an integer ≥ 0; 0 means no staleness filter.

**Is the zone multi-device?** Exactly the slice-1 answer for the zone's latest event:
`device_fields_for(latest_event(farm, zone)) is not None`.
- If not (or `MULTI_DEVICE_ZONES=0`, or there is no event), the response is `{"multi_device": false}` and nothing else.
- The dashboard then takes today's single-device path.

**Devices:**
- Each `device_id` with a `__packet__` row in `device_fields` for the zone, whose `last_seen` is within
  `retention_days` of Core's clock. This is the slice-1 window, on wall-clock time because there is no reading to
  anchor on.
- For each device, `latest = latest_event(farm, zone, device)`. A device with no latest event is left out.
- Devices are listed in `device_id` order.

**Per device** the response holds:

| key | value |
|---|---|
| `device_id` | as stored |
| `event` | the latest packet (`model_dump(mode="json")`, without `source`) |
| `sample_time`, `received_at` | of that packet |
| `age_s` | Core's clock minus the sample time, never negative (the same rule as the dashboard's `reading_age_s`) |
| `interval_s` | the median gap between the sample times of this device's last 6 live packets; `null` with fewer than 2 |
| `stale_limit_s` | `min(3600, max(stale_after_s, 3 × interval_s))` (just `min(3600, stale_after_s)` when `interval_s` is null); 0 when `stale_after_s` is 0. The 3600 s cap matches the router's 60-min `stale_reading` veto (drift item 35) |
| `stale` | `stale_limit_s > 0 and age_s > stale_limit_s` |
| `device_fields` | `device_fields_for(latest)`: the fields this device is expected to carry (slice 1, 1.3) |
| `supplied` | the fields this device supplies to the zone view (below) |
| `trust` | see "Trust per device" below |

**Trust per device, and "pending" without a ceiling.** Core looks up the `event_trust` row for
(farm, zone, device, `latest.timestamp.isoformat()`). That is the same key `add_trust` writes.
- **Row found:** `{"status": "judged", "trust_verdict", "vetoed_fields", "data_quality_labels",
  "safe_next_checks"}`.
  - The last two come from new columns (2.2). For a row written before them they are `null`.
  - `trust_verdict` is for display and tests only. The merge (2.4) uses vetoes, labels and checks.
- **No row:** `{"status": "pending"}`. There is no time limit.
  - "Pending" means only that Core has not recorded a verdict for this packet.
  - The feed may be behind, failed, or disabled (empty router or automation URL). In the last two cases the device
    stays pending forever.
  - The dashboard then judges the packet itself (2.4). Core never waits and never guesses.

**Fields: one device per field.** For each of `schemas.READING_FIELDS`:

1. **Candidates:** the non-stale devices whose latest packet holds a finite number for the field. A device's older
   packets are never used, so a probe that stopped reporting looks missing instead of showing an old value.
2. **Order:** by the `first_seen` of the device's `device_fields` row for this field, then by `device_id`.
   - This is stable, so two devices that both carry air temperature do not flip the tile at every packet.
   - The outline said "the newest packet". With a pair, that flips between the two probes, which is the problem this
     slice removes (open question 1).
   - `first_seen` comes from a new query; `device_fields_for` returns names only.
   - Zones backfilled by slice 1 have backfill first-seen times, so their first order may look arbitrary. It is stable
     from then on.
3. **Zone value:** the first candidate in that order, except one whose judged trust row vetoes this field. If every
   candidate vetoes it, the first one is used, and the router is told it is vetoed (2.4).
   - So a stuck primary probe does not hide a good second probe.
   - Pending devices count as not vetoing.
4. **Output:**
   `fields[f] = {"value", "device_id", "sample_time", "age_s", "others": [{"device_id", "value", "sample_time",
   "vetoed"}]}`.
   - `others` lists the other candidates in the same order.
   - `vetoed` is true when that device's judged row vetoes the field.
   - A field with no candidate is absent.

`supplied` (per device) is the fields whose `fields[f].device_id` is that device.

**Missing fields are not Core's call.** Core returns present fields only. Whether a missing field matters is decided by
the router's one expected-fields implementation when the dashboard sends the snapshot (2.5).

**Context fields** (`crop`, `growth_stage`, `system_type`, `weather`, `zone_area_m2`, `crop_kc`, `npk_target`):
Core fills schema defaults (`tomato`, `flowering`, `greenhouse_substrate`). A climate node that never sends
`system_type` therefore looks like `greenhouse_substrate`. One rule covers every context field:

1. **Candidates:** the value in each non-stale device's latest packet, or in every device's when none is non-stale.
2. Drop `null`. Drop the schema default when any candidate differs from it.
   - Accepted limit: a device that really sends `tomato` against one that sends `lettuce` is not reported as a
     conflict, because Core cannot tell a sent default from a filled one.
3. Take the value from the device with the newest sample time; ties by `device_id`.
4. If more than one distinct value remains after step 2, add the field name to `context_conflicts`.

The rule produces three things:
- `context`: a dict;
- `context_source`: `{field: device_id}`;
- `context_conflicts`: a sorted list.

`weather` and `npk_target` compare as JSON with sorted keys. When every device is stale, `context` is still returned,
but nothing uses it, because `sensor` is null.

**The snapshot packet** (`sensor`) is what the dashboard sends to the router as the zone's reading.
- It holds `farm_id`, `zone_id`, the context fields, and `fields[f].value` for each present field.
- `timestamp` is the newest `sample_time` among supplying devices.
  - The oldest would let one slow device put `stale_reading` on the whole zone when the stale filter is off.
  - The newest matches today's "latest packet".
  - Field values can be up to `stale_after_s` older than it. VPD may combine an air and a humidity reading of
    different ages, accepted when they are within the stale limit.
- `device_id` is **absent**: the snapshot is no single device. `sources` (below) says who supplied what.
- `sensor` is `null` when no field has a candidate: every device is stale, or none is left.

**Sources:** `sources: {field: [device_id, ...]}`.
- For a present field: the device that supplied it.
- For a field in any listed device's `device_fields` but absent from the snapshot: every device expected to carry it,
  for example a stale or silent one.

**Zone expected fields:** `zone_device_fields` is the sorted union of every listed device's `device_fields`, stale
devices included.

**Response:** `{"multi_device": true, "farm_id", "zone_id", "stale_after_s", "devices": [...], "fields": {...},
"sensor": {...} | null, "sources": {...}, "zone_device_fields": [...], "context": {...}, "context_source": {...},
"context_conflicts": [...], "newest_age_s": <smallest device age_s, or null when no device is listed>}`.

A zone silent for more than 7 days can be multi-device (slice 1 judges its latest event on that event's own
`received_at`) while `devices` is empty. Then `sensor` and `newest_age_s` are null and the dashboard takes slice 1's
newest-packet path (2.4), which shows today's stale line.

**Partial packets:** a device that sends one probe per packet (allowed: `SensorEvent` needs one reading) shows only
the fields in its latest packet; its other fields look missing until they come round again. Accepted; the contract
says a device should send all its probes in each packet.

**Why a per-device stale limit:** the dashboard's `ZONE_STALE_AFTER_S` (600 s) is today only a banner threshold for
the whole zone. Slice 2 uses it to leave a device out of the zone view, so a slow node (a substrate node every 15
min) would be left out most of the time. The limit therefore grows with the device's own interval (open question 3).
`ZONE_STALE_AFTER_S` stays the only setting.

**Cost:** one `device_fields` query (fields with first_seen), one `latest_event` and one `event_trust` lookup per
device. There is no device cap yet; per-device retention and the cap are a slice-1 follow-up on `private/ISSUES.md`.

### 2.2 Core: `event_trust` keeps the sensor-check result (O-3)

So the zone view can show a stuck probe that only a device's own history reveals, the feed stores the labels with the
verdict.

- **New columns:** `data_quality_labels` and `safe_next_checks` (TEXT, JSON lists).
  - They are added to the `CREATE TABLE`.
  - On an existing database they are added at start-up with `ALTER TABLE ... ADD COLUMN` when missing. Existing rows
    keep `NULL`.
- **Write:** `add_trust(event, verdict, vetoed, labels=None, checks=None)` is rewritten with named columns: an
  `INSERT INTO event_trust (farm_id, ...)` whose `ON CONFLICT ... DO UPDATE` sets the verdict, the vetoed fields and
  both new columns.
  - Today's call is a positional 7-value `INSERT`, which fails once the table has more columns.
  - The feed passes `sensor_quality.data_quality_labels` and `safe_next_checks`.
  - It writes them in every zone. This changes the database only; nothing anyone receives changes in a single-device
    zone.
- **Unchanged:** `stream_history` and the trusted reference, which read `vetoed_fields` only.

### 2.3 Router: `known_vetoed_fields` and the carried labels (O-7)

The snapshot has no history, so on its own the router can only check the snapshot's ranges and plausibility.
Persistent faults (stuck, noisy, drift) reach it only through the carried device results. This is intended.

- **Request keys:** `PipelineEvaluateRequest` and `SharedReasonerChainRequest` gain three optional keys, absent by
  default.
  - `known_vetoed_fields: list[str]`: fields a device's own check did not trust. Names not in
    `KNOWN_SENSOR_FIELDS` are dropped, as for `device_fields`.
  - `known_data_quality_labels: list[str]`: the validator keeps at most 50 strings matching `^[a-z_]{1,64}$`.
  - `known_safe_next_checks: list[str]`: at most 20 strings of at most 300 characters each; others are dropped.
- **Function arguments:** `evaluate_pipeline(...)` and `run_shared_reasoner_chain(...)` gain the same three keyword
  arguments (default `None`), so the in-process engine and the Pyodide copy keep working unchanged.
- **One merge, before the gate:** a new `trust_gate.merge_known_checks(quality, sensor, vetoed, labels, checks)` runs
  right after the sensor-quality reasoner and before `apply_sensor_veto`.
  - **Labels:** each known label is added (`add_unique`), except:
    - `GLOBAL_VETO_LABELS`: a stale packet of one device must not veto the whole zone, so the dashboard turns it into
      vetoed fields instead (2.4);
    - labels that start with `missing_`: the router decides missing fields on the snapshot itself.
  - **`suspect_fields`:** each known vetoed field that the sensor holds a value for is added. A field the snapshot does
    not hold is the router's own missing-field call, not a veto.
  - **`safe_next_checks`:** known checks not already present are appended. `continue routine monitoring` is removed
    when any other check is present.
  - **Review and rationale:** `human_review_required` becomes true if anything was added. `rationale` becomes the
    existing "Sensor packet needs verification ..." text if labels were added to a clean result.
  - **Provenance:** `quality["from_device_checks"] = {"data_quality_labels": [...], "vetoed_fields": [...]}` lists what
    was added. The key is absent when nothing was.
- **Semantics the outline asked for:**
  - **Reason string:** the gate keeps one reason. A carried veto is a suspect field like any other, so it is named in
    `"<fields> failed the sensor check and were not used"`. Where it came from is in `from_device_checks`.
  - **Companion groups:** yes. A carried `ph` veto also vetoes `previous_ph`, as a local one does.
  - **`cannot_confirm`:** yes. If every expected field ends up vetoed, carried or local, the verdict is
    `cannot_confirm`.
- **Without the keys** the output is byte-identical: no merge runs and no new key appears.
- **Parity:** the JavaScript gate mirrors (`spaces/*/trust_gate.js`) are not touched. The merge runs only with the new
  keys, which no parity case sends, so `make test-demo` and `make test-checker` stay byte-identical.

### 2.4 Dashboard: building and judging the zone view (O-1, O-3)

**One zone view per refresh.** A new helper `_zone_view()` is used by `overview()` and by every view.
- It calls `/v1/sensors/events` (as today). When `zone_multi_device` is true, it also calls `/v1/sensors/zone-snapshot`.
  - The snapshot call uses the scope's farm and zone, or the latest event's when unscoped (as slice 1 does).
  - It passes `stale_after_s = max(ZONE_STALE_AFTER_S, 0)`. That is the only staleness setting (O-1).
- The snapshot is cached in-process for 5 s, keyed by (farm, zone), with an injectable clock for tests.
  - Within one cache life every view sees the same zone view, and a page refresh makes one or two snapshot calls
    instead of six.
  - This is not a guarantee: a slow view (the explanation has a 30 s timeout) can see a newer zone view than the one
    before it. Each view's result names its own `sources`, so the page never mixes them silently.
- `pipeline()`, `risk()`, `safety()`, the twin and `explanation()` call `_zone_view()`, not `overview()`. Today they
  all call `overview()`; that would add the trend fetches to every view.
- **`/api/overview` does not judge pending devices.** It returns the snapshot as is, so it never waits on the router.
  The views that need device checks (pipeline, risk, twin, explanation) run them.
- **Trend fetches live in `/api/overview` only:** `/v1/sensors/events?farm_id&zone_id&device_id=<d>&limit=120` for up
  to 8 devices, in `device_id` order (120 covers an hour at 30 s).

**`OverviewResponse` gains:**
- `zone_snapshot: Optional[dict]`;
- `device_events: Optional[Dict[str, List[event]]]`: device id to that device's events, oldest first;
- `zone_snapshot_error: Optional[str]`.

All three are `null` in a single-device zone.

**Overview fields in a multi-device zone:**
- `latest_age_s` is the snapshot's `newest_age_s`, so "no reading from this zone" appears only when every device is
  quiet.
- `latest_event` stays the zone's newest packet, for old clients.

**Which path a view takes:**

| situation | path |
|---|---|
| single-device zone | today's path, untouched |
| multi-device, snapshot `sensor` present | the zone-view path (2.5) |
| multi-device, snapshot `sensor` null (every device stale) | slice 1's multi-device path: the newest packet, that device's own history and `device_fields`. The page then shows today's stale line and "Pipeline result from the last reading" exactly as for a stale single-device zone. |
| multi-device, snapshot call failed | slice 1's multi-device path. `zone_snapshot_error` is set and the page says `Zone view unavailable: showing the newest packet (<device>)`. |
| snapshot says `multi_device: false` (the zone just turned single-device) | today's single-device path |

**Device checks** (a new helper, `device_checks(snapshot)`) turn each device into what the router needs. Only devices
with a non-empty `supplied` list count; a stale device supplies nothing.

- **Judged device:**
  - `known_vetoed_fields` gets its `vetoed_fields` ∩ `supplied`.
  - `known_data_quality_labels` gets its `data_quality_labels`, but only when that intersection is not empty or it
    vetoed nothing. A device whose only flagged probe is not in the zone view therefore does not put `stuck_value` on
    the zone badge.
  - `known_safe_next_checks` gets its `safe_next_checks` under the same condition.
  - A row from before 2.2 (labels `null`) carries its vetoes only.
  - If its labels include one of `GLOBAL_VETO_LABELS`, all its supplied fields are vetoed.
- **Pending device:**
  - The dashboard judges that device's latest packet itself: `/v1/pipeline/evaluate`, `mode: rules_only` (as Core's
    feed does), its own history and its `device_fields`.
    - The history is fetched per device (`limit=24`, `earlier_samples`), not taken from the trend data.
  - Its `gate.vetoed_fields` ∩ `supplied` and its `sensor_quality` labels and checks are then used as for a judged
    device.
  - The result is posted to the alert monitor (as slice 1's branch does), with `detail` (2.6), through
    `feed_alert_monitor`, which gains an optional `detail` argument.
    - **Except a retained packet** (`event.mqtt_retained` true). Core's feed never judges retained packets (retained
      state never proves live availability), so such a device stays pending; the dashboard judges it for the view
      but does not post it to alerts or outcomes.
  - `PipelineResponse` gains `dashboard_judged: [device_id, ...]` (`null` otherwise), so the page can mark them.
  - This check has no `stream_baseline`, so it is weaker than Core's (no persistent stuck check). The trust line says
    `(checked by the dashboard)` for that device.
- **Pending device whose call fails:** all its supplied fields are vetoed, with the check
  `sensor check for <device> could not run; verify its readings`.
- **Limits:**
  - Pending devices are judged concurrently, with the existing 10 s router timeout each.
  - Results, failures included, are cached by (farm, zone, device, sample time), at most 256 entries. A success is
    kept until evicted. A failure is kept for 5 s (the snapshot cache life), so it is retried at most once per
    refresh.
  - Two dashboard workers keep separate caches, so they can post the same reading twice. The monitor ignores the
    second post of a sample time, so this is harmless.

### 2.5 Dashboard: each view on the zone view (O-2)

On the zone-view path every view below uses the snapshot's `sensor` (S) instead of `overview().latest_event`.
"Masked" means S with the carried `known_vetoed_fields` removed; the dashboard never sees the router's own gate result
before these calls.

| view | today in a multi-device zone (slice 1) | zone-view path |
|---|---|---|
| `/api/pipeline` | the newest packet, its own history, `device_fields`; posts to alerts | S; `history: []`; `device_fields` = `zone_device_fields` (so a field no device ever carried is not missing, and the tomato reasoner gets `not_expected_fields` as in slice 1); no `expected_fields`; the three `known_*` keys. **Does not post to the alert monitor**: alerts stay per device (Core's feed, or 2.4's fallback). `PipelineResponse` gains `sources` (`null` otherwise). |
| `/api/automation/evaluate` | the pipeline result | `automation_evaluate()` adds `sources` to the context (2.7); `pipeline()` sets `sensor_event_id` to the hash of S plus `sources`. |
| `/api/risk` (shared-chain) | the newest packet | S, the three `known_*` keys, and `device_fields` = `zone_device_fields`. `SharedReasonerChainRequest` and `run_shared_reasoner_chain` gain `device_fields` and narrow with `narrow_to_device` exactly as `evaluate_pipeline` does (no explicit `expected_fields`), so the risk panel and the trust line agree on what is missing. Absent: byte-identical. |
| `/api/safety` (safety-triage) | the newest packet | S unmasked. The triage gate reads only `sensor_quality` and the command, and the dashboard sends no `sensor_quality`, so the reading never changes its answer. S is sent only so the request names no single device. |
| `_digital_twin_preview` | the newest packet; its own `expected_fields` = the fields in the forecast end state | state = masked S. The guarded call sends `device_fields` = `zone_device_fields` and **no `expected_fields`**, so a field missing from the snapshot is reported missing instead of silently dropped. It also sends the `known_*` keys. The twin needs air, humidity or moisture; a masked S with none of them gets the twin's 422 and shows "Digital Twin unavailable", as a single-device packet without them does today. |
| `/api/explanation` | the newest packet + risk result | masked S, plus the zone-view risk result |

The combined risks the outline noted (heat on one node, dry substrate on the other) now reach the zone views and
"Evaluate current risk". They do **not** reach alerts, which stay per device (out of scope).

### 2.6 Alerts: `detail` (O-6)

**Storage:**
- `alert_states` and `alert_events` each gain `detail TEXT`, added at start-up with `ALTER TABLE ... ADD COLUMN` when
  missing (the pattern already used for `consecutive`).
- `AlertObserveRequest` gains `detail: Optional[str]` (at most 500 characters).
- `AlertMonitor.observe(...)` gains `detail=None` and `data_quality_labels=()`. `main.py`'s `observe_alerts` passes
  both from the request; the request already carries `data_quality_labels`.

**Which alerts get it:** a rule's text is updated on a reading when the rule matched on this reading **through a
data-quality label** (its `match_any_labels` ∩ `data_quality_labels` is not empty) and `detail` is non-empty.
- Today that is `sensor_check` and `sensor_flatline`.
- A condition alert (`high_ec_alert`) never gets sensor check text.

**State handling:**
- `_set` gains `detail` and every call site passes it. A new non-empty text replaces the stored one; otherwise the
  stored text is carried forward. No transition (pending → active, active → recovering, recovering → active) blanks
  it.
- A rule that matches while already `active` makes no `_set` call today. A new `UPDATE ... SET detail=?` covers it
  when the text changes.
- A recovering row has no match, so it keeps its text.
- The `raised` event copies the row's text. The `recovered` event has none.
- `events()` selects `detail` with its other columns.
- `AlertState` and `AlertEvent` gain `detail: Optional[str] = None`, an additive `null` key in every zone.

**Who sends it:** Core's feed sends `detail` built like this:
- the reading's `sensor_quality.safe_next_checks` without `continue routine monitoring`;
- joined with `"; "`;
- cut to 500 characters, ending in `…`.

It is sent only when `device_fields_for(event)` is not `None` (a multi-device zone; Rule 0). The dashboard's pending
fallback (2.4) does the same. Empty text is not sent.

**Hostile text:** `detail` is free text from a client.
- The engine strips every control character (Unicode category Cc) and cuts to 500 characters including
  the trailing `…`.
- It is stored and returned on alerts only; it is never copied into suggestions, advice cards or any prompt.
- The page renders it through `escapeHtml`.
- `services/automation-engine/tests/test_prompt_injection.py` gains `detail` (and the dashboard context's `sources`)
  among its planted strings (2.11).

**Same text for two rules:** `sensor_check` and `sensor_flatline` can match on one reading; both get the reading's
whole text. Accepted.

**Known limit:** if the dashboard's fallback posts a reading before Core's feed does, the feed's post of that sample
time is ignored (the monitor ignores a repeated sample time), and that one reading's text is the dashboard's weaker
one. This race already exists for every dashboard post today and is not fixed here. The pair-check doc must restate
it, because it relies on this text.

**Shown:** under the alert's message, in multi-device zones only (open question 2).

### 2.7 Outcome tracking with `sources` (O-4)

Today `observe_outcomes` filters by the suggestion snapshot's `device_id` (`own_device`). A zone-view suggestion has
none, so every device's readings would count, and `climate-1`'s clean readings could confirm an EC suggestion.

- **Context:** the evaluate context gains `sources: {field: [device_id, ...]}` from the snapshot (2.1). Single-device
  contexts are unchanged.
- **Label to field map:** a new `automation-engine/app/outcome_fields.py` maps the watched labels to fields. These
  were checked against `tomato_reasoner.py` and `nutrient_ph_ec.py`.
  - `high_ec`, `low_ec` → `ec_ms_cm`.
  - `high_ph`, `low_ph` → `ph`.
  - `heat_stress`, `cold_stress` → `air_temperature_c`, `substrate_temperature_c` (the router raises both from either
    reading).
  - `fungal_pressure` → `air_temperature_c`, `humidity_pct` (raised from humidity and from VPD).
  - `water_level_risk` → the three moisture fields.
  - Every other label (the sensor-check labels): the suggestion's own `vetoed_fields` and `missing_fields`.
- **`observe_outcomes` with a non-empty `sources`:**
  - A reading counts only if its `device_id` is in the union of `sources[f]` over the watched fields found in
    `sources`.
  - A reading with `device_id` null is skipped.
  - If that set is empty, **no** reading counts. Nobody is expected to carry the watched field (or the suggestion names
    no field), so the suggestion cannot confirm itself and ends `unconfirmed` or `not_recovered` at its deadline, by
    today's rule.
  - **Several counting devices** (a `fungal_pressure` suggestion whose air and humidity come from two devices; a heat
    suggestion with air on one and substrate temperature on another):
    - the evidence keeps `last_sample_time` **per device** (`last_sample_by_device`), so a slower device's reading is
      not dropped because a faster device's later reading arrived first. Old evidence without it uses today's single
      `last_sample_time`;
    - readings form one streak in arrival order; any flagged reading from a counting device resets it;
    - it is `confirmed` only when the streak reaches `required_clean_readings` **and** every counting device has sent
      at least one clean reading inside that streak. Three clean packets from the fast device alone are not enough.
- **Without `sources`:** today's rule (`own_device`) applies unchanged.
- **Advice cards:** `advice_cards.py` adds `evidence["sources"]` only when the context has it.

### 2.8 Overview page (O-5)

All of this applies when `zone_snapshot` is present; otherwise the page is today's.

- **Tiles:**
  - The value comes from `fields[f]`. Under it: `<device> · <age>` (`ageText`).
  - For each entry in `others`, a line `also <device>: <value>`, with ` (not used)` when `vetoed`.
  - VPD uses the zone view's air temperature and humidity. When they come from different devices its line says
    `air <d1>, humidity <d2>`.
- **Context conflicts:** for each field in `context_conflicts`, a status line
  `Devices disagree on <field name> (using <value> from <device>)`.
- **Sensor trends:**
  - Each card plots one polyline per device that carries the field, from `device_events`, with a legend of device ids.
  - x is sample time over a fixed window: the 60 min before the newest plotted point in the card. y uses one scale
    shared by every line in the card.
  - `sparkline(values, color)` becomes `sparkline(series, color)`, taking a list of `{label, points:[{t, v}]}`.
    - One series with no times draws exactly as today, by index.
    - Every line uses the card's colour; device n (in `device_id` order) uses dash pattern n from
      `["", "6 3", "2 3", "8 3 2 3"]`, cycling. The legend shows each device id next to a short sample of its pattern.
    - A device with fewer than 2 points in the window is listed in the legend as `<device>: not enough data`.
  - **VPD card:** one line per device that carries both air temperature and humidity (computed per packet, as today).
    If no device carries both: `No device carries both air temperature and humidity`.
  - The min/max/latest text is per device.
  - With more than 8 devices, the rest are named as `not plotted`.
- **Trust line wording** (what `trustLine()` really produces). `trustLine(verdict, fields, missing, zone)` gains an
  optional `zone` argument (the snapshot). Without it, the text is exactly today's. With it:
  - trusted: `All readings passed the sensor check (<n> devices)`, where n is the number of devices that supplied a
    field;
  - each vetoed field: `<name> (<device>) not used`, with the device from `sources`;
  - a missing field whose expected device is stale: `<names> not reported: no reading from <device> for <age>`;
  - any other missing field: `<names> not reported by any device in this zone`;
  - a device judged by the dashboard (2.4): ` (checked by the dashboard)` after its name;
  - parts are joined with `; ` after `Can't confirm: `, as today. A field that is both missing and vetoed is said once,
    as missing.
  - The "Integrated guarded pipeline" and "Guarded risk status" lines use it. Which devices were judged by the
    dashboard comes from `PipelineResponse.dashboard_judged`.
  - **Advice cards** carry only `evidence.sources`, not the snapshot. Their variant: each vetoed field is named with its
    device (`<name> (<device>) not used`), missing fields say `not reported by any device in this zone`; nothing about
    ages or dashboard judging.
- **Device columns** (multi-device zones only, open question 2):
  - the Alerts table gains a Device column after State;
  - the Alerts "Recent:" text line gets `(<device>)` after each rule id;
  - the Recent sensor events table gains a Device column after Time.

### 2.9 Files

- **Core:** `services/core/app/{store,main,outcome_feed,schemas}.py`: the snapshot query, the `event_trust` columns,
  the endpoint, `detail`, the response model.
- **Router:** `services/model-router/app/{main,pipeline,shared_chain,trust_gate}.py`.
- **Automation engine:** `services/automation-engine/app/{alerts,main,store,advice_cards}.py`, and a new
  `outcome_fields.py`.
- **Dashboard:** `services/dashboard/app/main.py` (Python and the page script), and
  `services/dashboard/tests/check_rendering.cjs`.
- **Tests:** in `services/{core,model-router,automation-engine,dashboard}/tests`.
- **Docs:**
  - `HARDWARE_EVENT_CONTRACT.md`: the zone view, staleness, pair tiles;
  - `services/dashboard/README.md`: remove the slice-1 "known limits" that are now fixed;
  - `SENSOR_QUALITY_REASONER.md`: the `known_*` keys;
  - the parent doc's slice-2 outline, pointed at this doc;
  - this doc's drift log.
- **Vendored copies:** the Space vendors the router. `make fool-space-check` rebuilds them locally (gitignored; slice 1
  drift note 4). No re-upload.
- **Not touched:** the in-process engine, simulator, scorer and game (slice 3); `/api/history`, `/api/devices`, probe
  health, audit; the JavaScript gate mirrors.

### 2.10 What a single-device zone sees (Rule 0)

- **Unchanged bytes:**
  - every request body sent to the router, safety triage, twin, advisor and automation engine;
  - every router and automation output;
  - the rendered page.
- **Allow-list of additive differences** (the byte-identical check ignores exactly these):
  - `/api/overview`: `zone_snapshot`, `device_events` and `zone_snapshot_error`, all `null`;
  - `/api/pipeline`: `sources: null` and `dashboard_judged: null`;
  - `/v1/automation/alerts`, `/v1/automation/alerts/observe` and `/api/alerts` items: `detail: null`;
  - new columns in `event_trust`, `alert_states` and `alert_events`.

  This is the same kind of exception slice 1 recorded (its drift note 8).

### 2.11 Tests that change (intended)

- **`services/dashboard/tests/test_dashboard_api.py`:** the slice-1 multi-device tests (the `zone_multi_device: True`
  fakes around lines 800-871, including `_two_device_pipeline` and `test_overview_passes_the_two_core_keys_on`).
  - Their fake Core returns one events payload for every path, so the new snapshot call breaks them.
  - Rewrite them on the path-aware fake, keeping what they assert: the newest-packet path now runs only when every
    device is stale or the snapshot fails.
- **`services/automation-engine/tests/test_prompt_injection.py`:** around line 297 it asserts that planted strings
  appear only at the `farm_id`, `zone_id` and `device_id` paths of alert items. It gains `detail` as an allowed path
  (stripped of control characters) and `sources` in `dashboard_context()`.
- **Checked, unchanged:** `services/core/tests/test_trusted_baseline.py:404` reads `event_trust` with `SELECT *` by
  column name, so the new columns do not break it.
- The builder lists any other test that changes, with the reason.

## Edge cases

- **Feed disabled:** every device stays pending, and the dashboard judges each one (2.4).
- **Feed behind by a few ms:** see the known limit in 2.6. This race is not new.
- **One device stale, one live:** the stale one supplies nothing. Its expected fields are missing (they are in
  `zone_device_fields`), and the trust line names it (2.8). The router verdict follows its usual rule.
- **Slow device:** a substrate node every 15 min gets a 45 min stale limit (2.1), so it stays in the zone view. A
  device with fewer than 2 live packets has no interval and uses `ZONE_STALE_AFTER_S` alone.
- **All devices stale:** the slice-1 newest-packet path (2.4) gives today's stale line and "Pipeline result from the
  last reading".
- **Stale filter off (`ZONE_STALE_AFTER_S=0`, demos, replays):** no device is ever left out, and old values are used as
  current. That is what "off" means today.
- **Pair, one probe stuck:** whichever device it is, the zone uses the other probe (2.1 step 3). The tile shows the
  stuck one as `also ... (not used)`, and its own device alert has the Device column and `detail`.
- **Pair, both stuck:** the first is used and vetoed; the field is "not used".
- **Pair, the zone's probe drops out:** the other device's value is used. The dropped device's `missing_*` is not
  carried (2.3); its own `sensor_check` alert says so.
- **Field no device has ever carried** (no moisture probe in a substrate zone): it is not in `zone_device_fields`, so it
  is not missing. The zone can be `trusted`. This is slice 1's rule applied to the zone.
- **A device that sends only context** (`weather`): it supplies no reading field, so it adds context only.
- **Context conflict:** shown (2.8). The router gets the value the rule picked.
- **Old `event_trust` rows** (before 2.2): their vetoes are carried and their labels are not. An old stuck flag is
  then visible as "not used" without the `stuck_value` badge until the next reading is judged.
- **A retained latest packet for a device:** used like any latest packet (Core's own `latest_event` rule).
- **The zone turns single-device:** Core's test flips, and the next refresh takes today's path.
- **Unscoped dashboard:** the zone of the newest event is shown, as in slice 1.
- **Many devices:** all are judged and listed; the trends plot 8.

## Out of scope

- Combined risks raised as **alerts** across devices. Core's feed still evaluates each device alone.
- Zone-level de-duplication of condition alerts. Two EC probes give two `high_ec` alerts; the Device column shows it.
- Retention per device, and a device cap (slice-1 follow-up).
- Fixing the dashboard-before-feed alert race (2.6), which exists today.
- A device filter in the dashboard UI.
- The in-process engine, simulator, scorer and game (slice 3).
- Feeding sensor quality into the dashboard's safety-triage call. That would change single-device zones.
- A moisture tile.
- Averaging or voting between two probes of one field. The pair check is its own doc.

## Done when

- [ ] **Before any code:** capture the baselines in a scratch folder, with the exact commands in the builder's report.
  - The slice-1 set: every scenario offline and on the stack, seeds 1-80, `real-replay`, `fault-replay`,
    `test-checker`, `test-demo`, `fool-space-check`.
  - For a single-device zone: every outgoing dashboard request body (a test that records them through a mock
    transport), every `/api/*` JSON response, and the rendered page as a DOM snapshot from `check_rendering.cjs` plus
    a screenshot.
- [ ] **Byte-identical after the build:** all of the above, apart from timing fields and the 2.10 allow-list.
- [ ] **Core tests:**
  - the snapshot: the `multi_device: false` paths; the device list and window; the stable order and `others`; a vetoed
    first device is skipped; the stale filter with per-device limits (`interval_s` null, 30 s and 15 min devices); an
    empty device list; no values from older packets; the context rule, including defaults,
    conflicts and the all-stale case; `sources` including stale carriers; `zone_device_fields`; judged, pending and
    pre-2.2 rows; `sensor` null;
  - `event_trust`: the migration on an old database, and that re-judging a packet overwrites the new columns;
  - the feed writes labels and checks;
  - `detail` is sent only in multi-device zones, and is cut at 500 characters.
- [ ] **Router tests:**
  - the merge rules: labels without the global and `missing_*` ones; vetoes only for held fields; companion groups;
    `cannot_confirm`; checks; `from_device_checks`;
  - the validators;
  - the shared chain, the same way;
  - absent keys give byte-identical output.
- [ ] **Automation tests:**
  - `ALTER TABLE` on an old database;
  - `detail`: stored only for rules matched through a data-quality label; carried through every transition (pending,
    active with a new text, recovering, re-activated); copied to `raised`; `events()` returns it;
  - an observe call without `detail` is unchanged;
  - outcomes with `sources`:
    - an EC suggestion: climate readings never count and substrate readings do;
    - a heat suggestion counts both air and substrate-temperature devices;
    - a sensor suggestion uses its own fields;
    - an empty set confirms nothing;
    - a `device_id` null reading is skipped;
    - two devices at 30 s and 5 min interleaved: no reading dropped, and no confirmation from the fast device alone;
  - `detail` with control characters and over 500 characters;
  - outcomes without `sources` are unchanged.
- [ ] **Dashboard tests:**
  - each view's request body on the zone-view path: S, `known_*`, `zone_device_fields`, masking, no twin
    `expected_fields`, no alert post from the snapshot;
  - one snapshot call per (farm, zone) within 5 s;
  - trend fetches only from `/api/overview`;
  - the pending fallback: `rules_only`, its own history, one post per packet (cache), `detail`; a retained packet is
    not posted; `/api/overview` makes no router call;
  - the snapshot cache expiry with an injected clock;
  - `/api/risk` sends `device_fields`, and a zone with no moisture device shows no missing moisture there;
  - a failed fallback vetoes and is retried after 5 s;
  - the snapshot failure and all-stale paths fall back as in 2.4;
  - a zone with no moisture device is `trusted` when everything else is fine;
  - single-device bodies are unchanged.
- [ ] **`check_rendering.cjs`:**
  - the trust-line wording for each case in 2.8;
  - tiles with a source line, a pair line, a `(not used)` pair line, and the VPD cross-device line;
  - the context-conflict line and the "Zone view unavailable" line;
  - the Device columns and the Recent line;
  - a two-device trend (time axis, shared scale);
  - a one-series sparkline unchanged.
- [ ] **Two-device check** (Core store and snapshot in-process, the real router as in slice 1's
      `test_multi_device_feed`, and the dashboard's view functions with Core and the router reached through ASGI
      transports):
  - a stuck humidity probe on `climate-1` → the zone-view pipeline shows `stuck_value` and humidity not used;
  - evaluate returns the `sensor_check` label set and `sources`.
  - The automation side (outcomes, `detail`) is covered by its own suite above, not in this process.
- [ ] **Screenshots:** a two-device zone (tiles with sources, a pair tile, a two-line trend, the trust line, Device
      columns, a detail line) and a single-device zone matching the baseline screenshot.
- [ ] **Gates:** `test-local`, `local-validation`, `fool-space-check`, `fool-space-pyodide-check`, `test-checker`,
      `test-demo`, `fault-replay` and `real-replay` all pass.

## Decisions (owner, 2026-11-14)

The owner approved the recommended answer to each open question ("Yes, as recommended"; also relayed as "yes approve
slice 2 with recommended answers"):

1. **A field both devices carry:** one stable device per field (the one that first sent it), skipping one whose own
   check failed; the other is shown as `also ...` (2.1).
2. **Detail line and Device columns:** shown only in multi-device zones for now (2.6, 2.8). Rule 0 stays strict.
3. **When a quiet device leaves the zone view:** per device, after the larger of `ZONE_STALE_AFTER_S` and 3 × its own
   reporting interval, capped at 60 min (2.1; cap added in the build, drift item 35).

## Open questions (answered above; kept for the record)

1. **A field both devices carry.** Recommended: the zone uses one stable device per field (the one that first sent
   it), skipping one whose own check failed, and the tile shows the other as `also ...`. The alternative is the newest
   reading of the two, as the outline said, which flips at each packet.
2. **Detail line and Device columns in single-device zones.** Recommended: show them only in multi-device zones for
   now, which keeps Rule 0 strict. The alternative is to show them everywhere: more useful, but the single-device page
   changes.
3. **When a quiet device leaves the zone view.** Recommended: per device, after the larger of `ZONE_STALE_AFTER_S`
   (10 min) and 3 × its own reporting interval, so a 15-min substrate node stays in. The alternative is one setting
   for all devices, which the owner would have to raise above the slowest node's interval.

## Outline answers (O-n)

- **O-1** zone snapshot, trust per device, pending, staleness, context, missing fields: 2.1, 2.4.
- **O-2** each view on `latest_event`, and how vetoes reach it: 2.5.
- **O-3** data-quality labels on the snapshot path: 2.2, 2.3, 2.4.
- **O-4** outcome tracking via `sources`: 2.7.
- **O-5** overview: per-device sparklines, real `trustLine()` wording, Device columns: 2.8.
- **O-6** alert `detail` via `ALTER TABLE`, and whether it shows in single-device zones: 2.6, open question 2.
- **O-7** router `known_vetoed_fields`: reason, companion groups, `cannot_confirm`: 2.3.

## Review changes (v1 → v2)

- **Zone expected fields:** the zone view sends `zone_device_fields`, so a field no device carries is not missing and
  the tomato reasoner gets `not_expected_fields`.
- **Pairs:** a vetoed first device is skipped (2.1 step 3), and `others` shows `vetoed`.
- **Outcomes:** heat and cold also map to substrate temperature; an empty device set confirms nothing;
  `snapshot_devices` was cut; null devices are skipped; the shared streak is stated.
- **One zone view per refresh:** a 5-s cache; trend fetches only in `/api/overview`.
- **Fallbacks:** all-stale and a failed snapshot use slice 1's newest-packet path, so the stale line works.
- **Pending checks:** `rules_only`; their own history; which gate fields are carried; failure caching; concurrency;
  duplicate posts across workers.
- **Masking:** carried vetoes only; `/api/safety` sends S unmasked (its gate never reads readings).
- **Storage:** `add_trust` gets named columns and the columns join `CREATE TABLE`; the unused `missing_fields` column
  was cut.
- **`detail`:** state handling for every transition; `events()`; `main.py` passes the labels; the race is restated.
- **Page:** the trend axis, scale and data shapes; the Rule-0 allow-list is complete; "Tests that change" added;
  slow-device staleness noted.
- **Labels:** a device's labels are carried only when its flagged probe is in the zone view.
- **Context:** limits stated.
- **Wording:** the example check text is the router's real text; the tile list is corrected; the parity note was
  added.
- **Done when:** the end-to-end check was cut to a buildable size; the build order is split into 2a/2b/2c.

## Review changes (v2 → v3)

- **Outcomes:** per-device last sample time; confirmation needs a clean reading from every counting device.
- **Staleness:** per-device limit from the device's own interval (open question 3); the slow-node example works.
- **Risk panel:** the shared chain takes `device_fields`, so it agrees with the trust line.
- **Retained packets:** judged for the view, never posted to alerts or outcomes.
- **`detail`:** control characters stripped, 500 including `…`, never copied elsewhere, injection tests updated.
- **Zone view per refresh:** softened to "within a cache life"; injectable clock; views call `_zone_view()`;
  `/api/overview` does not judge pending devices.
- **Advice cards:** their own trust-line variant. **Trends:** a fixed 60-min window, dash patterns, too-few points,
  the VPD card.
- **Edge cases:** empty device list, the twin's 422, partial packets.
- **Small fixes:** the evaluate row, `feed_alert_monitor`, `dashboard_judged`, the race inlined, two rules sharing
  text, `test_trusted_baseline` checked.
- **Size:** 2b split into 2b-1 and 2b-2, with the first cut named.

## Drift log

Filled in after the build (2026-11-14), from the builders' reports and a reviewer drift check (PASS WITH NOTES).
Each item: where the code differs from this doc, or what the doc left open and the code decided.

**Core and router (2b-1)**
1. `from_device_checks` is present also when only checks were added (its lists are then empty).
2. The rationale changes only when labels were added.
3. The snapshot's per-device `device_fields` uses the slice-1 counting rule directly; `device_fields_for` returns None
   when the device's latest packet predates its partner.
4. A context tie goes to the lowest `device_id`.
5. `interval_s` comes from the unique sample times of the device's last 6 live (non-retained) packets: one extra
   Core query per device, not listed in this doc's cost line.
6. The snapshot's queries are not one transaction (separate lock acquisitions). Harmless.
7. `DeviceZoneKeys` base class: `device_fields` moved there, so the property order of `PipelineEvaluateRequest` in
   OpenAPI changed. No behaviour change.

**Dashboard views (2b-2)**
8. The route handler is `overview_page()`; `overview(trends=False)` is the helper the views reach through `_zone_view()`.
9. Snapshot `multi_device: false` sets `zone_multi_device=False` and `latest_device_fields=None`, so views take
   today's single-device path.
10. All stale (`sensor` null): `zone_snapshot` stays attached to the overview; `latest_age_s` is `newest_age_s`
    (null when there are no devices: the latest event's own age).
11. A failed snapshot call is not cached; `zone_snapshot_error` reads `Zone snapshot unavailable: <exc>`.
12. The `known_*` keys are always sent on the zone path (empty lists when empty). `continue routine monitoring` is
    never carried in `known_safe_next_checks`: the router would count it as added and force human review.
13. `GLOBAL_VETO_LABELS` and `alert_detail()` are copied into the dashboard (it cannot import the router or Core);
    `services/dashboard/tests/test_parity_with_router.py` pins them to the originals.
14. `dashboard_judged` lists only devices whose check succeeded; a failed check is vetoed and named by its check text.
15. Concurrent views share one in-flight device check, so a refresh judges and posts a pending packet once.
16. The pending check sends `scenario_id: dashboard-device-check`, `actor: dashboard`, and the same `farm_context`
    keys as Core's feed. The alert post is awaited inside the check (existing 2 s timeout).
17. On the zone path `sensor_event_id` is the sha256 of `{"sensor": S, "sources": sources}` (sorted keys, compact) and
    the history hash is that of `[]`.
18. Trend events are sorted by sample time, oldest first; a failed trend fetch gives `[]` for that device; 3 s timeout.
19. The 5 s cache is a result cache only: the first concurrent views of a refresh can make more than one snapshot call.
20. A pending device with an empty `supplied` list is not judged or posted. So with the feed disabled, a device that
    supplies nothing to the zone view gets no alert from the dashboard ("Feed disabled" in Edge cases is too strong).
21. In a multi-device zone's newest-packet fallback (all stale, snapshot failed) `pipeline()` posts alerts without
    `detail`, as before; only the pending fallback carries one.

**Outcomes (2.7)**
22. Evidence in `sources` mode gains `last_sample_by_device` and `clean_streak_devices`; `last_sample_time` stays the
    newest sample overall. Without `sources` the evidence keys are exactly today's. An empty `sources: {}` is absent.

**Alerts (2a)**
23. `clean_detail` strips Unicode category Cc only; U+2028/2029, bidi and zero-width characters survive (the page
    escapes the text). `AlertObserveRequest.detail` is cut, not rejected, above 500 characters.
24. The in-process `AlertMonitor` omits the `detail` key when it is None; only the HTTP models add `detail: null`.

**Page (2c)**
25. `trustLine`'s `zone` argument is `{sources, devices, dashboard_judged}`, built from the snapshot plus the
    pipeline response.
26. Order of the parts: fields not used, then probes of a quiet device, then probes nobody reported (today's
    no-zone order, missing first, is unchanged).
27. A dashboard-judged device reads `humidity (climate-1) (checked by the dashboard) not used`; the trusted line
    reads `(2 devices, substrate-1 (checked by the dashboard))`. `(1 device)` / `(N devices)`; no count in the
    advice-card variant.
28. A missing field counts as "quiet" if any of its expected devices is stale; the line names only the stale ones.
29. When every device is quiet, tiles and trust line use the newest-packet path but the trends still plot
    `device_events`.
30. Device columns and the `detail` line key on `zone_multi_device`, so they also show in a multi-device zone's
    fallbacks.
31. Multi-device tiles set the value cell with `innerHTML` (every part escaped); single-device tiles keep
    `textContent`. The VPD tile gets a source line only when VPD is computable.
32. Context-conflict lines use raw field names (`growth_stage`); object values as JSON.
33. A device's dash pattern is its position in `device_id` order among the plotted devices, the same in every card.
34. Rule 0, static page: the served HTML gains three CSS rules (`.tile-src`, `svg.swatch`, `.legend-item`) and an
    always-present empty `<div id="zone-notes">`. Nothing renders differently and the DOM snapshots of every
    single-device case are byte-identical; added to the 2.10 allow-list in spirit.

**Known limit found in review (open)**
35. The router flags any packet older than 60 min as `stale_reading` (a global veto), while a device's stale limit
    is max(`ZONE_STALE_AFTER_S`, 3 × interval). A device reporting every 20 min or slower can be live in the
    snapshot at 60-90 min old: judged by the dashboard, all its fields are vetoed; as the zone view's newest supplier,
    the zone goes `cannot_confirm`. Core-judged devices are fine (judged on arrival). The 15-min example of this doc
    (45 min limit) is not affected. Owner decision 2026-11-15 ("Yes, cap at 60 min"): the per-device limit is now
    `min(3600, max(ZONE_STALE_AFTER_S, 3 × interval))` in Core `zone_snapshot` (`ZONE_STALE_CAP_S` in
    `services/core/app/store.py`), so a device is never live in the snapshot past the router's veto; a 30-min device
    with a 70-min-old reading is stale (test in `services/core/tests/test_zone_snapshot.py`). The cap also applies to a
    `ZONE_STALE_AFTER_S` set above 3600 s.

**Two-device test note**
36. The two-device check freezes humidity at tick 20 of 28, because the router's 11-packet history check stops
    flagging once the frozen run fills the whole history; the persistent check needs Core's stream baseline.
