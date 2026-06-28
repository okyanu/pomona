# Cursor / AI development rules

**Primary guide:** [AGENTS.md](../AGENTS.md) at repo root (Cursor, Claude, Codex).

This file adds Cursor-specific notes. Keep it short — details live in AGENTS.md.

## Before you start

1. [docs/PROJECT_STATUS.md](./PROJECT_STATUS.md)
2. [docs/ROADMAP.md](./ROADMAP.md)
3. Owner daily plan (if present): `private/DAILY_PLAN_30_DAYS.md` or `private/planning/` — local only

## Completed phases

| Phase | Status |
|-------|--------|
| 0 — Repo setup | ✅ |
| 1 — MVP skeleton | ✅ |
| 1b — Split + HF registry | ✅ |
| 2 — Dashboard + DB | ⏳ **current** |

## Local commands

```bash
make up | sim | health | events | advisor | test | down
make publish-check | publish-github
```

## After milestones

- Update `docs/PROJECT_STATUS.md` (public)
- Optionally update `private/DAILY_LOG.md` (local)

See [AGENTS.md](../AGENTS.md) for architecture, safety, and coding rules.
