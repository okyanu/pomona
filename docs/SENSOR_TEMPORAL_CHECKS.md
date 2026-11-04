# Sensor temporal checks (design draft)

**Status:** implemented locally in deterministic sensor-quality rules
(`services/model-router/app/sensor_quality.py`) with fault-replay coverage.
Not committed/deployed unless the owner requests it.

Pattern peer: [Makeph/plexus](https://github.com/Makeph/plexus) (startup-baseline
drift, stuck/flatline). Pomona keeps SQLite in `pomona-core` as system of
record; do not adopt Plexus as an ingest hub.

Prerequisite: trustworthy dual-time and zone-identity hygiene
([RELIABILITY_HARDENING.md](./RELIABILITY_HARDENING.md),
[SENSOR_QUALITY_INPUT_CONTRACT.md](./SENSOR_QUALITY_INPUT_CONTRACT.md)).

## Goal

Detect stream faults that packet-level rules miss today:

| Fault | Symptom | Current fault-replay gap |
|-------|---------|--------------------------|
| Stuck value | Same numeric reading across samples, fresh timestamps | 0/6 detected |
| Flatline | Near-zero variance over a window | related to stuck |
| Startup-baseline drift | Slow walk away from values seen at stream start | 0/6 slow drift |
| Dropout (temporal) | No new samples; last packet ages | partial via stale |

See [SENSOR_FAULT_REPLAY.md](./SENSOR_FAULT_REPLAY.md).

## Placement

```text
MQTT / HTTP ingest → core (store raw) → deterministic temporal SQI
  → sensor-quality labels / human_review
  → risk reasoners (only if usable)
```

- Deterministic rules first; learned SQI later if needed.
- Emit labels and review flags; never rewrite stored raw packets.
- Dashboard / automation may surface WARN/FAULT suggestions only.

## Proposed labels (additive)

Extend the allowlist in [SENSOR_QUALITY_REASONER.md](./SENSOR_QUALITY_REASONER.md):

```json
[
  "stuck_value",
  "flatline_possible",
  "baseline_drift_possible"
]
```

Keep existing `sensor_drift_possible` until these are sharper; avoid duplicate
labels on the same frame without a merge rule.

## Implemented behaviour (2026-09-27)

