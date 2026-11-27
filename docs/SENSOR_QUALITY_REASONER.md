# Pomona Sensor Quality Reasoner

The Sensor Quality Reasoner is a small specialist model in Pomona's small-model factory. A local adapter was trained; training is paused and the deterministic sensor checks below do the work (see Current Status).

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

`POST /v1/pipeline/evaluate` also takes an optional `device_fields` (list of reading field names). Core's outcome feed
sends it only for a device in a multi-device zone (`docs/design/multi-device-zones.md`): the fields that device has
reported in the last 7 days. Without an explicit `expected_fields`, the router then expects only those of the system
type's fields (a moisture field counts when any moisture name is present; an empty result falls back to the full list),
and the tomato reasoner skips the others as missing critical data. An explicit `expected_fields` always wins. Absent
`device_fields`, nothing changes.

`POST /v1/pipeline/evaluate` and the shared chain (`POST /v1/reasoners/shared-chain`) also take three optional keys for a
zone snapshot (`docs/design/multi-device-zones-slice2.md` 2.3), where the sensor packet is built from several devices
and has no history of its own, so a persistent fault such as a stuck probe is invisible to the router and arrives as
the check result of the device the reading came from:

- `known_vetoed_fields`: fields a device's own check did not trust. Names that are not known sensor fields are
  dropped.
- `known_data_quality_labels`: labels from that check; at most 50, each matching `^[a-z_]{1,64}$`, others dropped.
- `known_safe_next_checks`: the matching checks; at most 20, each at most 300 characters, others dropped.

They are merged into the sensor quality right after the sensor-quality reasoner and before the gate:

