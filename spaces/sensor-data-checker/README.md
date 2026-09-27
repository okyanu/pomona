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
- **stuck, flat or drifting** sensors (compared with the previous 11 readings of the same device)

Everything runs in your browser. Files are never uploaded.

## Formats

- One row per reading time: `time, temperature, humidity, pH, EC, …` (common column names
  are recognised; optional `device_id` / `zone_id`).
- One row per measurement: `timestamp_utc, measurement, value` plus optional `device_id`,
  `zone_id`, `boot_id`, the format written by Pomona's ESP32 SD logger.

## Where the rules come from

The checks are the deterministic sensor-quality rules from
[Pomona](https://github.com/okyanu/pomona) (`services/model-router/app/sensor_quality.py`),
ported to JavaScript. The port is tested against the Python rules on 8,638 cases, including
Python 3.11's timestamp parsing, so the page gives the same answers as the platform.

Why rules instead of an AI model? We measured it on the
[Agri Telemetry Sanity Bench](https://huggingface.co/datasets/Okyanus/agri-telemetry-sanity-bench):
fine-tuned small models scored 0.34–0.68, the rules 1.00.

Advisory only. This tool checks whether data is trustworthy; it does not judge whether growing
conditions are good, and it never controls equipment.

Source: [okyanu/pomona/spaces/sensor-data-checker](https://github.com/okyanu/pomona/tree/main/spaces/sensor-data-checker)