`services/model-router/app/sensor_quality.apply_temporal_checks`, using up to 11
prior packets (the dashboard's window) plus the current packet:

| Check | Fires when | Why this shape |
|---|---|---|
| `stuck_value` | The latest value has repeated ≥ 3 times **and** ≥ 2× the longest earlier repeat, after the field had varied; for water and substrate temperature the repeat must also span ≥ 3 h of sample time, for soil/substrate moisture ≥ 2 min (so 30 s sampling needs 5 identical readings to flag, 7 to raise a card; 1-minute and slower sampling is unchanged) | Continuous sensors are caught after 3 identical samples; quantized probes (DS18B20 0.0625 °C steps) that legitimately repeat 2–3 times need a longer freeze. Thermal mass holds a DS18B20 step for hours (real pond: 99th percentile 2.25 h, longest 4.75 h), so at 5-minute samples and an 11-packet window this cannot fire for those two fields; their probe error codes are still caught by range checks |
| `flatline_possible` | The last 6 samples span ≤ epsilon (0.05 °C / 0.25 %) but not exactly zero, **and** the field's median step before that was ≥ epsilon | Slow, healthy signals at 5-minute steps often stay within epsilon for 3 samples; the old 3-sample rule flagged them |
| `noisy_signal_possible` | pH/EC has ≥ 6 samples in the window and their median step is ≥ the drift threshold (pH 0.35, EC 0.4 mS/cm); drift is not evaluated for that field | Real unshielded PH-4502C jumps ~0.5 pH per 5-minute sample; commercial greenhouse drain probes stay ≤ 0.1. Noise that large cannot be told apart from drift |
| `baseline_drift_possible` | pH/EC stays ≥ threshold away from the **median of the first 3 plausible** values in the window (pH 3–11, EC 0–12) for 3 samples; no judgement until 3 plausible values exist | An impossible reading must not become the baseline, and one outlier first reading must not make a steady probe look drifted |

Packet-level range checks added alongside: `water_temperature_c` outside 0–50 °C and
`substrate_temperature_c` outside −10–60 °C give `impossible_temperature` (catches the
DS18B20 error values −127 °C and 85 °C).

Real-data replay (2026-09-28, `make real-replay`, see
[SENSOR_FAULT_REPLAY.md](./SENSOR_FAULT_REPLAY.md#real-data-replay-2026-09-28)) set the
3 h thermal-mass window and the noise label.

Normal controls covered by `services/model-router/tests/test_sensor_temporal_checks.py`:
stable pH plateau, quantized probe flicker, slow noisy climb. The browser checker in
`spaces/sensor-data-checker` mirrors these rules (`make test-checker`): `rules.js` the 11-packet checks, `persistent.js`
Core's trusted stream reference (`stream_baseline`) and the persistent checks that use it, run over a whole uploaded log
(the greenhouse demo Space sees one reading at a time and has neither history nor a reference, so it runs neither).

## Detection sketch (to implement later)

Inputs per `(farm_id, zone_id, device_id, measurement)`:

- Ordered history of `(sample_time, value)` from core (not receipt-only).
- Stream `baseline` = first N valid samples after boot / reconnect (fixed;
  not a sliding window that absorbs drift).
- Configurable windows and thresholds via env (no hard-coded crop magic).

### Stuck / flatline

Flag when, over `K` consecutive samples with fresh sample times:

- exact equality, or
- `max - min <= epsilon` for that measurement.

Require enough samples; do not flag single repeats after reconnect.

### Startup-baseline drift

Flag when recent median (or mean) moves beyond `delta` from the startup
baseline for longer than `T`, while timestamps remain fresh.

### Normal controls (required before enabling)

Flat or slow change can be legitimate. Acceptance fixtures must include:

- stable climate plateau (no review),
- quantized probes (1-decimal steps),
- expected day/night moisture/temperature change,
- post-irrigation step change (not stuck).

Do not feed evaluator fault annotations into the detector.

## Acceptance

1. Extend `make fault-replay` sequences for stuck / slow drift until they fail
   closed honestly, then until they pass with the new rules.
2. Unit tests for window edges, reconnect baseline reset, and normal plateaus.
3. No network, actuators, or model downloads in the harness.

## Out of scope

- Replacing core storage with Gorilla compression.
- Calibration budget / corrected readings (see [CALIBRATION_PROVENANCE.md](./CALIBRATION_PROVENANCE.md)).
- Silent “fixing” of live values.

## Implementation order

1. History API or in-process window feed into deterministic SQI.
2. Stuck + flatline rules + normal controls.
3. Startup-baseline drift.
4. Update fault-replay baseline table and SENSOR_QUALITY docs.

## Longer memory in Core's feed

The 11-packet window above absorbs a step or a frozen run within minutes. Core's outcome feed adds a
sticky trusted reference per probe (median of the readings the pipeline did not veto, plus when the value
last changed) so those faults stay flagged. See
[SENSOR_QUALITY_REASONER.md](./SENSOR_QUALITY_REASONER.md#sticky-trusted-reference-core-feed-only).

A flagged level **stays "can't confirm" until a calibration for that probe is recorded** (the default,
`TRUST_BASELINE_MAX_AGE_S=0`); the reference is anchored at the newest trusted reading, so even a probe
broken for hours is judged against the readings from before it broke. A lapse is opt-in.

**Why the unattended rates are high on historical logs.** `make real-replay` replays the real third-party
logs (aquaponic pond, 6 greenhouse compartments) through this check. Those logs have no operator, so
nobody can ever record a calibration: every real level shift of a drain pH or EC probe (and they move for
good over a crop cycle) stays flagged for the rest of the log. The "unattended: no operator to calibrate"
rates (EC 13 to 27 % of readings in the greenhouse compartments, pH 2 to 13 %) are therefore a statement
about the logs, not about the check, and are reported as information only. With the opt-in 2 h lapse the
same logs flag EC on 0.8 to 1.9 % and pH on 0.1 to 1.1 % of readings, about what the 11-packet drift check
flags on its own. The thresholds were not loosened to make the unattended numbers look smaller: what is
guarded is what must not regress (the legacy pass, the persistent stuck rates both ways, the drift rate with
the lapse, and the fields that had no persistent flags at all). In a live deployment each flagged level is
a card that asks someone to confirm the probe, and the confirmation ends it.

## Stream-habit checks in Core's feed (2026-11-02, widened 2026-11-05)

The "Try to fool Pomona" game ([FAKE_GREENHOUSE.md](./FAKE_GREENHOUSE.md)) showed sensor lies the checks
above missed. These checks now close most of them. All need Core's `stream_baseline` (they judge a reading against
its own stream, so they run in the Core feed and the in-process engine, not in the 11-packet rules the
browser checker mirrors in JavaScript) and every threshold was set on the real logs (`make real-replay`,
5-minute samples, budget about 0.15 % of readings per stream).

| Check | Fires when | Real-data share flagged (worst compartment) |
|---|---|---|
| `stuck_value` for pH and EC (adaptive) | The value repeats for longer than 5 minutes **and** 4 times the longest hold the stream showed in its last 200 trusted readings, **and** it is at least 3 readings in a row (at 10 or 15-minute sampling one pair of equal readings is already longer than 5 minutes), **and** the stream changed in at least 70 % of those steps (15 steps minimum). Core sends `change_share`, `change_steps`, `longest_run_s` for pH and EC | pH: 0 of 7 real streams. EC: 0.02 % (IUACAAS, no-lapse replay only), 0.004 % (Automatoes), 0 elsewhere. The floor was 15 minutes; 5 minutes (one real 5-minute sample: a pair of equal readings never counts) flags exactly the same real readings |
| `sensor_drift_possible` (step) for air temperature, humidity, substrate moisture and substrate temperature | The reading differs from the newest trusted reading (`last_value`, `last_at`) by more than max(smallest allowance, speed x minutes since that reading). Air 3 C and 1 C/min; humidity 12 %RH and 4 %RH/min; moisture 8 % and 2 %/min; substrate temperature 1.5 C and 0.3 C/min. A flagged reading is vetoed, so the reference stays put and the step stays flagged until the allowance has grown to cover it (4 minutes for +4 C air, 4 for +15 %RH, 8 for +15 % moisture, 13 for +4 C substrate), then the new level is accepted | air 0.054 % (the Reference compartment holds 17 C glitches), 0.002 % elsewhere; humidity 0.021 % (Reference glitches), 0.010 % (IUACAAS), 0.008 % (Digilog), about 0 elsewhere; moisture 0.017 % (Digilog, one 79 % glitch held until the allowance covers it), 0 elsewhere; substrate temperature 0.006 % (Digilog, one 2.4 C glitch), 0 elsewhere |
| `noisy_signal_possible` for humidity, air temperature, pH, substrate moisture and substrate temperature | The median step over the last 12 readings is at least the limit **and** the window has not simply moved in one direction (its net movement is at most half of the distance it travelled). The 5-minute limits are 10 %RH, 2 C, 0.5 pH, 1 % moisture and 0.4 C; they shrink with the square root of the sample interval, never below the floors 3 %RH, 0.4 C, 0.1 pH, 2.5 % and 0.5 C | humidity: 0.084 % (AICU), 0.056 % (IUACAAS), 0.025 % (Digilog), about 0 elsewhere; air: 0.029 % (Reference), about 0 elsewhere; pH: 0.061 % (AICU), 0 elsewhere (the unshielded pond pH is noisy on purpose and already flagged by the 11-packet rule); moisture and substrate temperature: 0 |
| `baseline_drift_possible` for pH, now also for a slow drift | As before, but a pH stream that normally changes every sample (the same 70 % test) is judged against the spread of its trusted readings older than half an hour (Core's `spread_lag`) instead of the spread of the whole window. A drift in progress is trusted until it is a threshold away, which widens the whole-window spread until 3 x spread hides it; the lagged spread has not seen the newest half hour | no change in the real logs: no real drain stream changes every sample, so they keep the full spread. Only the pond pH is judged this way: 0.49 % to 0.64 % of its readings (with the 2 h lapse), inside the 2 % guard. EC is not judged this way (see below) |

Why each shape:

- **pH/EC cannot have a fixed stuck limit.** Real drain probes hold one value for hours (80 % of readings
  are beyond 20 minutes; the longest hold is 6 days). A limit tuned to the longest real plateau would miss
  every freeze, a short one would flag the drain probe most of the time. A history-only variant (limit = a
  multiple of the longest hold in the last 2 to 72 hours) was tried on the real logs and flags 0.4 to 20 %
  of readings, because plateaus are heavy-tailed and every new record plateau looks like a freeze. What
  does separate the two kinds of probe is how often the value changes at all: the real drain probes change
  in 3 to 18 % of their steps, the pond pH in 99 % and the pond EC in 77 %, the simulator's pH and EC in 83 to
  93 %. Only a stream that normally changes almost every sample can be "stuck"; one that is quiet by habit
  is left alone, and the longest-hold factor (4) keeps a probe that rests for up to an hour (the pond EC)
  quiet too. Only the factor and the habit judge real streams: the floor (5 minutes) matters only to a probe
  whose longest hold is under 75 seconds, which no real stream is.
- **Humidity, moisture and substrate temperature have no level check** (humidity varies 20 %RH a day, moisture
  follows irrigation, and a flagged level of substrate temperature could never be confirmed: Core has no
  calibration for it), so a jump is judged by speed, like air temperature: how far the field can really move since
  the last reading Pomona trusted. The allowances are the largest steps the real logs make (5-minute steps:
  humidity 8 to 15 %RH on 0.1 % of readings and 15 to 20 on 0.01 %, moisture 4.3 to 7.1 % at most, substrate
  temperature 0.4 to 0.8 C at most, each apart from isolated glitches), so a real ramp, an irrigation pulse or a
  heat spike (about 0.5 C per minute) stays well inside. A smaller offset than the allowance (+10 %RH humidity,
  +5 % moisture, +1 C substrate temperature) cannot be told from a real change in one sample and is not caught.
- **Air temperature has no level check** (it varies 10 C a day, so a distance from the 2 h median would flag
  every morning), so the step is judged by speed too. In 5-minute logs the allowance is 5 C, so only glitches
  trip it.
- **Noise needs the sample interval, and has to go nowhere.** Real humidity at 5 minutes swings a lot (the
  median step over 12 readings reaches 8 %RH in 0.2 % of windows), which is why the limit at 5 minutes is
  10 %RH. A legitimate swing is spread over more samples when readings come faster, so the limit shrinks with
  the square root of the interval, down to a floor above what a healthy simulated probe's windows reach (fake
  greenhouse, normal runs of seeds 1 to 80: the largest window median step is humidity 2.5 %RH, air 0.32 C,
  pH 0.06, moisture 1.5 %, substrate temperature 0.31 C). No real log is sampled faster than 5 minutes, so the
  scaling at 30 seconds (limit 3.2 %RH, 0.63 C, 0.16 pH; the floors 2.5 % and 0.5 C for moisture and substrate
  temperature) is argued from the physics and checked only against the simulator's normal runs (0 flags in
  seeds 1 to 80), not against real data. A fast ramp has large steps too (the quick scenario's dry zone loses
  3 to 4 % moisture per sample), so a window that mostly moved in one direction is not called noisy.
- **Slow drift is judged against the lagged spread only for a steady pH stream.** A pH probe that moves every
  sample (the simulator, the pond) has a spread that is its own noise, so the threshold may follow the older
  readings. For the real drain probes the same lagged spread flagged 2.2 to 2.3 % of the EC readings with the 2 h
  lapse (guard 2 %, 1.7 to 1.9 % today): they swing with every irrigation and the full spread is what keeps them
  quiet. EC never uses it, even when it changes every sample (Core still sends `spread_lag` for both): substrate EC
  really rises as the substrate dries (the fake greenhouse's dry zone: +0.4 or more), and the lagged threshold
  turned that into a "check the probe" card for about an hour around the real event in demo.json, which a real
  probe that changes every sample would get as well.
- **Moisture rewetting is exempt from the step check.** A rise from a trusted level below 15 % is not judged by
  speed: a dried-out slab is rewetted by one irrigation (the dry zone shows +40 % in one sample), and the real
  logs never get that dry (lowest 54 %, apart from one 0 % glitch), so they neither support nor contradict it. A
  fall and a rise from any wetter level keep the allowance.

Limits that remain:

- A pH or EC freeze shorter than about 8 to 10 minutes is not caught (the floor is 5 minutes, the stream's
  4 x longest hold is usually 8 to 14 minutes in the simulator, and a card needs 3 flagged readings), and a
  stream with fewer than 15 trusted steps before the freeze has no habit to judge.
- A second freeze of the same probe soon after the first needs more than 4 x the first freeze's trusted
  minutes: the first freeze's first 5 to 14 minutes were still trusted, so that stream now "rests" for that
  long and the second freeze must last 20 to 56 minutes (about 21 minutes in the scenario the game uses: a
  second 30-minute freeze 10 minutes after the first is caught after 20 to 24 minutes) for the 100 minutes
  (200 readings) the first one stays in the habit window. A percentile of the holds instead of the longest one
  would fix it and flags 3 to 30 times more real readings, so the longest hold stays. A probe that was already
  frozen before Pomona started watching it has no earlier habit and is not judged.
- A step is flagged for as long as it is physically impossible and then accepted as the new level without a
  calibration (a heat spike must not be held back): +4 C air for about 4 minutes, +15 %RH for about 4 minutes,
  +15 % moisture for about 8, +4 C substrate temperature for about 13. Removing a long drift snaps the reading
  back and trips the same check, so a 40-minute drift raises a sensor card only when it ends. The scorer does not
  credit that: a sensor card whose label run began after the fault's last reading is scored "MISSED (noticed only
  when it ended)" (verdict `caught_at_recovery`), in the game and in `make fake-greenhouse-score`.
- **Still MISSED in the game: a slow drift of air temperature, humidity, substrate moisture or substrate
  temperature** (0.1 C, 0.5 %RH, 0.5 %, 0.1 C per minute, 40 minutes: noticed only when it ends, which is scored
  as missed). A drift can only be told from the real thing by its level against the probe's recent past, and
  the real logs do not leave room for a level that catches these while they last. Real readings leave their
  trusted 2 h median by (1 % of readings / 0.01 % of readings): air 3.3 to 8.7 C / 6.5 to 14 C, humidity 12.6 to
  16.3 %RH / 27 to 50, substrate temperature 1.1 to 2.1 C / 6 to 10 C. The drifts reach 4 C, 20 %RH and 4 C
  at their end, so a limit that fires while they last is crossed by 1 % of real readings. Moisture leaves its
  median by 2 to 7 % / 7.4 to 12.7 %, so a limit near 13 % would fit the real logs, but the dry-zone event is a
  moisture fall of 1.2 %/min with the same signature at a different speed (a drift of 0.5 %/min is its slow
  version), and a level check would turn that event into "can't confirm the probe" and withhold its water-level
  card, which is worse than missing a drift. A pH drift is different: it is steep against a steady probe's own
  noise and is caught (0.02 pH per minute after about 18 minutes, 0.01 after about 36), while 0.005 per minute over
  two hours stays inside the window and is not.
- **EC slow drift is partly missed.** EC is judged against the whole-window spread (see above), which a drift in
  progress widens. A steep drift is caught (0.05 mS/cm per minute for 40 minutes, and 0.1), but 0.025 and
  0.0125 per minute over 80 to 120 minutes are caught in 2 of 3 seeds and otherwise noticed only when the drift
  ends, and demo.json's EC drift (0.05 per minute for only 15 minutes) is noticed only when it ends, as before this
  change.
- **Still MISSED: a noisy EC probe.** The Automatoes drain EC really jumps (1.0 % of its windows have a median
  step of 0.4 mS/cm or more, 0.29 % of 2 mS/cm), so every EC noise limit the real logs allow (above 2 mS/cm at 5
  minutes, 0.63 at 30 seconds) is beyond what a noisy simulated probe shows (median step 0.28). It is caught
  now and then when the noise pushes the level check over its threshold, which is luck, not detection.
- A frozen substrate-temperature probe (3 h of thermal mass; real slab probes hold one value for up to 9 h) is
  still missed, and so are jumps smaller than the allowances above.
