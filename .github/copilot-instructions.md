# Copilot / Codex instructions

Read [AGENTS.md](../AGENTS.md) at the repository root before making changes.

**Pomona** — edge AI platform for agriculture. Early MVP.

- Current focus: Phase 2 (dashboard + persistence)
- Stack: Python, FastAPI, Docker Compose, MQTT
- Do not commit secrets, `.env`, or model weights
- LLM is advisory only — never direct actuator control
- Prefer minimal diffs; run `make test`

Public docs: `docs/`. Owner-only notes: `private/` (gitignored).
