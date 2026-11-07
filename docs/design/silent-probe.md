# Silent probe: say "can't confirm" when a probe stops reporting

Status: approved by owner 2026-11-07 (all four open questions answered as recommended)
Issue: `private/ISSUES.md` "Core refuses a whole packet when one required probe is missing"

## Goal

When one probe in a full packet stops reporting, Pomona must say so for that probe within minutes,
and it must stop showing "All readings passed the sensor check" on old data. Today one silent probe
does the opposite: Core refuses the whole full packet (422), so the zone goes quiet, no alert is
raised, and the dashboard keeps the last stored reading and its green trust line for up to an hour.
The `blind_spot` fake-greenhouse scenario (commit 9166752) shows this: in all six probe-dropout
cases the only sign is the Device health row turning "silent" after 120 s.

Words, as in the code: an **alert** is raised automatically by the automation-engine alert monitor
(`/v1/automation/alerts/observe`, dashboard Alerts panel). An **advice card** is created only when a
person presses "Evaluate current risk" (`/v1/automation/evaluate`). This design changes Core, the
router's gap handling and the dashboard; it creates no cards automatically.

## How the user meets it

1. A grower's EC probe stops sending; the node keeps publishing full packets without `ec_ms_cm`
   (absent or `null`).
2. Core stores them. On the next dashboard refresh the trust line says
   `Can't confirm: EC not reported in the latest reading`, and the sensor-quality badge shows
   `missing_ec`.
3. On the 3rd such reading in a row (existing `sensor_check` rule, about 60 s at 30 s sampling) the
   Alerts panel shows the `sensor_check` alert. A card made with "Evaluate current risk" says the same.
4. If the whole node goes quiet, the trust line becomes
   `Can't confirm: no reading from this zone for 12 min (last 09:12 +04)` instead of the green line.
5. When EC reports again, `missing_ec` goes away and the `sensor_check` alert recovers by its
   existing `clear_after` rule.

## Design

### Part 1: Core accepts partial full packets

- `services/core/app/schemas.py` `SensorEvent`: `air_temperature_c`, `humidity_pct`, `ec_ms_cm`,
  `ph`, `soil_moisture_pct` become `Optional[float] = None`, same bounds when present. Absent and
  `null` both mean "not reported"; Core never fills a default.
- **Still 422:** an out-of-range value; NaN / Infinity / strings / booleans (unchanged; a probe
  library that returns NaN must send `null`, as `docs/HARDWARE_EVENT_CONTRACT.md` will say); and a
  packet with no reading. **Reading fields** are exactly the five plus `substrate_temperature_c` and
  `substrate_moisture_pct`; "has a reading" means at least one of them is a non-null number
  (`model_validator`; `{"ec_ms_cm": null}` alone is refused). `weather`, `npk_target`, `zone_area_m2`,
  `crop_kc` don't count. Soil moisture absent with substrate moisture present is a normal packet.
- **Schema version stays 1.0** (constant and default), so stored payloads, the dedupe hash and every
  existing output are unchanged. Partial packets are accepted from every 1.x sender. Behaviour
  change, stated plainly: a firmware bug that drops a field used to get a 422 only the device log
  saw; now the grower sees `missing_*` and a `sensor_check` alert.
- `schemas/sensor-event.schema.json`: the five lose `required` and become `["number","null"]` (as
  the substrate fields are); add an `anyOf` over the seven reading fields, each
  `{"required":[f], "properties":{f:{"type":"number"}}}`, so an explicit `null` alone fails.
- **None-safe logging:** ingest log lines in `services/core/app/main.py` (~81-88) and
  `services/core/app/mqtt_client.py` (~80-90) use `%.2f` etc.; print `-` for `None` (today a partial
  packet would store, then return HTTP 500).
- Store, `latest_event`, `prior_events`, history and CSV export carry `None` through (CSV writes an
  empty cell). `device_presence`, `devices()` and `trusted_baseline.py` need no change
  (`StreamBaseline` already skips `None`).
