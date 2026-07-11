# Source Mapping

This file describes the intended mapping from source datasets into Pomona digital twin input fields.

| Pomona field | Common source aliases |
|---|---|
| `air_temperature_c` | air_temp, temperature, ambient_temperature |
| `humidity_pct` | relative_humidity, rh, humidity |
| `co2_ppm` | co2, carbon_dioxide |
| `light_lux` | lux, illuminance |
| `light_ppfd` | ppfd, par |
| `ph` | pH, nutrient_solution_ph |
| `ec_ms_cm` | ec, electrical_conductivity |
| `tds_ppm` | tds, total_dissolved_solids |
| `water_temperature_c` | water_temp, nutrient_solution_temperature |
| `substrate_temperature_c` | root_zone_temp, substrate_temp |
| `substrate_moisture_pct` | soil_moisture, substrate_vwc |
| `actuator_states` | fan, pump, heater, vent, dosing_pump |
| `symptoms` | observation, visual_symptoms, scouting_notes |

## Active v0.1 Sources

| Source ID | Typical contribution |
|---|---|
| `udea_greenhouse_tomato` | Greenhouse air temperature, humidity, pH, EC, substrate temperature, substrate moisture |
| `4tu_autonomous_greenhouse_challenge` | Controlled greenhouse climate, CO2, PAR/PPFD, pH, EC, and actuator-state timeseries |
| `pomona_handwritten_eval_cases` | Curated seed and eval JSONL; no external raw download |
| `pomona_generated_normal_calibration` | Generated safe-range no-risk calibration rows for routine-monitoring behavior |

Source-specific normalizers should preserve raw source IDs in interim data and emit only verified, transformed records into publishable JSONL.
