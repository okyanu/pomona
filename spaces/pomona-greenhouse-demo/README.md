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
hydroponic system and get back risk labels, safe next checks, and any
blocked actions -- exactly what the
[Pomona platform](https://github.com/okyanu/pomona) computes today at
`POST /v1/reasoners/tomato-risk`.

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

This demo runs the platform's deterministic tomato rules in your browser --
the same rules path the platform uses, not a simplified stand-in. The full
platform can also run the tomato model locally through Ollama, always checked
by those same rules; that model path is not part of this static demo.

## Try three preset scenarios

- **Routine reading** (substrate greenhouse) -- normal ranges, no risk
- **Hydroponic nutrient / pH risk** -- high pH and EC in a recirculating system, triggers a blocked fertigation action
- **Missing / suspect data** -- critical sensor fields absent, triggers a data-quality flag

## Vapour-pressure deficit (VPD)

The page also computes VPD from air temperature and humidity. Below 0.4 kPa the leaves stay wet,
so it raises `fungal_pressure` even when humidity is under 85 % (for example 17 °C at 80 %). At
1.6 kPa or more it only adds a "check irrigation / shading" note. Try 17 °C and 80 % humidity.

## Links

- Platform: [github.com/okyanu/pomona](https://github.com/okyanu/pomona)
- Model: [pomona-tomato-risk-reasoner-v0.1.7-lora](https://huggingface.co/Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora)
- Dataset: [greenhouse-sensor-data](https://huggingface.co/datasets/Okyanus/greenhouse-sensor-data)
- Collection: [Pomona -- Local AI for Safer Greenhouse Decision Support](https://huggingface.co/collections/Okyanus/pomona-local-ai-for-safer-greenhouse-decision-support-6a89931ffcc2f7a3f777f3b9)