- The outcome feed forwards partial packets like full ones. The router's existing path does the
  rest: `expected_fields_for` decides which missing fields matter (`substrate_temperature_c` is not
  expected and raises nothing), `derive_sensor_quality` adds `missing_*`, the veto gives `partial` /
  `cannot_confirm`, and the `sensor_check` rule raises the alert.

### Part 2: gap rule in the router's stream checks

`_series_values` / `_series_points` in `services/model-router/app/sensor_quality.py` drop packets
whose field is `None`, so values either side of a gap look adjacent. Rule:
- **Stuck / frozen runs** (`_trailing_run`, `_longest_run`, adaptive stuck limit): a packet missing
  the field ends the run; counting restarts after it.
- **Step and noise checks:** skip only the step that crosses the gap (no difference is taken between
  the readings either side of it); the window keeps its normal length over the remaining steps.
- `apply_persistent_checks` already skips a field missing on the previous packet; unchanged.
- **JS mirrors must match:** `spaces/sensor-data-checker/rules.js` (`seriesValues`, `seriesPoints`),
  `spaces/pomona-greenhouse-demo/rules.js` (exact copy), and regenerated parity cases
  (`make_parity_cases.py`), so `make test-checker` / `test-demo` stay green.
- No existing replay or dataset has `None` gaps today; `real-replay` and `fault-replay` confirm it.

### Part 3: dashboard honesty about old and missing data

- **Old data.** The dashboard backend computes `latest_age_s` = its clock minus the latest reading's
  sample time (Core and dashboard share a host; clamped at 0, since Core allows 60 s ahead) and
  sends it with the overview. New setting `ZONE_STALE_AFTER_S`, default 600 (twice the 5-min real
  log interval); `0` turns it off for demos and fixed-timestamp replays. Above it, the trust line is
  `Can't confirm: no reading from this zone for <age> (last <farm time>)` in the cannot_confirm tone,
  and the pipeline block is captioned "from the last reading at <farm time>". The browser clock is
  never used. Added to `.env.example` and `docker-compose.yml`. Limitation: fixed, not learned per
  zone.
- **Missing vs vetoed wording.** The main panel has `sensor_quality.missing_fields` and
  `vetoed_fields`: a missing field reads "EC not reported in the latest reading", a vetoed one
  "EC not used" (as today). Advice-card evidence gets `missing_fields` too
  (`services/automation-engine/app/advice_cards.py`) so the card and the panel say the same thing.
  `trustLine` takes both lists.
- **Null-safe rendering:** the history row (`Temperature … · pH … · EC …`, ~line 931) and the
  advice-card "Readings" line print `–` for `None`. (`value()`, `vpdKpa`, sparklines already cope.)

### Simulator, scorer and Space

- `examples/simulators/fake_greenhouse.py`: drop `CORE_REQUIRED` and the `core_rejects` truth key.
  `examples/simulators/inprocess_pomona.py`: mirror Core's new accept / refuse rule.
- `scripts/score_fake_greenhouse.py`: unchanged rules; `core_refused_frames` becomes 0 on
  `blind_spot.json`. `silent_flag_only` stays a reported category (not redefined).
- "Try to fool Pomona" Space: re-vendor (`scripts/build_fool_space.sh`) is a required step before
  `make fool-space-check`; the game offers no dropout trick, so visitors see no change; a re-upload is
  a separate owner approval.

### Files it touches

Core: `app/schemas.py`, `app/main.py`, `app/mqtt_client.py`, `schemas/sensor-event.schema.json`.
Router: `app/sensor_quality.py`. Automation-engine: `app/advice_cards.py`. Dashboard: `app/main.py`,
`tests/check_rendering.cjs`, `tests/test_dashboard_api.py`. Spaces: two `rules.js`, parity cases.
Simulators / scorer: `fake_greenhouse.py`, `inprocess_pomona.py`, `score_fake_greenhouse.py`, tests
`examples/simulators/tests/test_blind_spot.py` (the `CORE_REQUIRED` and 422 tests are rewritten),
`scripts/tests/test_score_fake_greenhouse.py`, `services/core/tests/test_core_api.py`. Config:
`.env.example`, `docker-compose.yml`. Docs: `HARDWARE_EVENT_CONTRACT.md`, `FAKE_GREENHOUSE.md`,
`examples/simulators/README.md` (both say "Core refuses"), `ADVICE_CARDS.md`.

