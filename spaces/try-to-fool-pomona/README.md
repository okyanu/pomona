---
title: Try to fool Pomona
emoji: 🌱
colorFrom: green
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: apache-2.0
short_description: Break a greenhouse sensor or hurt the plants; does Pomona catch it?
tags:
- agriculture
- sensors
- greenhouse
- hydroponics
- tomato
- fault-injection
models:
  - Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora
datasets:
  - Okyanus/greenhouse-sensor-data
---

# Try to fool Pomona

A pretend tomato greenhouse with two zones (A: substrate, B: hydroponic) and a button for every way things go
wrong. Break a sensor and Pomona should say it can't trust that sensor. Hurt the plants and it should raise the
right alert. Fast-forward time and see who wins. Every finished trick is graded against the simulator's answer
key: **you fooled Pomona**, **it caught it**, or **the trick was unfair** (nobody could tell from the readings).

- **Lie to Pomona** (sensor faults, the plants are fine): stuck, drift, jump, spike, noisy, dropout, dead clock,
  plausible offset.
- **Hurt the plants** (real events, the readings are honest): heat spike, humid night, nutrient overdose, dry zone.
- **Check the probe with a meter**: tells Pomona a reference meter confirmed a probe, so it may accept the probe's
  current level.
- **Pomona's blind test**: a random trick starts and stays hidden until you reveal it.
- **Share it**: "Copy replay link" puts the seed and your steps in the URL (nothing is stored on the server).
  "Download this scenario" gives a file you can run on your own stack with `make fake-greenhouse SCENARIO=...`.

## What is real and what is not

- The page runs **Pomona's real deterministic chain** in `rules_only` mode, not a copy: Core's trusted-baseline and
  dead-clock checks, the model-router pipeline (sensor-quality check, sensor veto, tomato, water and nutrient rules)
  and the automation-engine's alert monitor with the real `rules.yaml` card rules. The footer shows the commit.
- The **small AI models are advisory and are not used** here. Nothing on this page loads model weights or calls a
  network service.
- The **physics is fake**: a simple simulator (`examples/simulators/fake_greenhouse.py`), not a crop model. The dry
  zone dries in minutes, a heat spike is a vent failure on a sunny day, and so on.
- Time is simulated on a virtual clock (a reading every 30 seconds, physics at the real rate, so it is **not** a
  time-lapse): two simulated hours take about a quarter of a second to compute. A session is capped at 24
  simulated hours.
- Pomona only advises. It never controls irrigation, dosing or any other hardware.
- Known gaps stay visible on purpose: a plausible offset is undetectable by design, and some sensor lies (for
  example a stuck pH probe) are not caught yet. See
  [docs/FAKE_GREENHOUSE.md](https://github.com/okyanu/pomona/blob/main/docs/FAKE_GREENHOUSE.md#honest-limits).

## How it works

One FastAPI app (`server.py`) serves the page (`static/`) and a small JSON API. A session is a seed plus the list of
commands you gave; the browser holds it and sends it with each request. The server keeps live sessions in memory
(30 minutes idle, at most 500) and rebuilds any session from its scenario when it is not cached, so a sleeping or
restarted Space loses nothing and replay links use the same path. No accounts, no stored user data, no extra
logging. Limits: 24 simulated hours per session, 64 KB per request, a per-IP rate limit.

The engine files are copied byte for byte from the repository into `vendor/` by `scripts/build_fool_space.sh`
(`vendor/` is generated and not committed on GitHub; it is part of the Space repository). `vendor/BUILD_INFO.json`
records the commit and a SHA-256 for every file, and `make fool-space-check` fails when a vendored file no longer
matches the repository.

## Run it locally

From a checkout of [github.com/okyanu/pomona](https://github.com/okyanu/pomona):

```bash
scripts/build_fool_space.sh                       # fills spaces/try-to-fool-pomona/vendor/
cd spaces/try-to-fool-pomona
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m uvicorn server:app --host 127.0.0.1 --port 8767
# open http://127.0.0.1:8767/
```

Tests (rebuilds `vendor/`, verifies it against the repo, then runs the Space tests):

```bash
make fool-space-check
```

With Docker: `docker build -t try-to-fool-pomona spaces/try-to-fool-pomona` after the build script, then
`docker run -p 7860:7860 try-to-fool-pomona`.

## Links

- Platform: [github.com/okyanu/pomona](https://github.com/okyanu/pomona)
- Collection: [Pomona -- Local AI for Safer Greenhouse Decision Support](https://huggingface.co/collections/Okyanus/pomona-local-ai-for-safer-greenhouse-decision-support-6a89931ffcc2f7a3f777f3b9)
- Model: [pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- Dataset: [greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)
- Other Spaces: [Greenhouse demo](https://huggingface.co/spaces/Okyanus/pomona-greenhouse-demo),
  [Sensor Data Checker](https://huggingface.co/spaces/Okyanus/pomona-sensor-data-checker),
  [pH Calibration Checker](https://huggingface.co/spaces/Okyanus/pomona-ph-calibration-checker)
