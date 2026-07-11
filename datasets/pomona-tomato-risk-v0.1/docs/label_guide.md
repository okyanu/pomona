# Label Guide

Use risk labels to describe observable or sensor-derived risk, not final diagnosis.

## Risk Labels

- `high_ph`: pH is above tomato hydroponic target range.
- `low_ph`: pH is below tomato hydroponic target range.
- `high_ec`: EC is above target range or increasing into stress range.
- `low_ec`: EC is below target range and nutrient deficiency may be plausible.
- `heat_stress`: air or root-zone temperature is high enough to stress tomato plants.
- `cold_stress`: air or root-zone temperature is low enough to slow growth or uptake.
- `fungal_pressure`: humidity and symptoms suggest higher fungal risk; do not diagnose disease.
- `nutrient_uptake_issue`: symptoms plus pH, EC, water temperature, or root-zone conditions suggest uptake problems.
- `sensor_anomaly`: readings are physically implausible or internally inconsistent.
- `missing_critical_data`: one or more critical fields are missing for safe reasoning.
- `water_level_risk`: water availability or water temperature suggests irrigation/hydroponic risk.
- `actuator_conflict`: actuator states conflict with environmental risk or each other.

## Human Review

Set `human_review_required` to `true` when:

- Disease, pesticide, chemical, or fertigation decisions are involved.
- Critical sensor data is missing.
- Sensor values conflict.
- Actuator behavior appears unsafe.
