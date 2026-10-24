# Sensor fault replay

Run `make fault-replay` from the repository root after local dependency setup.
It prints JSON and returns **exit 1 when any detectable injected fault is missed
or a normal frame raises a review flag** (`plausible_offset`, marked
`detectable: false`, is reported but excluded from that gate). This is a
diagnostic acceptance benchmark, not a promise that today's baseline passes. Unit tests separately verify that
known gaps are reported honestly.

The offline harness calls the actual deterministic sensor-quality function,
with an explicit advancing clock and accumulating history. Twelve synthetic
sequences contain 12 frames each: normal, spike, missing pH, conflicting
probes, dropout, slow drift, stuck temperature, sustained impossible pH, and
(since 2026-10-24) a plausible EC offset, a pH jump, an EC drift to high and a
stuck high humidity.
Normal frames follow each fault to test recovery. No network, models,
databases, or actuators are used.

## Trusted-wrong per fault, observed 2026-10-24

Detection is not the goal; a wrong card shown as reliable is the harm. For every
frame the harness also builds the same frame before the fault was injected (the
clean counterpart) and computes domain labels with the deterministic water,
nutrient and tomato rules three ways: clean, faulty **ungated** (the old
behaviour) and faulty **gated** (sensor check, then the veto in
`app/trust_gate.py`, then the specialists). No network, no audit writes.

Definitions (also in the JSON `metric_definitions`):

- **faulty frames**: frames where a fault was injected, whether or not a detector can catch it.
- **wrong (labels)**: the frame's domain labels differ (either direction) from the clean counterpart's.
- **wrong cards**: the same, restricted to *card labels*, the labels matched by a rule in `services/automation-engine/app/rules.yaml` other than `sensor_check` (loaded from the YAML). Only these make an advice card.
- **trusted-wrong ungated**: wrong on the raw faulty reading and the sensor check raised nothing.
- **trusted-wrong gated**: wrong after the veto and `trust_verdict` is not `cannot_confirm`, so a wrong label (or card) is still shown as reliable.
- **cannot confirm / partial**: faulty frames with that verdict.
- **rate**: trusted-wrong / faulty frames (`trusted_wrong_rate_*`, `trusted_wrong_cards_rate_*`).

Label metric:

| Sequence | Faulty frames | Wrong ungated | Trusted-wrong ungated | Wrong gated | Trusted-wrong gated | Cannot confirm | Partial |
|---|---:|---:|---:|---:|---:|---:|---:|
| Spike | 1 | 1 | 0 | 0 | 0 | 0 | 1 |
| Missing pH | 6 | 6 | 0 | 0 | 0 | 0 | 6 |
| Conflicting probes | 6 | 0 | 0 | 0 | 0 | 0 | 6 |
| Dropout | 6 | 0 | 0 | 0 | 0 | 3 | 0 |
| Slow drift | 6 | 0 | 0 | 0 | 0 | 0 | 3 |
| Stuck value | 6 | 0 | 0 | 0 | 0 | 0 | 5 |
| Sustained impossible pH | 6 | 6 | 0 | 0 | 0 | 0 | 6 |
| pH jump 6.0 to 7.6 | 6 | 6 | 1 | 1 | 1 | 0 | 5 |
| EC drift to high | 9 | 5 | 0 | 0 | 0 | 0 | 7 |
| Stuck humidity at 88 % | 6 | 6 | 2 | 2 | 2 | 0 | 4 |
| Plausible offset (undetectable) | 12 | 12 | 12 | 12 | 12 | 0 | 0 |
| **Detectable sequences** | 58 | 30 | 3 | 3 | 3 | 3 | 43 |
| **All sequences** | 70 | 42 | 15 | 15 | 15 | 3 | 43 |

Card metric (same frames, card labels only):