- Labels are added, except `stale_reading`, `insufficient_context` and `unit_mismatch` (the global veto labels: one
  device's stale packet must not veto the whole zone, so the dashboard turns them into vetoed fields) and any
  `missing_*` label (the router decides missing fields on the snapshot itself).
- A known vetoed field becomes a suspect field only when the sensor holds a value for it; a field the snapshot does not
  hold is the router's own missing-field call. The gate then treats it like any suspect field: it is named in the one
  reason string, takes its companion fields with it (a carried `ph` veto also vetoes `previous_ph`), and counts toward
  `cannot_confirm` when every expected field ends up vetoed.
- Known checks not already present are appended, and `continue routine monitoring` is removed when any other check is
  there. Anything added makes human review required; labels added to a clean result give the "Sensor packet needs
  verification" rationale.
- `from_device_checks` (`data_quality_labels` and `vetoed_fields` that were added) is added to the sensor quality
  block. It is absent when nothing was added.

Absent keys: no merge runs, no new key appears, and the output is byte-identical. The JavaScript gate mirrors under
`spaces/*/trust_gate.js` do not implement the merge, because their parity cases never send these keys.

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

The result gains one optional key, `pair_disagreement_fields` (a list of field names), only when the pair check flagged a
field on this reading (see [Pair check](#pair-check-two-or-more-probes-in-one-zone)).

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
evaluation (`POST /v1/pipeline/evaluate`): per field `{median, n, window_s, spread, last_change_at}`, plus
the optional `last_value` / `last_at` and, for pH and EC, `change_share` / `change_steps` / `longest_run_s`
(older Cores omit them and the new checks stay off).

- `median`: the median of that probe's earlier readings in which the field was **not vetoed**, within
  2 h (`TRUST_BASELINE_WINDOW_S`) of the newest **trusted** reading (not of "now"), from the latest
  calibration for that probe on. At least 6 trusted readings (`TRUST_BASELINE_MIN_N`) are needed. A probe
  that has been broken for six hours is therefore still judged against the readings from before it broke.
  Core records each reading's verdict in the `event_trust` table and builds the reference with
  `services/core/app/trusted_baseline.py` (stdlib only, shared with the fake-greenhouse scorer).
  `stream_baseline` there walks the stored readings back from the newest (one pass for all fields, ending
  as soon as a field's run, window and norm are settled); the in-process engine behind the fake-greenhouse
  scorer and the "Try to fool Pomona" Space keeps the same answer up to date one reading at a time with
  `StreamBaseline` instead, so a late reading costs about as much as the first one. `stream_baseline` is the
  reference: the tests hold the two byte for byte equal, scan-limit overflow and out-of-order arrival included.
- `spread`: the window's 10th-to-90th percentile range, how far the probe normally wanders.
- `last_change_at`: when the current run of identical values began, over all readings.
- `last_value` / `last_at`: the newest trusted reading (a step is judged against it).
- pH and EC only, `change_share` / `change_steps` / `longest_run_s`: over the last 200 trusted readings
  before the current identical run, the share of steps in which the value changed and the longest hold in
  seconds. They tell a probe that normally moves every sample from a drain probe that sits still for hours.
- pH and EC only, `spread_lag`: the spread of the window's trusted readings that are older than half an hour
  (left out with fewer than 6). A slow drift is trusted until it is a threshold away and widens `spread` until
  3 x spread hides it; the router judges a pH stream that changes every sample against `spread_lag` instead (EC keeps
  the full spread: its level really rises as a substrate dries).

With it the router flags `baseline_drift_possible` while pH differs from the trusted median by 0.35 or
EC by 0.4 (the existing thresholds) **and** by 3 times the probe's own spread, so the flag lasts as long
as the fault, the veto holds, and no wrong domain card follows; and `stuck_value` when a reading repeats
for longer than 45 min (air temperature), 30 min (humidity), 6 h (substrate temperature) or 3 h (water
temperature); for pH and EC only when the stream normally changes in at least 70 % of its steps, and then
after 5 minutes and 4 times its longest hold (a drain probe that sits still for hours is never judged).
Two more checks run on the same path: `sensor_drift_possible` when air temperature (3 C, 1 C per minute),
humidity (12 %RH, 4 per minute), substrate moisture (8 %, 2 per minute) or substrate temperature (1.5 C, 0.3 per
minute) differs from the newest trusted reading by more than the larger of the two allowances (the second is
multiplied by the minutes since that reading), and `noisy_signal_possible` when humidity, air temperature,
pH, substrate moisture or substrate temperature has a median step over 12 readings beyond its limit (10 %RH / 2 C /
0.5 pH / 1 % / 0.4 C at 5-minute samples, shrinking with the square root of the interval to a floor of 3 %RH /
0.4 C / 0.1 pH / 2.5 % / 0.5 C) without having simply moved in one direction. EC has its own fixed limit, 0.20 mS/cm
over 12 readings, used as it is and only when the window's median sample interval is 90 seconds or less (real
10-second tank EC never reaches it; a slower stream, such as 5-minute drain EC that jumps by itself, is not judged);
see
[SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md#stream-habit-checks-in-cores-feed-2026-11-02-widened-2026-11-05). The
check text tells the operator to verify with a meter and, if the reading is right, to
record a calibration (`POST /v1/sensors/calibrations`) for that probe: a calibration resets the
reference (after 6 trusted readings at the new level the flag clears and the domain card can raise).
**A flagged level stays "can't confirm" until a calibration**, however long that takes and however
many hours the fault lasts; its `sensor_check` incident stays open meanwhile. An operator can opt into a
lapse with `TRUST_BASELINE_MAX_AGE_S` (seconds after the newest trusted reading; the probe is then judged by
the 11-packet checks again and trusted silently). Without `stream_baseline` the rules are exactly the
11-packet rules above. The dashboard's pipeline view and the shared chain send no stream state, so they do
not have the sticky check yet.

The limits come from the real logs (`make real-replay`, whose "sticky" pass replays them the way Core's
feed does): pH and EC have no fixed "stuck" limit because drain and tank probes sit on one value for
hours as a matter of course (80 % of real readings are beyond 20 minutes), so they get the adaptive check
that leaves such probes alone (0 pH and at most 0.02 % of EC readings flagged); the air temperature, humidity,
moisture and substrate-temperature step limits and the noise limits keep the flag rate on real logs under 0.15 % of
readings (the logs are not labelled, so not every flag is known to be false) (and on 3 months of real 10-second data the 30-second air, humidity and pH noise limits and the fast EC
noise limit flag none); substrate temperature needs 6 h because real
slab probes hold one 0.1 C value for up to 9 h; and a drift needs 3 times the probe's own spread because real
drain pH and EC leave their 2 h median by 0.35 / 0.4 on 1 to 3 % of readings. Moisture has no persistent stuck
or level check (a hydroponic zone sends a constant placeholder), only the step and noise checks. The unattended numbers are high on historical logs
for a reason that is not a defect, see [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md#longer-memory-in-cores-feed).

## Pair check: two or more probes in one zone

A slow drift of one probe cannot be told from the real thing by comparing the probe with its own past: real readings
leave their own 2 h median by more than the whole drift of the game. A second probe in the same zone sees the same
weather and the same irrigation, so the **difference** between the two barely moves in a real event and does move when
one probe drifts. The design and its evidence are in `docs/design/slow-drift-pair-check.md`.

Core's outcome feed adds a `pair` entry to a field's `stream_baseline` entry, only when the zone has another device
that reports the same field (multi-device zones, see
[HARDWARE_EVENT_CONTRACT.md](./HARDWARE_EVENT_CONTRACT.md)):

```json
"pair": {"offset": -1.5, "n": 40, "partner_value": 61.2, "partners": 1,
         "partner_device": "climate-2", "device": "climate-1"}
```

- `offset`: the usual difference, `own - partner`: the median over the probe's earlier readings in the 2 h window that
  were not vetoed and had the same partner device(s) as now. `n` is how many; at least 12 are needed (`PAIR_MIN_N`:
  6 minutes at 30 s, 1 hour at 5 minutes), else there is no `pair` entry.
- `partner_value`: what the other probes read now. With one partner it is that probe's latest reading; with several it
  is the median of their latest readings (the mean of the middle two for an even count; at most 8 partner devices).
  `partners` is how many were used, `partner_device` is set only when there is exactly one, and `device` is the probe
  being judged.
- **Which partner readings count.** Another device of the same farm and zone, matched through the moisture aliases
  (`substrate_moisture_pct` pairs with `soil_moisture_pct`). Its reading is earlier than the probe's own and not older
  than 2.5 times the probe's own median interval (60 to 750 seconds), so one missed packet does not drop the partner.
  It has been judged (it has an `event_trust` row), is a finite number and was not vetoed on that field. A flagged
  reading therefore stops serving as a partner, so a fault caught on one probe does not make the other look wrong.
  A device whose readings of the field are all one value (a constant moisture placeholder on a hydroponic zone) is not
  a partner. If the partner set changes (a probe goes quiet or joins), the usual difference is collected afresh against
  the new set.
- **Calibration.** A calibration of the field on **any** device of the zone restarts the pair reference for every
  device (the grower has just checked a probe with a meter). Own-stream references are not affected. Calibrate only the
  probe that was wrong: calibrating the good one makes today's difference the new normal.
- **Cadence.** A stream whose median interval is over 5 minutes is not paired and not judged. Such a device can still
  serve as a partner when its readings are fresh enough.
- **Fast-change skip.** A reading whose own step from the previous reading is a third of the limit or more (air
  1.0 C, humidity 3.3 %RH, moisture 2.7 %) is not judged: the partner's reading is always earlier, so a change both
  probes share (an irrigation pulse, a humidity step) shows up in the own reading before the partner has reported
  it. Core then sends no `pair` entry for that reading. The next reading is judged normally. A drift at the game's rates never
  triggers the skip.

The router's check (`apply_persistent_checks` in `services/model-router/app/sensor_quality.py`) computes
`moved = (current - partner_value) - offset` and, when `|moved|` reaches the limit, adds `baseline_drift_possible`,
the field as a suspect field and a check text:

| Field | Limit | 40-minute game drift caught after |
|---|---|---|
| `air_temperature_c` | 3.0 C | about 30 minutes (0.1 C per minute) |
| `humidity_pct` | 10 %RH | about 20 minutes (0.5 %RH per minute) |
| `soil_moisture_pct`, `substrate_moisture_pct` | 8 % | about 16 minutes (0.5 % per minute) |

A card needs 3 flagged readings in a row, which adds 1 to 1.5 minutes at 30-second sampling. The times assume 2 hours
of drift-free history. The limits do not scale with the sample rate. Substrate temperature, pH and EC have no pair check
(substrate temperature has no calibration path, so a flagged pair could never be cleared).

- **Check text**, first in `safe_next_checks`:
  `pair check: humidity_pct on climate-1 is 10.4 %RH lower than usual against climate-2 (now -11.9, usually -1.5). Check both with a meter; calibrate only the one that was wrong.`
  With several partners it says "against the median of 3 other probes in this zone". It names both devices because Core
  stores the text and passes it on to the other devices' evaluations. Device ids are cut to 32 characters and lose control
  characters; the whole text stays under the 300-character limit for known checks.
- **No separate clear threshold.** A flagged reading is vetoed and stays out of the usual difference, so the flag lasts for
  as long as `|moved|` stays over the limit.
- **Which probe is flagged.** In a zone with two probes it is close to a coin flip which one crosses the limit first,
  so the card may land on the good probe. With three or more probes the drifter is compared with the median of the
  others and crosses first. Either way the text asks for a meter on both. When no partner reading is usable (the other
  probe is silent, unjudged or vetoed), nothing is judged and the flag clears; an alert already raised stays until its
  clear window passes.
- **`pair_disagreement_fields`**: the sensor-quality result gains this list (the fields the pair check flagged on this
  reading) only when it is not empty, so every other output is unchanged. Core stores it per judged reading, and
  the zone view uses it: while any live device of a zone has a pair flag on a field, the zone treats that field as
  "can't confirm" for every probe (no advice uses either value). The dashboard's air or humidity tile shows both values
  with "probes disagree: check both with a meter", and the trust line names the first probe (for example "Can't
  confirm: humidity (climate-1) not used"). It ends when no device's latest reading carries the
  flag. Moisture has no zone tile, so a moisture disagreement shows only on the trust badge.
- **`PAIR_CHECK`.** Core's setting `pair_check` (environment variable `PAIR_CHECK`, default on) turns the whole pair
  path off: no `pair` entry and no partner query. `PAIR_CHECK=0` leaves multi-device zones otherwise unchanged;
  `MULTI_DEVICE_ZONES=0` turns the pair check off too, because every zone is then judged as one stream. The in-process
  engine of the fake greenhouse takes `pair_check=True` as a constructor argument.
- **Limits.** A zone with one probe is not helped, and both probes drifting alike are not caught. The limits come from
  one hydroponic chamber (four probes, 30-second readings, about 107 days) and one greenhouse (two slab probes per
  compartment, 5-minute readings), where the worst real pair crosses them now and then: a few false cards on one pair, and four
  moisture cards from slab glitches in one compartment (accepted, each says "check both probes"). The check is not
  mirrored in the browser checker (`spaces/sensor-data-checker/persistent.js`), which judges one uploaded stream. See
  [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md) for the real-data numbers.

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
