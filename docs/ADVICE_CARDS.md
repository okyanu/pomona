# Advice cards (design draft)

**Status:** local MVP implemented — automation
`GET /v1/automation/advice-cards` and dashboard `GET /api/advice-cards`.
No commit/deploy authorization implied by this file.

Pattern peer: CottonBot (local Ollama + RAG + soil/weather tools → field advice
via FastAPI; Flutter optional). Pomona already has guarded water/irrigation and
tomato reasoners; this doc defines a **card-shaped HITL presentation**, not a
new crop domain.

## Goal

2026-09-25 evidence checkpoint: dashboard evaluation now records the sensor
and history snapshots, history hash, rule outputs/IDs, readings, timestamps,
scope and blocked actions in suggestion context. Card API exposes these with
a context SHA-256 and units; dashboard renders escaped evidence details.
Legacy suggestions show `legacy_missing_snapshot` instead of invented evidence.
Hashes identify content; they are not signatures or proof of sensor accuracy.
Calibration references are preserved when present in the source snapshot, not
inferred or automatically resolved. Complete runtime/model pinning remains a
separate reproducibility requirement. Stored telemetry can be sensitive; keep
local suggestion databases private.

Turn reasoner + automation suggestions into stable **advice cards** for the
dashboard (and later optional mobile), answering:

```text
What should I check or do about water / climate / nutrients?
```

Cards advise. They never open valves, change schedules, or dose fertilizer.

## Outcome confirmation

Approving a card does **not** mean anyone did anything. After an approval Pomona
only watches whether the reading recovered, from later readings (sample time),
not from the click. A card then carries `outcome` (`null` for rejected, expired
or older suggestions):

```json
"outcome": {"status": "awaiting", "deadline": "2026-09-23T14:00:00+00:00",
            "required_clean_readings": 3, "clean_streak": 1, "readings_seen": 2,
            "untrusted_readings": 0, "watched_labels": ["high_ec"]}
```

- `awaiting` — watching until `deadline` (approval time + 2 h by default;
  a rule can set `response_window_seconds`).
- `confirmed` — N (default 3) consecutive trusted readings, all sampled after the
  approval, showed none of the rule's labels. It does not prove the suggested
  check was done or that it caused the recovery.
- `not_recovered` — the window ended with enough trusted readings, but the
  labels did not stay away for N in a row.
- `unconfirmed` — the window ended with too few trusted readings to tell.

Core feeds these readings itself: each new full packet is forwarded for a rules-only
evaluation and then to the alert monitor, so outcomes advance even when no dashboard is open.

Readings with a sensor data-quality label, readings sampled before the approval,
repeats, and readings from another farm, zone or device never count. There is
no actuator path: the outcome is advisory text on the card.

Sensor-check card: when a reading fails the sensor check, the trust gate keeps
the specialists from reasoning on it, so no dosing or irrigation card is made
from it. The `sensor_check` rule (`check_sensor`) makes this card instead:
"a reading could not be confirmed; check the flagged probe or timestamp before
acting on any advice that uses it; if a meter agrees with the reading, the condition is real:
record a calibration for that probe to accept the new level". The card is raised after the flag
is on 3 readings in a row (the sensor-check detectors flag a fault for only a few readings; waiting
the usual 10 minutes would let it cancel itself). Core also keeps a sticky trusted reference per
probe (see [SENSOR_QUALITY_REASONER.md](./SENSOR_QUALITY_REASONER.md)), so a step or a frozen
reading stays flagged for as long as it lasts instead of becoming the new normal; a real change
(a nutrient overdose) therefore shows as "can't confirm" until a calibration for that probe is
recorded. A probe that has merely barely moved (`flatline_possible`, a softer hint than a stuck value)
has its own card, `sensor_flatline` ("it may be stuck or clipped: check that it still responds"), which
waits the usual 10 minutes; both cards use the action `check_sensor`. Every card's `evidence` carries
`trust_verdict`, `vetoed_fields` (readings that were there but not used) and `missing_fields` (probes that
did not report in the latest reading), and the dashboard shows a "Sensor trust:" line that says
"EC not reported in the latest reading" for a missing probe and "EC not used" for a vetoed one. A reading
that is `null` is shown as an en dash in the card's "Readings" line. For a `sensor_check` card the outcome differs: a later reading with one of
its watched sensor labels is a trusted reading showing the problem persists
(`readings_seen` grows, `clean_streak` resets to 0), not an untrusted one; a
reading with some other sensor label still does not count.

