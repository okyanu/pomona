---
title: Pomona pH Calibration Checker
emoji: 🧪
colorFrom: green
colorTo: gray
sdk: static
pinned: false
license: apache-2.0
short_description: Check a pH calibration and spot a worn probe
tags:
- agriculture
- sensors
- ph
- calibration
- hydroponics
- iot
---

# Pomona pH Calibration Checker

Enter the volts your pH probe gives in pH 7 and pH 4 buffer (and optionally pH 10). The page works
out the calibration (`PH_SLOPE`, `PH_OFFSET`) for an ESP32 or Arduino logger and checks that it makes sense:

- the probe's **sensitivity** (mV per pH) is believable, which catches identical, swapped and wrong buffers
- the **pH 7 voltage** is inside what a 3.3 V ADS1115 can read
- with your board's expected sensitivity and slope direction: swapped buffers and a worn probe
- with a pH 10 buffer: the probe is linear (within 0.3 pH)
- with the probe's **first calibration**: whether it is `ok`, `weakening` (< 90 % of the first
  sensitivity, or the pH 7 voltage moved 0.1 V) or `worn` (< 80 %)

Everything runs in your browser. Nothing is uploaded.

These are the rules of the [Pomona](https://github.com/okyanu/pomona) cress logger firmware
(`tools/ph_calibrate.py`) and Core's probe-health report; the page matches the Python rules on
10,000 test cases. It tells you when a calibration is implausible, not that a plausible one is
correct: use fresh buffers. Advisory only.

Companion Space: [Pomona Sensor Data Checker](https://huggingface.co/spaces/Okyanus/pomona-sensor-data-checker)
checks whole sensor logs.
