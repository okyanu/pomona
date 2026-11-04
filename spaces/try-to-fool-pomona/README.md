---
title: Try to fool Pomona
emoji: 🌱
colorFrom: green
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: Break a greenhouse sensor. Does Pomona catch it?
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
- **Hurt the plants** (real events, the readings are honest): heat spike, cold night, humid night, nutrient overdose, dry zone.
- **Check the probe with a meter**: tells Pomona a reference meter confirmed a probe, so it may accept the probe's
  current level.
- **Pomona's blind test**: a random trick starts and stays hidden until you reveal it.
- **Share it**: "Copy replay link" puts the seed and your steps in the URL (nothing is sent to any server).
  "Download this scenario" gives a file you can run on your own stack with `make fake-greenhouse SCENARIO=...`.

## What is real and what is not

- The page runs **Pomona's real deterministic chain** in `rules_only` mode, not a copy, as **Python in your browser**
  ([Pyodide](https://pyodide.org), WebAssembly): Core's trusted-baseline and
  dead-clock checks, the model-router pipeline (sensor-quality check, sensor veto, tomato, water and nutrient rules)
  and the automation-engine's alert monitor with the real `rules.yaml` card rules. The footer shows the commit.
- The **small AI models are advisory and are not used** here. Nothing on this page loads model weights or calls a
  network service. **Nothing you do is sent to any server**: there is no server behind this Space, only static files.
  The first visit downloads about 9 MB (Pyodide and Pomona's code, served by the Space itself) and the browser keeps
  them for later visits.
- The **physics is fake**: a simple simulator (`examples/simulators/fake_greenhouse.py`), not a crop model. The dry
  zone dries in minutes, a heat spike is a vent failure on a sunny day, a cold night is a heating failure, and so on.
- Time is simulated on a virtual clock (a reading every 30 seconds, physics at the real rate, so it is **not** a
  time-lapse): two simulated hours take a few seconds in the browser. A session is capped at 24 simulated hours.
- Pomona only advises. It never controls irrigation, dosing or any other hardware.
- Known gaps stay visible on purpose: a plausible offset is undetectable by design, and some sensor lies are still
  not caught: a pH or EC freeze shorter than about 8 to 10 minutes (or a second one soon after the first that lasts
  less than about 21 minutes), a jump smaller than a real probe can make (humidity below 12 %RH, substrate moisture
  below 8 %, substrate temperature below 1.5 C), a slow drift of air temperature, humidity, substrate moisture or
  substrate temperature (Pomona notices it only when the drift ends and the reading snaps back, which is scored as
  "MISSED (noticed only when it ended)", not as caught), a very slow pH drift (0.005 per minute), a gentle or short EC drift, a noisy EC probe
  and a frozen substrate-temperature probe. Each of these is limited by what real greenhouse logs allow, see
  [docs/FAKE_GREENHOUSE.md](https://github.com/okyanu/pomona/blob/main/docs/FAKE_GREENHOUSE.md#honest-limits).

## How it works

A static Space: `index.html`, `app.js` and `style.css` are the page, `worker.js` is a Web Worker that starts Pyodide
(Python 3.14 compiled to WebAssembly, in `pyodide/`) and unpacks `pomona.zip` into it. `pomona.zip` holds `game.py`
(the game), `engine_api.py` (request checks and the play / info / rebuild calls) and `vendor/` (Pomona's engine
files). A session is a seed plus the list of commands you gave; the page holds it and sends it to the worker with each
action. The worker keeps one live session in memory and rebuilds it from the scenario when it is not the one it holds
(a reload, a replay link), in slices with a progress count. Nothing is stored anywhere except your own browser's
`localStorage` (your last run), no accounts, no logging. Limits: 24 simulated hours per session, 2 simulated hours
per click.

Python's `asyncio` has no blocking loop in the browser, so the engine runs on `engine_api.SyncLoop`, which drives the
pipeline's coroutines directly; in `rules_only` mode they never wait on I/O, and `SyncLoop` fails loudly if one ever
does. `make fool-space-pyodide-check` proves the browser build gives byte-identical results to CPython. A strict
Content-Security-Policy (`<meta>` in `index.html`) allows only this Space's own scripts, workers and WebAssembly.

The engine files are copied byte for byte from the repository into `vendor/` by `scripts/build_fool_space.sh`.
`vendor/`, `pyodide/` (the pinned Pyodide 314.0.7 files the page loads), `wheels/` (two pure-Python PyPI wheels) and
`pomona.zip` are generated and not committed on GitHub; they are part of the Space repository. The build script checks
a pinned SHA-256 for every Pyodide and PyPI file, `vendor/BUILD_INFO.json` records the commit and a SHA-256 for every
vendored file, and `make fool-space-check` fails when anything no longer matches.

## Run it locally

From a checkout of [github.com/okyanu/pomona](https://github.com/okyanu/pomona):

```bash
scripts/build_fool_space.sh                       # fills vendor/, pyodide/, wheels/ and pomona.zip (downloads ~16 MB once)
python3 -m http.server 8767 --directory spaces/try-to-fool-pomona
# open http://127.0.0.1:8767/
```

Tests (rebuild and verify the Space folder, then run the Space tests in CPython; no network once the files are there):

```bash
make fool-space-check            # hashes, pomona.zip, 70+ pytest tests of the game and engine_api
make fool-space-pyodide-check    # needs node: the same engine in Pyodide must equal CPython byte for byte
```

## Links

- Platform: [github.com/okyanu/pomona](https://github.com/okyanu/pomona)
- Collection: [Pomona -- Local AI for Safer Greenhouse Decision Support](https://huggingface.co/collections/Okyanus/pomona-local-ai-for-safer-greenhouse-decision-support-6a89931ffcc2f7a3f777f3b9)
- Model: [pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- Dataset: [greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)
- Other Spaces: [Greenhouse demo](https://huggingface.co/spaces/Okyanus/pomona-greenhouse-demo),
  [Sensor Data Checker](https://huggingface.co/spaces/Okyanus/pomona-sensor-data-checker),
  [pH Calibration Checker](https://huggingface.co/spaces/Okyanus/pomona-ph-calibration-checker)
