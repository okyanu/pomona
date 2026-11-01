# Pomona Sensor Quality Reasoner

The Sensor Quality Reasoner is the next planned small specialist model in Pomona's small-model factory.

Task:

```text
farm context + sensor JSON -> data quality labels + missing fields + suspect fields + safe next checks
```

This model answers a question that should happen before risk or action reasoning:

```text
Is this sensor data usable enough to reason from?
```

## Why This Model Exists

Pomona should not classify crop risk from bad telemetry. Missing pH, impossible humidity, stale timestamps, unit mismatches, sensor drift, and conflicting readings can make downstream models unsafe or misleading.

This model is crop-agnostic and useful across:

- tomato,
- strawberry,
- lettuce,
- hydroponic systems,
- substrate greenhouses,
- soil farms,
- future aquaponic or oceanic farm systems,
- digital twin inputs.

## Input Shape

```json
{
  "farm_context": {
    "crop": "tomato",
    "system_type": "controlled_greenhouse",
    "zone_id": "greenhouse-a"
  },
  "sensor": {
    "air_temperature_c": 24.0,
    "humidity_pct": 68.0,
    "ph": 6.2,
    "ec_ms_cm": 2.4,
    "substrate_moisture_pct": 45.0,
    "timestamp": "2026-07-07T10:00:00Z"
  },
  "expected_fields": ["air_temperature_c", "humidity_pct", "ph", "ec_ms_cm"]
}
```

## Output Shape

```json
{
  "data_quality_labels": [],
  "missing_fields": [],
  "suspect_fields": [],
  "safe_next_checks": ["continue routine monitoring"],
  "human_review_required": false,
  "rationale": "Critical sensor readings are present and inside plausible ranges."
}
```

## Allowed Labels

```json
[
  "missing_ph",
  "missing_ec",
  "missing_temperature",
  "missing_humidity",
  "missing_moisture",
  "impossible_ph",
  "impossible_ec",
  "impossible_temperature",
  "impossible_humidity",
  "stale_reading",
  "unit_mismatch",
  "sensor_drift_possible",
  "stuck_value",
  "flatline_possible",
  "baseline_drift_possible",
  "noisy_signal_possible",
  "conflicting_readings",
  "insufficient_context"
]
```

## Veto and trust verdict

A reading that failed the sensor check is not reasoned on. After the sensor-quality
reasoner runs, `services/model-router/app/trust_gate.py` removes every field in
`suspect_fields` and `missing_fields` (plus companions of the same measurement,
such as `previous_ph` or `backup_air_temperature_c`) from the sensor packet and
from every history frame before the water, nutrient and tomato specialists see
it. An impossible pH 13 therefore no longer becomes a `high_ph` label, and a
drifted EC no longer becomes `high_ec`. The actuator/safety gate still receives
the original packet and the quality result.

The gate returns `{trust_verdict, vetoed_fields, global_veto, reason}`, copied into
`final_decision` of `/v1/pipeline/evaluate` (and `trust_gate` of the shared chain):

| `trust_verdict` | Meaning |
|---|---|
| `trusted` | The sensor check found nothing. Specialists see the whole packet. |
| `partial` | Some fields are vetoed; the other expected fields are still reasoned on. |
| `cannot_confirm` | Nothing can be confirmed: a stale/invalid timestamp, `stale_reading`, `insufficient_context` or `unit_mismatch` (global veto), or every expected field is vetoed. Specialists return empty results (`source: "sensor_veto"`). |

`partial` and `cannot_confirm` keep `human_review_required` true and `risk_level`
"high". The automation engine turns any sensor-check label into a sensor card (`sensor_check`; the softer
`flatline_possible` hint has its own rule, `sensor_flatline`, which waits the usual 10 minutes) instead of a dosing card. `make fault-replay` measures how many wrong domain
labels are still shown as trusted per injected fault
([SENSOR_FAULT_REPLAY.md](./SENSOR_FAULT_REPLAY.md)). The veto cannot help when the
sensor check itself raises nothing, for example a constant in-range offset.

## Sticky trusted reference (Core feed only)

The temporal checks above only remember the last 11 packets, so a step or a frozen probe becomes
the new "normal" within minutes and the flag stops (about 8 consecutive readings at 30 s) while the
fault is still there. Core's outcome feed therefore sends an optional `stream_baseline` with each
evaluation (`POST /v1/pipeline/evaluate`): per field `{median, n, window_s, spread, last_change_at}`.

