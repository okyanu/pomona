# Design: noisy-EC check for fast loggers, and the 30-second limits checked on real data

Status: approved 2026-11-07, built. Reviewed once by a context-free reviewer (verdict: ready with fixes; all
fixes applied below). The owner approved it for the scope "every stream at 90 s or faster" (open question 1); items 1 to
4 of "Proposed change" are built, item 5 is not (as designed).

## Goal

1. **Record real evidence for the 30-second limits.** Every real log we had sampled every 5 minutes, so the 30 s
   jump and noise limits were scaled guesses (`STEP_LIMITS`, plus `NOISE_STEP_LIMIT_5MIN` scaled by the square root
   of the interval with `NOISE_STEP_FLOOR` as the floor). This design records that they raise no false flags on
   3 months of real 10-second data. No limit value changes.
2. **Close one known miss: a noisy EC probe is not caught.** EC has no noise limit, because the 5-minute Automatoes
   drain EC really jumps (1.0 % of its 12-reading windows have a median step of 0.4 mS/cm or more; it moves
   4.4 → 6.3 mS/cm between samples). Real 10-second tank data shows a healthy EC probe sampled fast barely moves, so
   a fixed noise limit is possible when the stream's sample interval is short.

## How the user meets it

A stream whose 12-reading window has a **median sample interval of 90 s or less**, and whose EC probe goes noisy
(loose BNC connector, ground loop, dying probe), gets the same flag pH and the other fields already get:
`noisy_signal_possible` on `ec_ms_cm`, with EC as a suspect field. After 3 flagged readings in a row it gets the
`sensor_check` card. Slower streams see no change.

- **Time to a card at 30 s.** About 6 of the 11 steps in the window must be noisy before the median crosses the
  limit (about 3 minutes). Then 3 flagged readings in a row are needed (`rules.yaml` `raise_after_samples: 3`), so
  roughly 4–5 minutes in total.
- **In the "Try to fool Pomona" game,** the "Noisy sensor" trick on EC moves from missed to caught.

## Data

