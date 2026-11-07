---
title: Pomona Sensor Data Checker
emoji: 🌱
colorFrom: green
colorTo: gray
sdk: static
pinned: false
license: apache-2.0
short_description: Find bad readings in greenhouse & hydroponic sensor logs
tags:
- agriculture
- sensors
- iot
- data-quality
- greenhouse
- hydroponics
datasets:
- Okyanus/agri-telemetry-sanity-bench
---

# Pomona Sensor Data Checker

Upload a sensor log from a greenhouse, grow tent or hydroponic system and see which readings
you shouldn't trust:

- **missing** values (empty cells, `null`, or never logged)
- **impossible** values (pH outside 3–11, humidity outside 0–100 %, EC outside 0–12 mS/cm…)
- **broken** values (`err`, `NaN`, text where a number should be)
- **badly timed** readings (no timezone, future-dated, stale latest reading, logging gaps, reboots,
  time going backwards)
- **stuck, flat, noisy or drifting** sensors (compared with the previous 11 readings of the same device, and with the
  device's own earlier readings in the file: slow drift, longer freezes, sudden jumps, noisy probes; a noisy EC
  probe is caught only when the log is sampled every 90 seconds or faster, since 5-minute drain EC jumps by itself)

Everything runs in your browser. Files are never uploaded.

Companion Space: [Pomona pH Calibration Checker](https://huggingface.co/spaces/Okyanus/pomona-ph-calibration-checker)
turns pH buffer readings into a calibration and checks that the probe is not wearing out.

## Formats

- One row per reading time: `time, temperature, humidity, pH, EC, …` (common column names
  are recognised; optional `device_id` / `zone_id`).
- One row per measurement: `timestamp_utc, measurement, value` plus optional `device_id`,
  `zone_id`, `boot_id`, the format written by Pomona's ESP32 SD logger.

## Where the rules come from

The checks are the deterministic sensor-quality rules from
[Pomona](https://github.com/okyanu/pomona) (`services/model-router/app/sensor_quality.py`),
ported to JavaScript. The port is tested against the Python rules on more than 18,000 cases, including
Python 3.11's timestamp parsing, so the page gives the same answers as the platform.

Two parts. `rules.js` holds the checks over a reading and the 11 before it. `persistent.js` holds the checks that
judge a reading against what the device did earlier (Pomona Core's trusted per-stream reference,
`services/core/app/trusted_baseline.py`, and `apply_persistent_checks`): a level that stays away from the
trusted median, a value that does not change for too long (air temperature 45 minutes, humidity 30 minutes,
substrate temperature 6 hours, pH/EC on a probe that normally changes every reading), a step faster than the probe can
change, and a probe that jumps between samples. The reference is built from the device's earlier readings in the
file, leaving out any value the sensor check removed, as Core does. The page has no probe calibrations, so none are
applied.

Why rules instead of an AI model? We measured it on the
[Agri Telemetry Sanity Bench](https://huggingface.co/datasets/Okyanus/agri-telemetry-sanity-bench):
fine-tuned small models scored 0.34–0.68, the rules 1.00.

Advisory only. This tool checks whether data is trustworthy; it does not judge whether growing
conditions are good, and it never controls equipment.

Source: [okyanu/pomona/spaces/sensor-data-checker](https://github.com/okyanu/pomona/tree/main/spaces/sensor-data-checker)