| Sequence | Faulty frames | Wrong cards ungated | Trusted-wrong cards ungated | Wrong cards gated | Trusted-wrong cards gated |
|---|---:|---:|---:|---:|---:|
| Spike | 1 | 0 | 0 | 0 | 0 |
| Missing pH | 6 | 0 | 0 | 0 | 0 |
| Conflicting probes | 6 | 0 | 0 | 0 | 0 |
| Dropout | 6 | 0 | 0 | 0 | 0 |
| Slow drift | 6 | 0 | 0 | 0 | 0 |
| Stuck value | 6 | 0 | 0 | 0 | 0 |
| Sustained impossible pH | 6 | 0 | 0 | 0 | 0 |
| pH jump 6.0 to 7.6 | 6 | 6 | 1 | 1 | 1 |
| EC drift to high | 9 | 5 | 0 | 0 | 0 |
| Stuck humidity at 88 % | 6 | 6 | 2 | 2 | 2 |
| Plausible offset (undetectable) | 12 | 12 | 12 | 12 | 12 |
| **Detectable sequences** | 58 | 17 | 3 | 3 | 3 |
| **All sequences** | 70 | 29 | 15 | 15 | 15 |

What the numbers say:

- **Original sequences.** The old pipeline already made no wrong advice card for
  them. An impossible pH 13 or a missing pH never became `high_ph`: the nutrient
  and tomato rules have their own impossible-value guards (pH of 9 or more, or
  3.5 or less, gives `sensor_anomaly`; a missing pH gives `missing_critical_data`),
  and no automation rule matches those labels. The veto still removes the 13
  wrong labels (`sensor_anomaly`, `missing_critical_data`), but that is hygiene,
  not a card that was prevented.
- **Plausible but faulty readings** (the three added sequences) are where the veto
  matters. A pH of 7.6, an EC of 4.5 to 5.5 mS/cm or a humidity of 88 % are
  inside the plausible range, so the specialists label them `high_ph`, `high_ec`
  and `fungal_pressure`, and those make cards ("check water/dosing system",
  "review nutrient dosing", "increase ventilation"). On the detectable sequences
  the old pipeline made 17 wrong cards; after the veto 3 remain. The 3 are frames
  before a detector can fire: the pH is steady after the jump until the startup
  baseline check has three samples, and a freeze or a drift needs three samples
  too. Those frames are wrong and trusted, and stay in the count.
- The veto's gain is mostly **wrong cards that used to carry a flag**: the sensor
  check had fired, but the card was still made. That is why the 14 vetoed cards do
  not show up in `trusted_wrong` (the ungated pipeline did set `human_review`).
  They are visible in `wrong_cards_ungated` against `wrong_cards_gated`.
- **`plausible_offset` is still not caught.** EC reads a constant 5.0 mS/cm instead
  of 2.0 from frame 0, inside the plausible range with no baseline to drift from,
  so the sensor check raises nothing and `high_ec` is shown as trusted
  (`detectable: false`, excluded from `passed`, counted in the totals). The offset
  is +3.0 because +1.5 (3.5 mS/cm) is wrong in value but crosses no domain
  threshold, so the label metric would not see it.
- Overall `trusted_wrong_rate_gated` equals the ungated rate, 15 / 70 = 0.2143,
  for both labels and cards: the 12 offset frames dominate, and the veto cannot
  help what the sensor check does not flag.

Limitations: synthetic faults, one frame-level comparison against the clean
frame (a wrong value that keeps the same label is not counted, and a coincidentally
right label is), and one fixed packet shape. `ec_drift_high` does not recover
(its drift/noise flags would linger after a return to 2.0, which the frames after
the fault would count as false positives), and `stuck_humidity_high` assumes a
probe that latches at 88 % while the true value stays near 60 %. The gate cannot
catch a plausible but wrong reading; that needs a reference or "is this familiar"
layer, for example a second probe, a manual check or a learned per-zone baseline.

## Baseline observed 2026-09-23 (temporal checks)

| Sequence | Detected faulty frames | Missed faulty frames |
|---|---:|---:|
| Spike | 1 | 0 |
| Missing pH | 6 | 0 |
| Conflicting probes | 6 | 0 |
| Dropout | 3 | 0 |
| Slow drift | 3 | 0 |
| Stuck value | 5 | 0 |
| Sustained impossible pH | 6 | 0 |

Fault annotations for dropout / stuck / slow-drift start only when the
deterministic detectors can honestly fire (staleness age, freeze window, or
baseline delta). Earlier pre-threshold frames are not counted as false
negatives. Dropout still uses a frozen last-packet timestamp, not broker
failure. **No learned model runs in this benchmark**.