[Identifying Uncertainties In Air Temperature Data Of An Indoor Farming System](https://data.mendeley.com/datasets/rmvgvkg8vn)
(University of Florida, Mendeley Data, CC BY 4.0).

- **Setup:** lettuce in a small hydroponic growth chamber with four recirculating nutrient-solution loops (LNS 1–4),
  each with Atlas Scientific pH and EC probes. Air temperature and humidity are logged at four positions (SHT30
  class). A reference climate sensor logs every 5 s and is not used here.
- **Size:** 140 daily low-cost-sensor files, 926,903 rows, 2022-03-03 to 2022-09-27. Rows are 10 s apart for
  99.9 % of steps, with 86 gaps longer than a minute.
- **Units:** EC is in µS/cm, converted to mS/cm. EC is about 1.2 mS/cm throughout. The EC dosing columns are active
  (31k–41k non-zero rows per loop), so dosing events are in the data.
- **Labels and glitches:** there are no fault labels. Obvious glitches (pH 134, EC 9.4 → 0.0 → 9.4, air 64.6 °C) are
  single readings, which the range checks or the window median already absorb.
- **Where it lives:** downloaded to a local, uncommitted folder. Anyone can fetch it from the link above. The
  committed analysis script (see Proposed change, item 4) takes the folder as an argument.

### Air, humidity, pH at 30 s (every third row; 12-reading windows; one-way moves excluded as now)

| Field (4 positions or probes) | Real 30 s step, p99.99 | Jump limit | Largest real window median | Noise limit at 30 s | Windows flagged |
|---|---|---|---|---|---|
| Air temperature | 0.23–0.46 °C | 3 °C | 0.21–0.42 °C | 0.632 °C | 0 of 308,285 |
| Humidity | 4.3–5.2 %RH | 12 %RH | 1.9–2.4 %RH | 3.16 %RH | 0 of 308,285 |
| pH | 0.19 (5.3 on probe 4, glitches) | — | 0.05–0.10 | 0.158 | 0 of 308,285 |

- **Jumps over the limit:** only from single-reading glitches (air 64.6 and 45.8 °C; humidity 25 → 70 %RH and back).
- **Real humidity drops:** about 10 %RH within 30 s do happen (62 → 52.6 %RH), so the 12 %RH allowance is about
  right at 30 s.
- **Largest real air step** that is not a glitch: 1.09 °C.

### EC at every rate and phase (all offsets of each subsampling; 12-reading windows; about 0.92 M windows per probe)

| Rate | Phases | Largest window median per probe (mS/cm) | Flagged at 0.20 |
|---|---|---|---|
| 10 s | 1 | 0.128, 0.140, 0.091, 0.119 | 0 |
| 30 s | 3 | 0.067, 0.098, 0.059, 0.116 | 0 |
| 60 s | 6 | 0.056, 0.143, 0.064, 0.076 | 0 |
| 90 s | 9 | 0.065, 0.122, 0.060, 0.086 | 0 |

The worst real window is 0.143 mS/cm (60 s, probe 2), so a limit of 0.15 would leave only 1.05× headroom. The
proposal therefore uses **0.20** (1.4× headroom).

The simulator's "Noisy sensor" on EC (σ 0.03 × 10 = 0.3 mS/cm) gives a median step of about 0.29, which is 1.45×
the limit, so it is caught.

**Validated on tank EC only.** All four probes sit in recirculating tanks at about 1.2 mS/cm. There is no public
fast-sampled drain EC (tomato substrate, 2–6 mS/cm, where the probe may also see intermittent drain flow).

A false EC flag has a cost: the trust gate stops the specialists from reasoning on a flagged reading
(`rules.yaml`). See open question 1.

## Proposed change

1. **Separate fixed-limit table.** In `services/model-router/app/sensor_quality.py`, add
   `NOISE_FIXED_LIMIT = {"ec_ms_cm": (0.20, 90.0)}`, giving the limit in mS/cm and the largest median interval in
   seconds.
   - `NOISE_STEP_LIMIT_5MIN` and `NOISE_STEP_FLOOR` stay unchanged; `test_sensor_stream_habits.py` asserts their
     exact contents.
   - The gate that decides whether a field gets the noise check (around line 406) becomes "in either table".
   - In `apply_noise_check`, a fixed-limit field uses its limit as is, without the square-root scaling, and is
     judged only when the median sample interval of the window is at or below its largest interval.
   - Everything else is shared: the 12-reading window, the one-way rule (`NOISE_MAX_NET_SHARE`), the label, the
     suspect field and the check text.
   - The check still runs only through `apply_persistent_checks`, so it needs Core's `stream_baseline` entry for EC.
     `trusted_baseline.py` already lists `ec_ms_cm` in `BASELINE_FIELDS`.
2. **JavaScript parity.** Mirror item 1 in `spaces/sensor-data-checker/persistent.js` (the noise check lives there).
   Python and JS must give the same label, suspect field and check text. **Do not touch `rules.js`**: it holds only
   the 11-packet rule, and `make test-demo` requires the greenhouse demo's copy to be identical. Also update the
   "Noisy probe" tooltip in `spaces/sensor-data-checker/app.js`, which lists the fields that fire.
3. **Docs**, in plain language, with no `private/` paths:
   - **Comments** in `sensor_quality.py` above `NOISE_STEP_LIMIT_5MIN`, `STEP_LIMITS` and the EC paragraph (about
     lines 136–145), and the matching comment in `persistent.js`.
   - **`docs/SENSOR_TEMPORAL_CHECKS.md`:** the noise table row and the "Still MISSED" list.
   - **`docs/SENSOR_QUALITY_REASONER.md`:** the noise section.
   - **`docs/FAKE_GREENHOUSE.md`:** the honest limits, including the line saying the 30 s noise limits are scaled
     rather than measured.
   - **`spaces/try-to-fool-pomona/README.md`** and **`spaces/sensor-data-checker/README.md`** where they list
     checks or misses.
   - **This doc:** note where the build differs.
   - **Attribution:** add the dataset to `docs/LICENSE_AND_ATTRIBUTION.md` (CC BY 4.0, Attribution: Required, with
     the link and title).
4. **Committed analysis script.** Add `scripts/analyze_fast_sensor_log.py`. It takes the dataset folder as an
   argument, uses only the standard library, and prints both tables above. It runs in about 2 minutes on a laptop
   and is not part of any make target.
5. **Not doing:** adding the dataset to `make real-replay`. The replay is built for 5-minute data in `datasets/raw/`
   with per-source loaders, and would need a new loader and runtime budget for 926k rows × 4 loops. The one-off
   evidence lives in the docs and the script.

## Edge cases

- **Mixed or irregular intervals:** the gate uses the median interval of the 12-reading window, so one long gap does
  not switch it on or off.
- **Once-a-minute loggers:** these jitter between 59 and 61 s with second-resolution stamps. The 90 s gate keeps them
  in. Data at 90 s (all 9 phases) stays under 0.122.
- **Dosing:** an EC dose is a one-way step, excluded by the net-share rule. Dosing is active in the data, which
  still stays under 0.143.
- **Single glitches:** a reading that drops to 0.00 and comes back moves 1–2 of the 11 steps and does not raise the
  median.
- **Units:** a logger that sends µS/cm under `ec_ms_cm` already fails the range check; nothing new here.
- **Calibrated streams:** same as the other noise fields. The check looks at steps between readings, not levels.

## Tests

- **Python** (`services/model-router/tests/test_sensor_stream_habits.py`):
  - An EC entry in `NOISE_CASES` at 30 s: healthy σ 0.03 gives no flag in 20 of 20 seeds; σ 0.3 flags in at least
    12 of 20 seeds.
  - Boundary cases at median intervals of 60, 90, 91 and 300 s.
  - A window with one long gap whose median interval stays at 30 s.
  - A one-way EC ramp (dosing) that is not flagged.
  - A test that `NOISE_STEP_LIMIT_5MIN` and `NOISE_STEP_FLOOR` are unchanged.
- **JS parity:** cases for the same intervals (10, 30, 60, 90, 91, 300 s) in the persistent parity set.
- **Simulator:** add noisy EC to the fault lists in `examples/simulators/tests/test_fake_greenhouse.py` and
  `spaces/try-to-fool-pomona/tests/test_engine.py`, and assert it is caught at 30 s.
- **Space folder:** `make fool-space-check` rebuilds `vendor/`, the generated copy of the engine, so the game picks
  the change up there.

## Out of scope

- Tightening the air or humidity jump allowances. The data is one closed chamber; a greenhouse with vents and doors
  can move faster.
- EC noise for streams slower than 90 s (no real data supports a limit there).
- Slow drift of air, humidity, moisture or substrate temperature (a separate known miss).
- Substrate moisture and substrate temperature at 30 s (this dataset has neither).

## Done when

- `make test-local`, `local-validation`, `test-checker`, `test-demo`, `fool-space-check`,
  `fool-space-pyodide-check`, `fault-replay` and `real-replay` pass, and the real-replay output is unchanged (all of
  its data is 5-minute, so the new check must not fire there).
- A 30 s noisy-EC fault in the fake greenhouse is caught. Seeds 1–80 (720 ticks) keep 0 false alarms, and the demo
  and cold scenario verdicts are unchanged.
- `scripts/analyze_fast_sensor_log.py` on the downloaded dataset reproduces both tables. The EC table shows 0
  windows flagged at 0.20 at every rate and phase.
- The docs in item 3 list noisy EC as caught for streams at 90 s or faster, and still missed for slower ones.

## Open questions

1. **Scope.** Should the check apply to every fast EC stream, or wait until fast drain-EC data exists? The evidence
   covers tank EC only. Recommendation: apply it to every stream at 90 s or faster. A flag only asks for a probe
   check, and it can be revisited when real drain data arrives.
2. **Re-uploading the game and checker Spaces** after the change is a separate step. Nothing is uploaded without its
   own approval, with the exact file list shown first.

## Where the build differs

- **Time to a card is longer than estimated.** The doc says roughly 4 to 5 minutes at 30 s. In the fake greenhouse
  (noise on EC multiplied by 10, a reading every 30 seconds, seed 7, a temporary scenario) the `sensor_check` card
  came 8 minutes after the fault began in greenhouse-a and 6 minutes in greenhouse-b (16 and 12 samples), against
  never on the base commit. A noisy step reaches 0.20 only about 2 times in 3, so the window median needs more than
  6 noisy readings. The docs in item 3 say "6 to 8 minutes" or quote this measurement, not 4 to 5.
- **The analysis script matches the doc's EC table exactly and every number of the air, humidity and pH table,
  with two corrections to the wording.** (1) The "4 positions" of air temperature and humidity are really 3: the
  outflow position logs nan in most rows (windows: 63,582 of 308,285), so the table's ranges use the three full
  columns and the script lists outflow separately (it is also clean: 0 windows flagged, the largest window median
  0.17 C and 1.93 %RH). (2) For pH the real 30 s step p99.99 is 0.19 to 0.20 on probes 1 and 2 and 4.6 and 5.3 on
  probes 3 and 4 (glitches); the doc's "0.19 (5.3 on probe 4)" omits probe 3. One air column has 308,284 windows
  instead of 308,285 (one more missing reading in that column). The windows per probe in the EC table are about 1 fewer
  than the prototype analysis scripts count, because the script drops nan readings instead of letting them poison a median.
  The script runs in about 15 seconds, not 2 minutes.
- **One existing test changed meaning.** `test_ec_noise_is_not_judged_here_and_a_ph_plateau_or_irrigation_swing_is_quiet`
  asserted that EC noise at 30 s is not judged. It is now `test_a_ph_plateau_or_irrigation_swing_is_quiet` (the pH
  and moisture halves are kept); the EC halves are the new EC tests.
- **Extra parity cases.** `make_persistent_cases.py` gained 600 EC-only cases at 10, 30, 60, 90, 91 and 300 s (a
  window with a long gap, jittered once-a-minute stamps, one-way ramps, steps at the edge of 0.20), with a coverage
  assertion, so the parity set has more than "the same intervals".
- **Docs beyond the list.** The comment above `STEP_LIMITS` in `sensor_quality.py` also records the 30 s check of the
  jump allowances. `docs/LICENSE_AND_ATTRIBUTION.md` lists the dataset as a candidate source (evidence only, not in any
  release), with the DOI taken from the dataset's own listing.
- **No difference** in the limit value, the gate (90 s, median interval of the window), the shared rules, `rules.js`
  (untouched), `make real-replay` (output byte-identical to the base commit, and the dataset is not added to it).