## Edge cases

- **Probe not fitted for this system type:** not in `expected_fields_for`, so no `missing_*`.
- **Retained MQTT message:** never live (existing rule).
- **Dashboard re-posting the latest event:** a repeated sample time is ignored by the alert monitor.
- **Device clock lagging:** shows an old age on the panel, which is visible and correct.
- **Multi-device zones (limit):** `latest_event` and router history are zone-wide while alerts and
  baselines are per device. Zones where two devices each carry some of the probes are not supported
  by this design (the latest packet would flip between devices and report `missing_*`); one device
  per zone sending the full set is the supported case. Written into the hardware contract.

## Out of scope (later, own designs)

- **Alert hold on missing input.** An alert that is already open for a rule whose probe goes
  silent (e.g. `high_ec` with EC missing) can still recover because the label disappears. Fixing it
  needs per-rule input definitions (`any` vs `all`: `high_humidity_fan` uses humidity alone or
  humidity + air via VPD; `heat_stress_check` air or substrate), a decision on global vetoes, and
  changes to `alerts.py`, `AlertState`, `inprocess_pomona.py` and the vendored Space copies. It also
  changes existing scorer timings. `sensor_check` is active meanwhile and says why.
- **Whole-node silence alert** (timed watchdog): own alert stream key, per-field last-seen and
  learned intervals in Core, expected fields known to Core, a background tick, a `dropout` scenario.
- Per-sensor Device health rows; alerts for the per-sensor observation path (watercress logger).
- Digital twin preview with a missing field (`/api/digital-twin` treats it as not expected).
- Cards created automatically; carrying forward a missing value; neighbour checks; any actuator path.

## Done when

- [ ] `blind_spot.json`: `core_refused_frames` 0; no case is `silent_flag_only` or
      `false_reassurance`; each probe-dropout case is `cant_confirm` via the `sensor_check` alert
      (first raise ≤ 3 min after the probe goes silent) or `alerted` by the event's own rule where
      another probe still carries the event (the heat cases, if substrate reaches 30 °C). The builder
      lists the actual per-case table (tick, field, rule, outcome) in the drift log.
- [ ] Core tests: partial packet stored and returned with `None` over HTTP and MQTT with no 500 and
      no log traceback; `{"ec_ms_cm": null}`-only and no-reading packets 422; NaN still 422; the
      observation-posted-as-event test (`test_core_api.py` ~114) still 422; default `schema_version`
      still `1.0`.
- [ ] Router tests: a stuck run never spans a missing reading; a step across a gap is not taken.
      JS parity (`make test-checker`, `make test-demo`) green with regenerated cases.
- [ ] Dashboard tests: age > `ZONE_STALE_AFTER_S` shows the "no reading" line; `0` disables it;
      missing EC reads "not reported", vetoed reads "not used" (panel and card); `None` renders `–`.
- [ ] Existing scenarios (smoke, quick, validation, cold, demo): scorer output byte-identical;
      `real-replay` / `fault-replay` guards unchanged; normal seeds 1–80 still 0 false alerts.
- [ ] `make test-local`, `local-validation`, `fool-space-check` (after re-vendor), `test-checker`,
      `test-demo` pass. Docs listed above updated.

## Open questions (answered 2026-11-07: 1 yes, 2 yes = 600 s, 3 yes = NaN stays 422, 4 yes = later designs)

1. **Partial packets from every 1.x sender** (no version bump). A firmware bug that drops a field now
   shows up to the grower as `missing_*` + a `sensor_check` alert instead of a 422 only the device
   log sees. OK? (Recommended: yes.)
2. **Dashboard old-data threshold:** `ZONE_STALE_AFTER_S` = 10 min, `0` = off. OK?
3. **NaN stays a 422** (firmware must send `null` for a failed read). OK, or treat NaN as "not
   reported" too?
4. **Alert hold and the whole-node watchdog** as two later designs. OK?

## Drift log

