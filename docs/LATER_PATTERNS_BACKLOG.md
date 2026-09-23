# Later SQI / twin / advice patterns (local backlog)

**Status:** local implementation slices landed 2026-09-23 (working tree only).
No commit, push, training, upload, or deploy is authorized by this file.

Research rationale:
`private/research/HURST_FRONTZEK_PLEXUS_COTTONBOT_2026_09_23.md`

None of these replace Days 1–2 trust work (dual time, zone leakage, input
contract, eval hygiene).

## Design drafts + local status

| Order | Doc | Pattern | Local status |
|------:|-----|---------|--------------|
| 1 | [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md) | Plexus-style stuck / flatline / baseline drift | Implemented in deterministic SQI + fault-replay |
| 2 | [CALIBRATION_PROVENANCE.md](./CALIBRATION_PROVENANCE.md) | Hurst-style budget + tagged corrections | Core APIs for calibrations / corrected / recalibrate-next |
| 3 | [ADVICE_CARDS.md](./ADVICE_CARDS.md) | CottonBot-style HITL cards | Automation + dashboard advice-card endpoints |
| 4 | [DIGITAL_TWIN.md](./DIGITAL_TWIN.md) | Frontzek-style calibrate → estimate (advisory) | parameter_version + quality fail-closed; still linear |

## Do not do yet

- Commit or publish without an explicit owner request.
- Adopt ThingsBoard, Plexus-as-hub, Flutter-first, or MPC/RPC actuator loops.
- Silently overwrite raw sensor history with “corrected” values.
