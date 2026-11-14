# Next 90 days

**Dated 2026-11-14. The maintainer's current focus, as a plan, not progress.** Nothing below has been done yet. The ESP32 logger firmware compiles but has not run on a board, and there is no field data. Phase status stays in [PHASES.md](./PHASES.md).

Three items, in order. Each one needs the one before it.

## 1. Bench-test the ESP32 logger

Run the firmware in [`devices/esp32-cress-logger`](https://github.com/okyanu/pomona/tree/main/devices/esp32-cress-logger) on a real board with the sensors wired, including the pH calibration check. See [WATERCRESS_PILOT.md](./WATERCRESS_PILOT.md) and the logger README.

**Done when:** both nodes (hydro, soil) have logged for the 24-48 h dry run; after a deliberate power pull a new `boot_id` appears and rows continue; the CSV imports into Core with no unexplained rejected rows; the boot log shows the `ph_cal=` line and the pH rows are not marked `suspect`; the probe pH has been compared with a handheld pH reading.

## 2. Run the two-zone watercress pilot (monitoring only)

One hydroponic zone and one soil zone, sown together, as described in [WATERCRESS_PILOT.md](./WATERCRESS_PILOT.md). Pomona drives no pumps, dosing or relays.

**Done when:** about 2-3 weeks of data from both zones are imported; the original SD-card CSV files are kept unchanged; and every real event (a fault, a plant problem, a recalibration) has a dated note.

## 3. Replay the pilot data through the existing checks

Run the pilot readings through the existing sensor checks and the scorer, the way `make real-replay` does for the third-party logs ([SENSOR_FAULT_REPLAY.md](./SENSOR_FAULT_REPLAY.md)), and compare the result with the event notes. `make real-replay` currently reads two third-party logs; whether it needs a loader for the pilot CSVs has not been checked.

**Done when:** a public write-up lists what the checks got right and what they got wrong on the pilot data, with the raw files and notes kept.

## Parked until then

- New model training
- New demo Spaces
- Further hardware designs