Built 2026-11-07. Nothing committed or uploaded. Where the code differs from the doc above, or the doc was silent:

1. **`persistent.js` is mirrored too.** The doc named `rules.js` (checker + demo copy) and the parity cases, but
   `spaces/sensor-data-checker/persistent.js` carries its own copy of `seriesPoints`, `trailingRun` and
   `applyNoiseCheck` (Core's persistent checks), so it needed the same gap rule. Done; `make_persistent_cases.py` and
   `make_parity_cases.py` gained gap cases (900 + 900 random ones; the old rule gives a different answer on 72 of
   the derive cases and 88 of the persistent-check cases, so they do exercise the rule).
2. **The gap rule reaches a few places the doc did not list.** (a) The flatline window must be 6 readings in one run
   (a gap inside it ends the check) and its "prior step" median skips steps across a gap; with no steps left it is
   skipped (an empty median would raise). (b) The pH/EC baseline-drift noise test in `apply_temporal_checks` takes
   its median over steps inside runs only. (c) In `apply_noise_check` the sample interval (median of the time gaps) also
   ignores the pair across a gap, not only the value step. (d) When the newest packet has no reading of the field,
   the stuck check judges nothing from older readings (before, it ran on stale readings as if they were the latest).
   Helper: `_series_segments` / `_segment_steps` in `sensor_quality.py`, `seriesSegments` in both JS files.
3. **`fmt_reading`** (new, in `services/core/app/schemas.py`) is the `-` for a `None` in the two ingest log lines.
4. **Pre-existing, not changed:** a bare `NaN` token in an HTTP JSON body (not the string `"NaN"`) returns HTTP 500,
   before and after this work, because FastAPI cannot serialise the validation error that echoes the value. The string
   forms and a bare NaN over MQTT are refused as the doc says (tests cover them; the HTTP bare-token case is not
   tested because it is the 500). Worth its own punch-list item.
5. **`inprocess_pomona.py`:** `CORE_OPTIONAL` now also lists the five reading fields (Core stores an absent one as
   `null`), a new `READING_FIELDS` tuple mirrors Core's, and `observe` rejects a packet with no numeric reading
   (`rejection: "no_reading"`). Full packets are unchanged byte for byte.
6. **`score_fake_greenhouse.py`:** `core_accepted` no longer looks at the `core_rejects` truth key (the simulator no
   longer writes it). A truth log from an older simulator that has it is now read as accepted.
7. **Tests that modelled "Core refuses" were rewritten** (`test_blind_spot.py`, `test_score_fake_greenhouse.py`).
   Hand-built truth rows for a node whose packets stop arriving use `delivery: {"status": 422}` now, which keeps the
   passive device-silent path of the scorer covered.
8. **Dashboard:** the overview sends `stale_after_s` (the setting, negative values read as 0) next to `latest_age_s`,
   so the page needs no setting of its own. The "no reading" line replaces the trust line in the pipeline block and the
   risk block; advice cards keep their own recorded verdict (they show a past evaluation with its own sample time).
   `readingTime` shows the date too when the reading is 12 h old or more, and UTC when Core gave no farm zone.
9. **Docs touched beyond the list:** `docs/SENSOR_TEMPORAL_CHECKS.md` (gap rule), `services/dashboard/README.md`
   (`ZONE_STALE_AFTER_S`).
10. **Doc claim not quite right:** "a missing `substrate_temperature_c` is not expected and raises nothing". The tomato
    reasoner (not the sensor-quality block) emits the crop-risk label `missing_critical_data` for it. No alert rule
    matches that label, so no alert follows and the outcome below is unchanged.
11. **How the byte-identical check was run:** the plain `--dry-run` CLI stamps readings with the real clock, so every
    tick falls in the same second and the scorer's timings mean nothing. Both captures (before the first edit, after the
    last) used `fake_greenhouse.main(..., clock=<30 s fake clock starting 2026-06-01T12:00Z>)`, as the tests do, then
    `score_fake_greenhouse.py --offline --json --report` for smoke, quick, validation, cold, demo and blind_spot. Truth
    logs, event logs, stdout, JSON and markdown of the five existing scenarios are identical (only the input-path
    header differs).

