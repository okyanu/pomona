# Calibration provenance (design draft)

**Status:** local MVP implemented in `pomona-core` (calibration events,
corrected observations, recalibrate-next ranking). No commit/deploy
authorization implied by this file.

Pattern peer: Hurst et al., [arXiv:2506.09186](https://arxiv.org/abs/2506.09186)
(“Not all those who drift are lost”) — uncertainty-aware drift correction and
calibration scheduling for sensor fleets. Pomona adapts the *budget / tag*
ideas for pH/EC (and later other probes), not the DO-specific GPR stack.

Prerequisite: temporal WARN/FAULT signals
([SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md)) and trustworthy
ingest time/identity.

## Goal

After probes are flagged WARN/FAULT:

1. Decide **which** probe to recalibrate next under a limited maintenance budget.
2. Record calibration events with full provenance.
3. Optionally attach **tagged** corrected readings — never silently overwrite raw
   “truth.”

## Non-negotiable rules

- Raw sensor events and modular observations stay immutable once stored.
- Corrected values are derived artifacts with `derived_from`, method, and
  uncertainty — separate rows or explicit fields, not in-place edits.
- LLMs and twins must not invent calibrations or write actuators.
- Sender-reported `calibration_timestamp` on devices remains advisory until a
  matching calibration event exists in core.

## Proposed calibration event (sketch)

HTTP/MQTT sibling to modular observations (exact path TBD at implementation):

```json
{
  "device_id": "esp32-greenhouse-01",
  "farm_id": "demo-farm",
  "zone_id": "greenhouse-a",
  "sensor_id": "ph-probe-01",
  "measurement": "ph",
  "event_type": "calibration",
  "method": "two_point_buffer",
  "points": [
    {"reference": 4.0, "raw": 1.12},
    {"reference": 7.0, "raw": 2.05}
  ],
  "coefficients": {"offset": 0.0, "slope": 1.0},
  "uncertainty": {"offset_sigma": 0.02, "slope_sigma": 0.01},
  "performed_at": "2026-09-23T10:00:00Z",
  "performed_by": "operator-label-optional",
  "notes": "fresh buffers"
}
```

Core stores these in SQLite with the same identity/time validation style as
observations ([HARDWARE_EVENT_CONTRACT.md](./HARDWARE_EVENT_CONTRACT.md)).

## Derived (corrected) reading (sketch)

```json
{
  "event_type": "corrected_observation",
  "sensor_id": "ph-probe-01",
  "measurement": "ph",
  "raw_value": 6.8,
  "corrected_value": 6.5,
  "uncertainty": 0.15,
  "calibration_event_id": "...",
  "method": "response_inverse_v0",
  "quality": "corrected",
  "human_review_required": false
}
```

Downstream reasoners that consume corrected values must record which
calibration version they used (snapshot id), for auditability.

## Calibration budget (Hurst-style, later)

Given a fixed weekly budget `B` of calibrations:

- Rank probes by prediction / drift uncertainty and WARN/FAULT severity.
- Suggest top-`B` targets as automation **suggestions** (HITL), not jobs.
- Do not auto-schedule hardware maintenance without an operator.

v0 can be a deterministic ranker (age since last calibration + SQI severity).
GPR / response-function modelling is optional and separate.

## Acceptance

1. Contract tests: raw rows unchanged after correction insert.
2. API rejects corrected payloads that lack `calibration_event_id`.
3. Dashboard can list “recalibrate next” suggestions without executing anything.
4. No silent mutation of `sensor_events` / `sensor_observations` history.

## Out of scope

- Full Hurst GPR pipeline.
- Optical / lab reference hardware integration.
- Replacing temporal detectors (those come first).

## Related

- Research note (local): `private/research/HURST_FRONTZEK_PLEXUS_COTTONBOT_2026_09_23.md`
- [SENSOR_QUALITY_REASONER.md](./SENSOR_QUALITY_REASONER.md)
- [HARDWARE_EVENT_CONTRACT.md](./HARDWARE_EVENT_CONTRACT.md)