Design notes: [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md).

## Prior baseline 2026-09-06 (packet-level only)

| Sequence | Detected faulty frames | Missed faulty frames |
|---|---:|---:|
| Spike | 1 | 0 |
| Missing pH | 6 | 0 |
| Conflicting probes | 6 | 0 |
| Dropout | 3 | 3 |
| Slow drift | 0 | 6 |
| Stuck value | 0 | 6 |
| Sustained impossible pH | 6 | 0 |

Flat or slowly changing readings can be legitimate. Stuck checks require prior
variation so long plateaus (for example stable humidity) do not alert. Do not
convert an evaluator's injected-fault annotation into detector input.

Reported timing measures the rule function only. It excludes transport,
database, model latency, and memory usage. This synthetic fixture is neither a
field-validation dataset nor a replacement for independent model evaluation.

## Real-data replay 2026-09-28

`make real-replay` runs `scripts/benchmark_real_sensor_replay.py` over two real
third-party logs kept locally in `datasets/raw/` (licenses and checksums in
`datasets/sources/`). A dataset that is not downloaded is reported as skipped.
These logs have **no fault annotations**, so the report counts labels per field
(each field is also replayed alone for clean attribution) and checks regression
guards; exit 1 means a guard failed. Each packet sees the previous 11 packets
and is checked at its own sample time.

- `mendeley_aquaponic_pond_iot` (CC BY 4.0): PH-4502C pH, DFRobot TDS (EC =
  TDS × 2 / 1000) and DS18B20 in a ~0.7 m³ NFT/fish pond, ESP8266. The last raw
  reading of each 5-minute bucket is used, matching the cress logger's single
  unaveraged read. 11,108 packets.
- `4tu_agc2_cherry_tomato` (CC0): six Wageningen compartments, 5-minute air
  temperature, humidity, drain pH/EC and slab temperature/moisture. 47,809
  packets each.

| Field, label | Before (HEAD b22a13e) | After |
|---|---:|---:|
| Aquaponic pH `baseline_drift_possible` | 38.98 % | 8.71 % |
| Aquaponic pH `noisy_signal_possible` | — | 69.54 % |
| Aquaponic pH `impossible_ph` | 5.61 % | 5.61 % |
| Aquaponic water temperature `stuck_value` | 6.44 % | 0.00 % |
| AGC2 slab temperature `stuck_value` (6 compartments) | 3.88–5.54 % | 0.00 % |
| AGC2 drain pH/EC `noisy_signal_possible` (max) | — | 1.03 % (Automatoes EC) |

Guards: aquaponic water-temperature stuck ≤ 0.5 %, aquaponic pH drift ≤ 10 %,
aquaponic pH noise ≥ 50 %, AGC2 pH/EC noise ≤ 2 %, AGC2 slab-temperature
stuck ≤ 0.5 %. All pass.

Follow-up the same day: the drift baseline became the median of the first 3
plausible readings (was the first plausible reading). Aquaponic pH drift
8.71 % → 7.57 %, aquaponic EC drift 4.96 % → 0.82 %, AGC2 pH/EC drift down or
equal in every compartment; synthetic fault replay unchanged. The remaining
aquaponic pH drift windows show the probe wandering between pH 8 and 11 in a
fish pond, so they are treated as genuine "verify this probe" alarms.

Firmware estimate (one-off, same log): cress-logger 0.1.1 logs the median of
15 pH reads per interval. Emulated as the median of the last 15 raw readings
per 5-minute bucket, pH noise flags fall from 69.5 % to 43.3 % and drift
rises from 7.6 % to 10.8 % (quieter windows can now be judged for drift).

Known remaining behaviour, not changed:
- AGC2 air temperature (1.5–3.1 %) and slab moisture (1.7–4.1 %) `stuck_value`
  at 0.1 resolution in a controlled greenhouse are likely legitimate plateaus.
- Automatoes drain EC genuinely jumps 4.4–6.3 mS/cm between samples, so its
  noise label describes the signal.
- Timezones are assumed (+07:00 aquaponic, +01:00 AGC2); values are unaffected.