Extreme-reading card: a reading can be far outside any growing range (pH at or below 3.5 or at or above 9.0,
EC above 10 or below 0.01) and still inside the sensor check's plausible range (pH 3 to 11, EC 0 to 12), so the probe
passes and the reasoners call it `sensor_anomaly`. The `extreme_reading_check` rule (`check_sensor`, the usual 10
minutes) turns that label into a card: "measure it by hand now: either the condition is real and serious, or the probe
is failing". It suggests a check only, never a dose. The `water_level_check` rule also matches the water reasoner's
own moisture labels (`low_moisture`, `high_moisture`, `irrigation_underwatering`, `irrigation_overwatering`), which
trip at 28 % and 78 %, before the tomato reasoner's `water_level_risk` at 10 % and 85 %. A test
(`services/model-router/tests/test_rule_label_coverage.py`) fails when a reasoner can emit a label that no rule
matches and that is not listed there as "no card on purpose".

A gap is not persistence: an alert (the card on the dashboard) is raised only after its label has lasted
(10 minutes, 3 readings for the sensor check). When two consecutive readings of a stream are more than
`ALERT_MAX_GAP_SECONDS` apart (default 1800, 0 turns it off), the waiting timers restart from the later reading, so a
label seen once and again hours later with nothing between does not raise at once. A device that reports less often than this value never accumulates a time-based raise, so a slow reporter must raise the setting or set it to 0. An alert that is already raised is not
touched by a gap (what to do about a probe that goes silent while an alert is open is a separate, later design: see
`docs/design/silent-probe.md`, "Out of scope"). A sample time up to `MAX_FUTURE_SAMPLE_S` (default 300, Core's own
limit) ahead of the clock counts as current in the router and the automation engine too; 0 means 60 s there.

## Placement

```text
sensor quality (incl. temporal checks)
  → water / tomato / nutrient reasoners (guarded)
  → safety-checker
  → automation-engine suggestion
  → advice card on dashboard
  → human approve / reject / defer
```

Same boundary as [WATER_IRRIGATION_RISK_REASONER.md](./WATER_IRRIGATION_RISK_REASONER.md)
and [architecture.md](./architecture.md).

## Card shape (sketch)

```json
{
  "card_id": "uuid",
  "created_at": "2026-09-23T12:00:00Z",
  "expires_at": "2026-09-23T18:00:00Z",
  "severity": "irrigation",
  "title": "Root zone moisture trending low",
  "summary": "Moisture below target band for zone greenhouse-a.",
  "severity": "warn",
  "evidence": {
    "sample_time": "2026-09-23T11:40:00Z",
    "zone_id": "greenhouse-a",
    "readings": {"soil_moisture_pct": 28.0},
    "reasoner_ids": ["water-irrigation-risk-reasoner-v0.1.8"],
    "sensor_quality_labels": []
  },
  "safe_next_checks": [
    "confirm probe is not stuck or flatlined",
    "check reservoir level",
    "review last irrigation event"
  ],
  "blocked_actions": [
    "autonomous_irrigation_change",
    "irrigation_schedule_change"
  ],
  "suggestion_id": "optional-link-to-automation-row",
  "human_review_required": true,
  "status": "pending"
}
```

Statuses: `pending` | `approved` | `rejected` | `expired` | `superseded`.

## Allowed tools (if agentic later)

Read-only only:

- latest / scoped sensor history from core,
- weather forecast fetch (optional, cached),
- RAG over owner-approved guides (tomato / greenhouse — not cotton PDFs by default).

Forbidden: any tool that publishes actuator MQTT, calls irrigation hardware, or
mutates schedules without a separate non-LLM gate and human approval.

## What to steal from CottonBot

- Local Ollama for privacy/cost.
- RAG + sensor tools for context, not for control.
- Mobile later only if Phase 2 dashboard cards work first (Flutter is optional).

## What not to copy

- Cotton production guide as default corpus.
- Direct irrigation triggers from the assistant.
- Replacing deterministic water reasoner labels with free-form chat as the
  system of record — cards wrap structured outputs.

## Acceptance

1. Card creation requires passing sensor-quality gate (or explicit
   `human_review_required` when quality is degraded).
2. Approving a card records a decision; it does not execute hardware.
3. Expired / superseded cards cannot be approved without refresh.
4. Rendering tests: dashboard shows title, severity, checks, and blocked actions.

## Implementation order

1. Map existing automation suggestions → card schema in dashboard.
2. Wire water reasoner evidence into card `evidence`.
3. Optional RAG / weather tools behind the same schema.
4. Optional mobile client reading the same API.

## Related

- [WATER_IRRIGATION_RISK_REASONER.md](./WATER_IRRIGATION_RISK_REASONER.md)
- [TOMATO_RISK_REASONER.md](./TOMATO_RISK_REASONER.md)
- Research note (local): `private/research/HURST_FRONTZEK_PLEXUS_COTTONBOT_2026_09_23.md`
