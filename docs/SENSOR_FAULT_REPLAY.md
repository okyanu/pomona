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