12. **Doc claim not true: "No existing replay or dataset has `None` gaps today".** The real 5-minute logs do: the
    AGC2 slab file leaves `substrate_moisture_pct` out of about 2,350 of each compartment's rows (the replay drops a
    NaN, so the key is absent). `make real-replay` therefore changes slightly: every guard still passes with the same
    values, but the per-compartment `flagged` counts fall by 9 to 23 packets (for example AICU 6,863 to 6,854,
    `stuck_value` 3,866 to 3,857; Automatoes 3,399 to 3,381). Cause, checked packet by packet against the old rule:
    nearly all are `substrate_moisture_pct` `stuck_value` flags on a packet that has no moisture reading at all
    (the old rule judged stale readings as if they were the latest; the packet now says `missing_moisture` instead),
    and 1 or 2 per compartment are runs that used to span a gap. The aquaponic pond log (no gaps) is unchanged.
    `make fault-replay` differs only in timing fields (`max_detector_latency_ms`); every count and rate is identical.
    This is the rule working as designed, not a regression, but the Done-when line "real-replay guards unchanged"
    holds only for the guards, not for the raw counts.
13. **Normal seeds 1-80:** there is no script for it, so a scratch script ran the default simulation (no scenario, two
    zones, 720 ticks = 6 simulated hours at 30 s, 30 s fake clock) through `InProcessPomona` for each seed: 0 raised
    alerts of any rule, on this tree and on the commit before it (a clean worktree of `HEAD`).

### `blind_spot.json` per-case table (offline scorer, seed 7, 30 s ticks)

`core_refused_frames` is 0 in all seven cases (before: 662 of 1240 frames accepted; now 1240 of 1240). No case is
`false_reassurance` or `silent_flag_only`. "Raised" is the first `sensor_check` raise, found by replaying the truth log
through `InProcessPomona` (ticks; 1 tick = 30 s); the silent probe's `missing_*` label is on from the first silent tick.

| Zone | Probe silent (ticks) | Real event (crossing tick) | Label from | `sensor_check` raised | Rule | Outcome |
|---|---|---|---|---|---|---|
| greenhouse-a | `soil_moisture_pct` 46-155 | dry_zone (125) | 46 `missing_moisture` | 48 (+60 s) | sensor_check | cant_confirm (reading flagged, sensor card) |
| greenhouse-b | `ec_ms_cm` 46-167 | nutrient_over_concentration (138) | 46 `missing_ec` | 48 (+60 s) | sensor_check | cant_confirm (reading flagged, sensor card) |
| greenhouse-a | `air_temperature_c` 206-259 | heat_spike (227) | 206 `missing_temperature` | 208 (+60 s) | sensor_check | cant_confirm (reading flagged, sensor card) |
| greenhouse-b | `humidity_pct` 216-329 | humid_night (242) | 216 `missing_humidity` | card already open (raised 48 for the EC probe, still open: its EC aftermath and then this gap kept it up, recovered 360); alone, the same steps raise at 218 (+60 s) | sensor_check | cant_confirm (sensor card, reading flagged) |
| greenhouse-a | `ec_ms_cm` 326-449 | nutrient_over_concentration (408) | 326 `missing_ec` | 328 (+60 s) | sensor_check | cant_confirm (reading flagged, sensor card) |
| greenhouse-b | `air_temperature_c` 376-429 | heat_spike (395) | 376 `missing_temperature` | 378 (+60 s) | sensor_check | cant_confirm (reading flagged, sensor card) |
| greenhouse-a | `substrate_temperature_c` 526-579 | heat_spike (541) | 526 `missing_critical_data` (crop-risk label, no rule) | none | heat_stress_check, raised 561 (+600 s after the crossing) from the air probe | alerted (event card) |

Scorer summary line: blind spots 7: false reassurance 0, can't confirm 6 (0 by the device-silent flag only), alerted 1,
too short 0, no fault in window 0; real episodes 7: caught 1, can't-confirm 6, missed 0; false alarms 0. Before the
change the same run was: can't confirm 6 (all 6 by the device-silent flag only), alerted 1.
