# Copilot / Codex instructions

Read [AGENTS.md](../AGENTS.md) at the repository root before making changes.
Use [docs/EXECUTION_PLAN.md](../docs/EXECUTION_PLAN.md) for the current timetable, Codex/Cursor workflow, and future planning rules.

**Pomona** — edge AI platform for agriculture. Early MVP.

- Current focus: Phase 2 (dashboard + persistence)
- Stack: Python, FastAPI, Docker Compose, MQTT
- Do not commit secrets, `.env`, or model weights
- LLM is advisory only — never direct actuator control
- Prefer minimal diffs; run `make test`

Public docs: `docs/`. Owner-only notes: `private/` (gitignored).
