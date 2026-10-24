---
title: Pomona Greenhouse Demo
emoji: 🌱
colorFrom: green
colorTo: gray
sdk: static
pinned: false
license: apache-2.0
short_description: Guarded greenhouse & hydroponic tomato risk reasoner
models:
  - Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora
datasets:
  - Okyanus/greenhouse-sensor-data
---

# Pomona -- Guarded Greenhouse & Hydroponic Risk Demo

Enter a tomato sensor reading from a substrate/soil greenhouse or a
hydroponic system and get back a sensor-trust verdict, risk labels, safe next
checks, and any blocked actions. The page runs the same chain as the
[Pomona platform](https://github.com/okyanu/pomona) pipeline: sensor-quality
check, then sensor veto, then the tomato rules.

## Sensor trust: the sensor check and the veto

Before any tomato advice, the page asks: can this reading be believed?

1. **Sensor check** -- looks for missing readings, impossible values (a pH of
   13, humidity over 100 %), a primary and backup temperature that disagree,
   a temperature in the wrong unit, a value that is not a number, or a
   timestamp that is missing, invalid, too old or in the future.
2. **Sensor veto** -- a reading that fails the check is *removed*, never
   corrected, so the tomato rules cannot turn a broken probe into advice
   (a pH of 13 is no longer reported as high pH). The result is one of:
   - **trusted** -- everything passed;
   - **partial** -- some readings were not used (for example "pH not used --
     check the probe") and the others are still reasoned on;
   - **cannot confirm** -- the whole packet is untrustworthy (stale or
     future timestamp, invalid packet, unit mismatch) or every expected
     reading failed; the tomato rules are skipped.
3. **Tomato rules** -- run on what is left. A reading the veto removed is not
   also reported as "missing critical data"; the sensor-trust section already
   says so.

The sensor-quality code is an exact copy of the one in the
[Sensor Data Checker](https://huggingface.co/spaces/Okyanus/pomona-sensor-data-checker)
Space (`rules.js`; Spaces are separate repos, so it is vendored, not loaded
across Spaces), and `trust_gate.js` is a port of the platform's
`apply_sensor_veto`.

**Fields checked.** `air_temperature_c`, `humidity_pct`, `ph`, `ec_ms_cm`, plus
`substrate_moisture_pct` for the substrate/soil system. These are the
pipeline's default expected fields; the pipeline does not look at the system
type, so the demo drops the substrate moisture probe for hydroponic systems,
which have none. Substrate temperature and the other fields are still
range-checked when present.

**Timestamp.** The page stamps each sample with the current time, so "stale"
and "future" readings cannot happen on the page itself (the parity tests
cover them).

## What is not in this demo

- **History-based checks.** Stuck, flat-line, noisy-signal and drift checks
  need a log of earlier readings. The page sees one reading at a time (history
  is empty). Use the
  [Sensor Data Checker](https://huggingface.co/spaces/Okyanus/pomona-sensor-data-checker)
  to run them on a CSV log.
- **Water-irrigation and nutrient specialists.** The full pipeline also runs
  them (behind the same veto); the demo runs the tomato rules only.
- **Any model.** Deterministic rules only.

## Tomato only

This demo applies **tomato** thresholds only. In the full platform, the
tomato-risk endpoint returns `not_applicable` for any other crop (for example
the watercress monitoring pilot) instead of giving tomato advice.

## Advisory only

This demo never controls irrigation, dosing, or any other hardware. It never
issues a pesticide or fertigation command and never gives a definitive
disease diagnosis -- those are always **blocked actions** that require a
human to review and decide. A deterministic safety checker is the final
authority in the full platform; this demo shows that same guarded logic in
isolation.

This demo runs the platform's deterministic sensor-check, veto and tomato rules in your browser --
the same rules path the platform uses, not a simplified stand-in. The full
platform can also run the tomato model locally through Ollama, always checked
by those same rules; that model path is not part of this static demo.

## Try four preset scenarios

- **Routine reading** (substrate greenhouse) -- normal ranges, sensor trust is "trusted", no risk
- **Hydroponic nutrient / pH risk** -- high pH and EC in a recirculating system; the readings are believable, so it triggers a blocked fertigation action
- **Missing / suspect data** -- pH and EC are left blank; the sensor check flags them as missing, sensor trust is "partial", and the tomato rules run on the remaining readings (no pH/EC advice)
- **Broken pH probe** -- pH 13 is impossible; the pH is vetoed (not used, no pH advice), sensor trust is "partial", and the other readings are still reasoned on

## Vapour-pressure deficit (VPD)

The page also computes VPD from air temperature and humidity. Below 0.4 kPa the leaves stay wet,
so it raises `fungal_pressure` even when humidity is under 85 % (for example 17 °C at 80 %). At
1.6 kPa or more it only adds a "check irrigation / shading" note. Try 17 °C and 80 % humidity.

## Links

- Platform: [github.com/okyanu/pomona](https://github.com/okyanu/pomona)
- Model: [pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- Dataset: [greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)
- Collection: [Pomona -- Local AI for Safer Greenhouse Decision Support](https://huggingface.co/collections/Okyanus/pomona-local-ai-for-safer-greenhouse-decision-support-6a89931ffcc2f7a3f777f3b9)
