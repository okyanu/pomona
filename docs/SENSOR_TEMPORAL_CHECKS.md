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
