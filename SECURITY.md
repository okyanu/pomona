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

## Dependencies

Report dependency vulnerabilities via GitHub Dependabot (when enabled) or a private report to maintainers.
