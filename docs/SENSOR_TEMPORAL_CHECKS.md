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
