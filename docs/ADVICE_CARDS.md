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
