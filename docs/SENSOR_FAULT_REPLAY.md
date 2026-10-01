# Sensor fault replay

Run `make fault-replay` from the repository root after local dependency setup.
It prints JSON and returns **exit 1 when any injected fault is missed or a
normal frame raises a review flag**. This is a diagnostic acceptance benchmark,
not a promise that today's baseline passes. Unit tests separately verify that
known gaps are reported honestly.

The offline harness calls the actual deterministic sensor-quality function,
with an explicit advancing clock and accumulating history. Eight synthetic
sequences contain 12 frames each: normal, spike, missing pH, conflicting
probes, dropout, slow drift, stuck temperature, and sustained impossible pH.
Normal frames follow each fault to test recovery. No network, models,
databases, or actuators are used.

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
