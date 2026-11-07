# Security

## Reporting a vulnerability

**Please do not open a public GitHub issue for security problems.**

Email or DM the repository maintainer privately with:

- Description of the issue
- Steps to reproduce
- Impact assessment if known

We will respond as soon as possible.

## Safe defaults

- Never commit `.env`, `HF_TOKEN`, `MQTT_PASSWORD`, or API keys
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

## MQTT broker login

The MQTT broker (Mosquitto) does not accept anonymous clients. `./scripts/setup.sh` / `./scripts/up.sh` put a
random `MQTT_PASSWORD` into your gitignored `.env`; Docker Compose refuses to start the broker without one.
The broker builds its password file inside the container at start, so no password file is kept on the host.
Every client (Core, the simulators, device firmware) must use the same `MQTT_USERNAME` / `MQTT_PASSWORD`.

- Port 1883 is plain MQTT without TLS: the login and the readings cross the network unencrypted. It is for the
  local network only. Do not port-forward it or publish it to the internet.
- If you can, keep sensors on their own network or VLAN, apart from phones and laptops.
- Wi-Fi passwords stay on the sensor node and are never sent to Core.
- One shared login is not per-device identity (see the roadmap): anyone who has it can publish as any device.

## Dependencies

Report dependency vulnerabilities via GitHub Dependabot (when enabled) or a private report to maintainers.
