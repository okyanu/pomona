# Digital twin (design draft)

**Status:** local advisory upgrades implemented — `parameter_version`,
trajectory `quality: forecast`, and fail-closed when upstream sensor quality
requires review. Still linear forecast-only (no FMU). No commit/deploy
authorization implied by this file.

Pattern peer: Frontzek et al., Frontiers Plant Science 2026 — CEA digital twin
(MQTT → ThingsBoard → Modelica/FMU → calibrated simulation → multirate soft
sensor). Pomona steals **calibrate → estimate/forecast**; drops ThingsBoard as
system of record and drops RPC/MPC actuator paths.

## Current local service

`services/digital-twin` exposes:

```text
POST /v1/digital-twin/scenarios/simulate
```

Bounded linear trajectories from allowlisted scenario deltas. Never sends MQTT,
never commands actuators. See service README.

## Target architecture (advisory twin)

```text
Trusted sensors (core SQLite)
  → optional model calibration snapshot
  → estimate / forecast service
  → dashboard preview + suggestions (HITL)
```

Hard rule (unchanged): twin outputs are advisory. No RPC handlers to valves,
pumps, or HVAC. Safety-checker treats `digital_twin` like other non-executing
actors.

## Steal from Frontzek

| Idea | Pomona form |
|------|-------------|
| Calibrate model against data | Versioned parameter snapshot + metrics |
| Soft sensor / multirate estimate | Estimate unmeasured or slow states (e.g. biomass later) as **estimates**, labeled |
| YAML map model ↔ telemetry | Registry-style config under `models/` or twin config |
| MQTT ingest | Already via `pomona-core` — do not add ThingsBoard |

## Explicitly drop

- ThingsBoard / PostgreSQL as SoR (core + SQLite remains).
- Vendor RPC → actuators / MPC closed loop.
- Requiring OpenModelica/CasADi in Phase 2 — optional later backend only.

## Calibration of the twin (not probe calibration)

Distinct from [CALIBRATION_PROVENANCE.md](./CALIBRATION_PROVENANCE.md) (hardware
probes):

- Twin calibration = fitting model parameters to historical greenhouse series.
- Store `twin_model_id`, `parameter_version`, fit window, RMSE/NRMSE, dataset
  hash.
- Forecast responses must echo those ids for audit.

## Soft estimates

2026-09-25: removed the unvalidated `humidity * 0.55` root-moisture proxy.
Missing root-zone readings stay missing. VPD remains a derived estimate from
measured air temperature/RH, not a new independent measurement.

## Offline replay checkpoint

`scripts/benchmark_twin_replay.py` calls the actual simulator and compares MAE,
RMSE and bias to persistence at 15/30/60 minutes by default. Input is one
farm/zone, strictly ordered timezone-aware samples, explicit `quality: valid`,
and `state` values. Optional scenarios must be known at forecast origin.
Mixed zones, duplicate times and boolean/nonfinite readings are rejected.
Gaps and bad-quality pairs are not imputed. Earlier rows are reserved as a
calibration block; **no parameter fitting is implemented or claimed**.

```bash
services/core/.venv/bin/python scripts/benchmark_twin_replay.py \
  examples/scenarios/twin-replay-synthetic.jsonl /tmp/pomona-twin-report.json \
  --split-index 3
```

Output must be a new file. The supplied data is explicitly synthetic. With
zero scenario deltas this twin equals persistence; matching it proves no
forecast improvement. Real AGC2/site data, facility mapping and independent
calibration/evaluation windows are still required before field claims.

When estimating quantities not sampled every second:

- Mark `quality: "estimated"` (or equivalent).
- Include uncertainty / method.
- Never present estimates as raw sensor events.

## Acceptance

1. Existing forecast API remains backward-compatible or versioned.
2. Integration tests prove no MQTT publish and no automation execute path.
3. Scenario rejects unknown fields and out-of-range deltas (already true).
4. Any soft-sensor path fails closed when base sensor quality is WARN/FAULT.

## Implementation order

1. Keep linear twin; document assumptions in API responses (done partially).
2. Parameter snapshot + reproducibility fields.
3. Optional calibrated grey-box / FMU backend behind the same advisory API.
4. Soft estimates only after temporal SQI + probe provenance are trustworthy.

## Related

- [architecture.md](./architecture.md)
- Research note (local): `private/research/HURST_FRONTZEK_PLEXUS_COTTONBOT_2026_09_23.md`
- [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md)
