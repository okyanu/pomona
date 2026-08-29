# Security

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Email or DM the repository maintainer privately with:

- Description of the issue
- Steps to reproduce
- Impact assessment if known

We will respond as soon as possible.

## Safe defaults

- Never commit `.env`, `HF_TOKEN`, or API keys
- Run `make publish-check` before pushing
- Model outputs are **advisory only** — not for direct actuator or chemical control

## Sensor ingestion authentication

`pomona-core`'s sensor ingestion endpoint (`POST /v1/sensors/events`) has no
authentication by default, matching the local-first quickstart. Set `API_KEY`
in `.env` before exposing `core` beyond localhost — requests must then send
`Authorization: Bearer <API_KEY>`. `GET` endpoints and `/health` stay
unauthenticated. This is the first piece of Phase 2 production hardening;
see [docs/ROADMAP.md](docs/ROADMAP.md) for the rest of what's not yet done
(no authentication elsewhere in the platform, no signed device identity, no
production observability).

## Dependencies

Report dependency vulnerabilities via GitHub Dependabot (when enabled) or a private report to maintainers.