- `median`: the median of that probe's earlier readings in which the field was **not vetoed**, within
  2 h (`TRUST_BASELINE_WINDOW_S`) of the newest **trusted** reading (not of "now"), from the latest
  calibration for that probe on. At least 6 trusted readings (`TRUST_BASELINE_MIN_N`) are needed. A probe
  that has been broken for six hours is therefore still judged against the readings from before it broke.
  Core records each reading's verdict in the `event_trust` table and builds the reference with
  `services/core/app/trusted_baseline.py` (stdlib only, shared with the fake-greenhouse scorer).
- `spread`: the window's 10th-to-90th percentile range, how far the probe normally wanders.
- `last_change_at`: when the current run of identical values began, over all readings.

With it the router flags `baseline_drift_possible` while pH differs from the trusted median by 0.35 or
EC by 0.4 (the existing thresholds) **and** by 3 times the probe's own spread, so the flag lasts as long
as the fault, the veto holds, and no wrong domain card follows; and `stuck_value` when a reading repeats
for longer than 45 min (air temperature), 30 min (humidity), 6 h (substrate temperature) or 3 h (water
temperature). The check text tells the operator to verify with a meter and, if the reading is right, to
record a calibration (`POST /v1/sensors/calibrations`) for that probe: a calibration resets the
reference (after 6 trusted readings at the new level the flag clears and the domain card can raise).
**A flagged level stays "can't confirm" until a calibration**, however long that takes and however
many hours the fault lasts; its `sensor_check` incident stays open meanwhile. An operator can opt into a
lapse with `TRUST_BASELINE_MAX_AGE_S` (seconds after the newest trusted reading; the probe is then judged by
the 11-packet checks again and trusted silently). Without `stream_baseline` the rules are exactly the
11-packet rules above. The dashboard's pipeline view and the shared chain send no stream state, so they do
not have the sticky check yet.

The limits come from the real logs (`make real-replay`, whose "sticky" pass replays them the way Core's
feed does): pH and EC are not checked for "stuck" because drain and tank probes sit on one value for
hours as a matter of course (80 % of real readings are beyond 20 minutes); air temperature and humidity
limits keep real-log false flags under 0.15 % of readings; substrate temperature needs 6 h because real
slab probes hold one 0.1 C value for up to 9 h; and a drift needs 3 times the probe's own spread because real
drain pH and EC leave their 2 h median by 0.35 / 0.4 on 1 to 3 % of readings. Moisture has no persistent
check (a hydroponic zone sends a constant placeholder). The unattended numbers are high on historical logs
for a reason that is not a defect, see [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md#longer-memory-in-cores-feed).

## Related design drafts

- Temporal stuck / flatline / baseline drift: [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md) (implemented locally in deterministic rules)
- Calibration events and tagged corrections: [CALIBRATION_PROVENANCE.md](./CALIBRATION_PROVENANCE.md)
- Backlog index: [LATER_PATTERNS_BACKLOG.md](./LATER_PATTERNS_BACKLOG.md)

## Relationship To Other Models

Recommended reasoning order:

```text
sensor quality reasoner
  -> tomato/crop risk reasoner
  -> safety triage reasoner
  -> deterministic safety checker
  -> dashboard / human approval
```

## Current Status

Status (2026-09-27): **model training paused; the deterministic rules are the
authority.** Two controlled retrains on `Qwen/Qwen3.5-0.8B` failed the publish
gate on a 123-case holdout (best label F1 0.684). Better data fixed missing,
invalid and normal packets, but the model could not reliably do exact
timestamp arithmetic (stale/future) or range-edge comparisons, which
`services/model-router/app/sensor_quality.py` already computes exactly. Details
and reopen criteria: `models/registry/sensor-quality-reasoner-v0.1.yaml`
(`decision` and the v0.1.4/v0.1.5 pilot). The history below is kept for context.

Generated train/validation/test files live under `datasets/processed/` and are ignored by Git.

Local generated artifacts:

- `datasets/processed/pomona-sensor-quality-v0.1/`: first balanced generated split.
- `datasets/processed/pomona-sensor-quality-v0.1.1-boundary/`: boundary-focused split for improving label confusion.
- `private/colab/pomona-sensor-quality-v0.1.1-boundary-training-data.zip`: local Colab upload zip.
- `private/colab/pomona_sensor_quality_reasoner_v0_1_1_boundary_colab.ipynb`: local Colab training notebook.

The v0.1.1 boundary split adds contrast cases for:

- `unit_mismatch` vs `conflicting_readings`,
- `impossible_*` vs `sensor_drift_possible`,
- `missing_*` vs `insufficient_context`,
- normal complete packets vs `stale_reading`.

Do not publish the first v0.1 sensor-quality adapter until it improves on boundary evaluation.
