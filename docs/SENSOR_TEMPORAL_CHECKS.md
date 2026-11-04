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
| `stuck_value` | The latest value has repeated ≥ 3 times **and** ≥ 2× the longest earlier repeat, after the field had varied; for water and substrate temperature the repeat must also span ≥ 3 h of sample time | Continuous sensors are caught after 3 identical samples; quantized probes (DS18B20 0.0625 °C steps) that legitimately repeat 2–3 times need a longer freeze. Thermal mass holds a DS18B20 step for hours (real pond: 99th percentile 2.25 h, longest 4.75 h), so at 5-minute samples and an 11-packet window this cannot fire for those two fields; their probe error codes are still caught by range checks |
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
`spaces/sensor-data-checker` mirrors these rules (`make test-checker`).

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

## Stream-habit checks in Core's feed (2026-11-02)

The "Try to fool Pomona" game ([FAKE_GREENHOUSE.md](./FAKE_GREENHOUSE.md)) showed four sensor lies the checks
above missed. Three checks now close them. All need Core's `stream_baseline` (they judge a reading against
its own stream, so they run in the Core feed and the in-process engine, not in the 11-packet rules the
browser checker mirrors in JavaScript) and every threshold was set on the real logs (`make real-replay`,
5-minute samples, budget about 0.15 % of readings per stream).

| Check | Fires when | Real-data share flagged |
|---|---|---|
| `stuck_value` for pH and EC (adaptive) | The value repeats for longer than 15 minutes **and** 4 times the longest hold the stream showed in its last 200 trusted readings, **and** the stream changed in at least 70 % of those steps (15 steps minimum). Core sends `change_share`, `change_steps`, `longest_run_s` for pH and EC | pH: 0 of 7 real streams. EC: 0.02 % (IUACAAS, no-lapse replay only), 0.004 % (Automatoes), 0 elsewhere |
| `sensor_drift_possible` for air temperature (step) | The reading differs from the newest trusted reading (`last_value`, `last_at`) by more than max(3 C, 1 C per minute since that reading). A flagged reading is vetoed, so the reference stays put and the step stays flagged until the allowance has grown to cover it (4 minutes for 4 C), then the new level is accepted | 0.054 % of the Reference compartment (it holds 17 C glitches), 0.002 % in two others, 0 in three |
| `noisy_signal_possible` for humidity and air temperature | The median step over the last 12 readings is at least the limit: 10 %RH / 2 C scaled by the square root of the sample interval over 5 minutes, never below 3 %RH / 0.4 C | humidity: 0.084 % (AICU), 0.056 % (IUACAAS), 0.025 % (Digilog), about 0 elsewhere; air: 0.029 % (Reference), about 0 elsewhere |

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
  quiet too.
- **Air temperature has no level check** (it varies 10 C a day, so a distance from the 2 h median would flag
  every morning), so the step is judged by speed: how far air can really move since the last reading it
  trusted. A heat spike ramps about 0.5 C per minute and never reaches the allowance, so it stays a real event
  (a heat card, not a sensor card). In 5-minute logs the allowance is 5 C, so only glitches trip it.
- **Noise needs the sample interval.** Real humidity at 5 minutes swings a lot (the median step over 12
  readings reaches 8 %RH in 0.2 % of windows), which is why the limit at 5 minutes is 10 %RH. A legitimate
  swing is spread over more samples when readings come faster, so the limit shrinks with the square root of
  the interval, down to a floor several times a healthy probe's noise. No real log is sampled faster than
  5 minutes, so the scaling at 30 seconds (limit 3.2 %RH, 0.63 C) is argued from the physics and checked only
  against the simulator's normal runs (0 new flags in 23 seeds), not against real data.

Limits that remain:

- A pH or EC freeze shorter than about 16 minutes is not caught (the floor is 15 minutes, and a card needs 3
  flagged readings), and a stream with fewer than 15 trusted steps before the freeze has no habit to judge.
- A second freeze of the same probe soon after the first is missed: the first freeze's first 15 minutes were
  still trusted, so that stream now "rests" for 15 minutes and needs 4 x 15 = 60 minutes. A percentile
  of the holds instead of the longest one would fix it and flags 3 to 30 times more real readings, so the
  longest hold stays. A probe that was already frozen before Pomona started watching it has no earlier habit
  and is not judged.
- A step of 4 C is flagged for about 4 minutes and then accepted as the new level without a calibration (a
  heat spike must not be held back). Removing a long drift snaps the reading back and trips the same check, so
  a 40-minute air-temperature drift raises a sensor card only when it ends. The scorer does not credit that: a
  sensor card whose label run began after the fault's last reading is scored "MISSED (noticed only when it
  ended)" (verdict `caught_at_recovery`), in the game and in `make fake-greenhouse-score`.
- Not covered by the new checks, and still MISSED in the game: a jump or drift on humidity, substrate moisture
  or substrate temperature, a slow drift on air temperature, EC or pH (0.1 C, 0.05 mS/cm, 0.02 pH per minute,
  40 minutes: noticed only when it ends, which is scored as missed), a noisy pH, EC, moisture or
  substrate-temperature probe, and a frozen substrate-temperature probe (3 h of thermal mass).
