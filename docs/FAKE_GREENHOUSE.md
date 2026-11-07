# Try Pomona without hardware: the fake greenhouse

A five minute walkthrough. The fake greenhouse (`examples/simulators/fake_greenhouse.py`) publishes
realistic readings for two zones, lets you break sensors and cause real problems with buttons, and
keeps a hidden answer key. A scorer then lays Pomona's cards next to that key. Full reference:
[examples/simulators/README.md](https://github.com/okyanu/pomona/blob/main/examples/simulators/README.md).

Two kinds of trouble are kept strictly apart:

- **Sensor faults**: the reading is wrong, the plant is fine (stuck, drift, jump, spike, noisy,
  dropout, dead clock, plausible offset). A good system says "cannot confirm this sensor".
- **Real events**: the plant really is in trouble and the readings are correct (heat spike, cold night,
  humid night, nutrient over-concentration, dry zone). A good system raises the matching card.

## With Docker

```bash
make up                  # full stack: Core, model-router, automation-engine, dashboard, MQTT
make fake-greenhouse     # second terminal: demo scenario to MQTT, control page at http://127.0.0.1:8090/
```

1. Open the control page (<http://127.0.0.1:8090/>) and the dashboard (see
   [GETTING_STARTED.md](./GETTING_STARTED.md) for its address).
2. Press buttons on the control page, or **Hidden random** to start something without seeing what
   it is. The page shows only what Pomona receives; the answer key stays hidden until the run is over.
3. Alerts need time: a card is raised only after its label has lasted 10 minutes (30 for humidity).
   Give each experiment 15 to 30 minutes.
4. When done, stop the simulator (Ctrl+C) and grade the run against a running automation-engine:

```bash
python3 scripts/score_fake_greenhouse.py --truth data/fake_greenhouse/truth.jsonl \
  --automation-url http://127.0.0.1:8085 --core-url http://127.0.0.1:8080 \
  --report data/fake_greenhouse/report.md --json data/fake_greenhouse/score.json
```

## Without Docker

```bash
make fake-greenhouse-score                          # about 30 minutes: quick scenario at 30 s per tick
SCENARIO=examples/simulators/scenarios/demo.json make fake-greenhouse-score   # about 3.5 hours
CONTROL_PORT=8090 make fake-greenhouse-score        # also serve the control page while it runs
```

This starts Core (with its outcome feed), the model-router and the automation-engine from the
service venvs, posts readings to Core over REST (no MQTT broker needed), then scores the run twice:
against the running stack and offline (an in-process replay of the same readings through the real
pipeline and alert monitor). Outputs land in `data/fake_greenhouse/` (gitignored): `truth.jsonl`
(the answer key), `report_stack.md`, `report_offline.md` and the matching `score_*.json`.

## Blind spots: a real fault and a silent probe

The worst failure for an advisory system is a calm screen while something is really wrong, because the one probe
that would show it has dropped out. `scenarios/blind_spot.json` runs real events (dry zone, heat spike, nutrient
over-concentration, humid night) and, 3 minutes after each starts, silences the probe that decides it
(`probe_dropout`: the field is missing from every packet). There is also a control where an optional probe
goes silent but another probe still shows the fault.

```bash
python3 examples/simulators/fake_greenhouse.py --dry-run --out /tmp/e.jsonl --truth-log /tmp/t.jsonl \
  --scenario examples/simulators/scenarios/blind_spot.json
services/model-router/.venv/bin/python scripts/score_fake_greenhouse.py --truth /tmp/t.jsonl --offline \
  --report /tmp/r.md --fail-on-miss
```

The scorer adds a **Blind spots** table (only when the truth log has a `probe_dropout`). A case is a silent probe
while a real event runs and the true state has crossed a label that probe decides. Its verdict, from what Pomona
actually emits:

| Verdict | Meaning |
|---------|---------|
| FALSE REASSURANCE | While the probe was silent and the fault ran: no card for the event, no sensor card, (offline) no reading of that field flagged (vetoed or a missing-data label) and no silent-device flag. The zone looked fine. Counted apart from caught and missed; `--fail-on-miss` fails on it |
| can't confirm (pass) | At least one of: a sensor card (`sensor_check`, `sensor_flatline`) raised or open; (offline) a reading flagged for that field; the device marked silent, meaning no Core-accepted reading for longer than Core's `device_timeout_seconds` (120 s), which the dashboard shows under Device health. The row says which (`Via`), and "passive flag only" when the device flag was the only sign |
| alerted (pass) | The event's own card was open or raised while the probe was silent, from other evidence |
| too short to judge / no fault in window / no real event | Not judged |

Real episodes that a silent probe kept from ever raising are listed here and not counted as missed. Core stores a
packet that is missing a probe (the field is absent or `null`; only a packet with no reading at all is refused),
the router flags the missing reading from the first packet, and the `sensor_check` alert is raised after 3 of
them in a row (about 60 s at 30 s ticks). So in `blind_spot.json` each probe-dropout case ends in "can't confirm"
through the `sensor_check` card, or "alerted" by the event's own rule where another probe still carries the event;
the passive device-silent flag stays a reported category for a node whose packets stop arriving altogether.

## Reading the report

`report_*.md` has one row per episode: where, when, what really happened, the expected answer, and
what Pomona raised, with a verdict.

| Verdict | Meaning |
|---------|---------|
| caught | A real event raised its card (delay shown), or a sensor fault raised a sensor check while it was still going on |
| caught as can't-confirm (safe) | A real event whose domain card never came, but the sensor check raised while that probe was flagged: Pomona said "check the probe" instead of acting on a doubtful reading |
| MISSED | A real event that lasted longer than the rule's window raised nothing |
| MISSED (noticed only when it ended) | A sensor fault whose check-the-sensor card was raised only after the fault stopped, when the reading snapped back to the true value (a slow drift of pH, EC or air temperature). The card's label began on the first honest reading, so the lie itself was not seen. Counted as a miss in the sensor-fault totals (the summary says how many of the misses were of this kind); a card whose label began during the fault but was raised a reading or two after it ended still counts as caught |
| too short to raise | The episode was shorter than the rule's `raise_after`; no card was possible |
| no card rule | The label has no rule in `rules.yaml`, so Pomona has no card for it (every label the simulator can produce has one today) |
| WRONG CARD | A sensor fault on one field produced a domain card built on it |
| undetectable | `plausible_offset`: an in-range constant offset nobody can see from one reading |
| rejected by Core | A dead-clock reading refused at ingest, as intended |
| FALSE ALARM | A card raised in normal operation, outside every episode's clear window |
| silent probe | A real episode that a silent probe (`probe_dropout`) kept from raising; graded in the Blind spots table, not as missed |

The stack and offline reports should agree on which rules raised. The offline report adds
reading-level counts (normal frames with a card or a sensor check, trusted-wrong-card frames).

## Honest limits

- **Time-lapse is not meaningful.** Pomona's drift checks count samples and its alert windows use
  sample time; a sped-up run (`--sim-speed` above 1) makes both unrealistic. Run in real time.
- **Demos take time.** A card needs its label to persist for 10 minutes (30 for humidity) and a
  fault needs 11 samples to leave Pomona's history, so a meaningful run is 30 minutes or more.
- What the scorer shows on the current rules: `heat_stress` raises the `heat_stress_check` card (check vents, fans and
  shading) after 10 minutes, and `cold_stress` (`cold_night`, air or substrate at or below 16 C) raises `cold_stress_check` (check heating and insulation) after 10 minutes; a slow drift of pH (0.02 per minute) is flagged after about 18 minutes
  (0.01 per minute after about 36, but 0.005 per minute over two hours stays unseen); a slow EC drift (0.05 mS/cm per
  minute) is flagged after about 10 minutes when it lasts 40 minutes, but a gentle or short one may be noticed only when it ends; a slow drift of
  air temperature, humidity, substrate moisture or substrate temperature is not seen while it lasts, only when it
  ends and the reading snaps back (scored as missed, "noticed only when it ended"); a fast EC drift (0.3 mS/cm per
  minute) is flagged within about 2 minutes; a stuck pH or EC probe is caught after about 6 minutes of freeze
  (shorter than 8 to 10 minutes it may not be); a +4 C air-temperature jump, a +15 %RH humidity jump, a +15 %
  substrate-moisture jump and a +4 C substrate-temperature jump are each flagged within a minute (and then accepted as the
  new level after 4, 4, 8 and 13 minutes); a noisy humidity, air, pH, substrate-moisture or substrate-temperature
  probe is caught within about 4 to 6 minutes, and so is a noisy EC probe at this 30-second rate, in about 6 to 8 minutes (not on a
  stream slower than 90 seconds); a single-sample spike is flagged but too
  short to raise a card; `plausible_offset` started mid-stream is flagged for as long as it lasts (from the start of
  a stream nobody can see it).
- Pomona now keeps a trusted reference per probe, so a real step (a nutrient overdose) shows first as
  "can't confirm, check the probe" (a safe catch, scored as such) and the domain card follows only after
  a calibration confirms the level (`make fake-greenhouse` has a Calibrate button, and `calibrate` steps in
  scenarios). Until then the probe stays flagged: that is by design, and a risk if nobody confirms.
- The `sensor_check` card is raised after 3 flagged readings in a row, so a chance run of identical
  readings (the stuck check) can raise a card. Soil moisture (0.1 % steps, noise of several steps) did
  this once in 23 normal runs of 6 simulated hours at 30 s (seed 4; seed 66 in the next 57): five equal
  readings in a row. A moisture freeze must now also span 2 minutes, so at 30 s the card needs seven equal
  readings, and seeds 1 to 80 give no false card. A frozen moisture probe gets its card 1 minute later at
  30 s sampling (after 3.5 minutes of repeats instead of 2.5); nothing changes at 1-minute or slower
  sampling. The softer flatline hint has its own rule and waits 10 minutes.
- Closing those gaps was bounded by real logs, not by the game: a stuck pH/EC probe is judged only if the
  stream normally changes in at least 70 % of its readings (real drain probes sit still for hours and are
  never judged), a freeze shorter than about 8 to 10 minutes, or a second freeze of the same probe soon after
  the first that lasts less than about 21 minutes, is not caught; a jump of humidity (below 12 %RH), moisture (below
  8 %) or substrate temperature (below 1.5 C) is not caught because real probes make such changes; a slow
  drift of air temperature, humidity, moisture or substrate temperature, a noisy EC probe on a stream slower than 90
  seconds and a frozen substrate-temperature probe (thermal mass) are still missed; a step is flagged only as long as it is
  physically impossible and then accepted as the new level; and the noise limits at 30 seconds for air temperature,
  humidity and pH are scaled from real 5-minute logs rather than measured: they were checked on one real fast log
  (3 months of 10-second data from one closed growth chamber, no false flags), and a greenhouse with vents and doors
  may behave differently. The fixed EC noise limit (0.20 mS/cm, streams at 90 seconds or faster) rests on tank EC
  only; there is no public fast drain EC. Details and real-data rates:
  [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md#stream-habit-checks-in-cores-feed-2026-11-02-widened-2026-11-05).
- A flagged level that nobody confirms stays "can't confirm" until a calibration (a probe broken for six
  hours stays flagged for the six hours, and its card stays open). That is by design; a lapse is an
  opt-in Core setting (`TRUST_BASELINE_MAX_AGE_S`). On real historical logs, which have no operator to
  calibrate, this keeps drain probes flagged for long stretches; see
  [SENSOR_TEMPORAL_CHECKS.md](./SENSOR_TEMPORAL_CHECKS.md#longer-memory-in-cores-feed).
- The fake model is simple physics, not a validated crop model; the dry zone dries in minutes.
- The control page has no authentication. Keep it on `127.0.0.1`.
