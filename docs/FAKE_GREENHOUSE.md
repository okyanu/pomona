# Try Pomona without hardware: the fake greenhouse

A five minute walkthrough. The fake greenhouse (`examples/simulators/fake_greenhouse.py`) publishes
realistic readings for two zones, lets you break sensors and cause real problems with buttons, and
keeps a hidden answer key. A scorer then lays Pomona's cards next to that key. Full reference:
[examples/simulators/README.md](../examples/simulators/README.md).

Two kinds of trouble are kept strictly apart:

- **Sensor faults**: the reading is wrong, the plant is fine (stuck, drift, jump, spike, noisy,
  dropout, dead clock, plausible offset). A good system says "cannot confirm this sensor".
- **Real events**: the plant really is in trouble and the readings are correct (heat spike, humid
  night, nutrient over-concentration, dry zone). A good system raises the matching card.

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

## Reading the report

`report_*.md` has one row per episode: where, when, what really happened, the expected answer, and
what Pomona raised, with a verdict.

| Verdict | Meaning |
|---------|---------|
| caught | A real event raised its card (delay shown), or a sensor fault raised a sensor check |
| MISSED | A real event that lasted longer than the rule's window raised nothing |
| too short to raise | The episode was shorter than the rule's `raise_after`; no card was possible |
| no card rule | The label (for example `heat_stress`) has no rule in `rules.yaml`, so Pomona has no card for it |
| WRONG CARD | A sensor fault on one field produced a domain card built on it |
| undetectable | `plausible_offset`: an in-range constant offset nobody can see from one reading |
| rejected by Core | A dead-clock reading refused at ingest, as intended |
| FALSE ALARM | A card raised in normal operation, outside every episode's clear window |

The stack and offline reports should agree on which rules raised. The offline report adds
reading-level counts (normal frames with a card or a sensor check, trusted-wrong-card frames).

## Honest limits

- **Time-lapse is not meaningful.** Pomona's drift checks count samples and its alert windows use
  sample time; a sped-up run (`--sim-speed` above 1) makes both unrealistic. Run in real time.
- **Demos take time.** A card needs its label to persist for 10 minutes (30 for humidity) and a
  fault needs 11 samples to leave Pomona's history, so a meaningful run is 30 minutes or more.
- Findings the scorer surfaces on the current rules: `heat_stress` has no card rule; slow drift and
  a noisy probe stay under the drift and flatline thresholds; a step fault that lasts more than 11
  samples is absorbed into the rolling baseline and then shows as a trusted wrong card;
  `plausible_offset` is undetectable by design. The sensor check flags faulty readings, but its
  labels come and go between readings and rarely last the 600 s `raise_after`, so most sensor faults
  end with no sensor-check card (reported as MISSED). A real EC rise faster than about 0.4 mS/cm
  within 11 samples is vetoed as drift, which is why `quick.json` uses a dry zone, not a nutrient event.
- The fake model is simple physics, not a validated crop model; the dry zone dries in minutes.
- The control page has no authentication. Keep it on `127.0.0.1`.
