"""Offline-capable Pomona software-validation orchestrator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.actuator_gate import route_actuator_gate_reasoner
from app.advisor import explain
from app.agronomy_calc import (
    NpkTarget,
    WeatherInputs,
    crop_evapotranspiration,
    fertilizer_grams_for_target,
    irrigation_volume_liters,
    reference_et_penman_monteith,
)
from app.audit import write_pipeline_audit
from app.config import settings
from app.nutrient_ph_ec import route_nutrient_ph_ec_reasoner
from app.safety_triage import route_safety_triage_reasoner
from app.sensor_quality import route_sensor_quality_reasoner
from app.shared_chain import derive_actuator_gate
from app.tomato_reasoner import derive_tomato_risk
from app.water_irrigation import route_water_irrigation_reasoner


DEFAULT_EXPECTED_FIELDS = [
    "air_temperature_c",
    "humidity_pct",
    "ph",
    "ec_ms_cm",
    "substrate_moisture_pct",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _combined_input(farm_context: dict[str, Any], sensor: dict[str, Any]) -> dict[str, Any]:
    combined = dict(farm_context)
    combined.update(sensor)
    return combined


def _agronomy_estimate(farm_context: dict[str, Any]) -> dict[str, Any] | None:
    """Compute FAO-56 irrigation and NPK dosing estimates when farm_context
    supplies the optional inputs they need (weather, zone area, crop
    coefficient, and/or an NPK target). Returns None field-by-field when
    the inputs for that estimate are absent, rather than guessing values
    that would feed a safety-relevant pipeline.

    This is advisory/informational only; it never sets risk labels or
    blocked actions, and it is not required for the pipeline to run.
    """
    weather_data = farm_context.get("weather")
    zone_area_m2 = farm_context.get("zone_area_m2")
    crop_kc = farm_context.get("crop_kc")
    npk_target_data = farm_context.get("npk_target")

    irrigation_estimate = None
    if weather_data and zone_area_m2 and crop_kc is not None:
        try:
            weather = WeatherInputs(**weather_data)
            eto = reference_et_penman_monteith(weather)
            etc = crop_evapotranspiration(eto, kc=crop_kc)
            liters = irrigation_volume_liters(
                etc,
                area_m2=zone_area_m2,
                irrigation_efficiency=farm_context.get("irrigation_efficiency", 0.9),
            )
            irrigation_estimate = {
                "reference_et_mm_day": round(eto, 3),
                "crop_et_mm_day": round(etc, 3),
                "expected_irrigation_liters": round(liters, 2),
            }
        except (TypeError, ValueError):
            irrigation_estimate = None

    fertilizer_estimate = None
    if npk_target_data:
        try:
            target = NpkTarget(**npk_target_data)
            fertilizer_estimate = fertilizer_grams_for_target(target)
        except (TypeError, ValueError):
            fertilizer_estimate = None

    if irrigation_estimate is None and fertilizer_estimate is None:
        return None
    return {"irrigation": irrigation_estimate, "fertilizer": fertilizer_estimate}


async def evaluate_pipeline(
    farm_context: dict[str, Any],
    sensor: dict[str, Any],
    expected_fields: list[str],
    proposed_command: dict[str, Any] | None,
    actor: str,
    mode: str,
    scenario_id: str | None = None,
) -> dict[str, Any]:
    """Evaluate all deterministic specialists, then apply the final gate."""
    pipeline_id = f"pipeline-{uuid4().hex[:12]}"
    evaluated_at = _now()
    fields = expected_fields or DEFAULT_EXPECTED_FIELDS
    specialist_input = {
        "farm_context": farm_context,
        "sensor": sensor,
        "expected_fields": fields,
    }
    specialist_mode = "hybrid_guarded" if mode == "hybrid_guarded" else "rules_only"
    quality = route_sensor_quality_reasoner(
        specialist_input,
        specialist_mode,
        "pomona-sensor-quality-reasoner-v0.1",
        now=evaluated_at,
    )
    water_backend = "rules" if mode == "rules_only" else settings.reasoner_backend
    water = await route_water_irrigation_reasoner(
        specialist_input,
        specialist_mode,
        water_backend,
        "pomona-water-irrigation-risk-reasoner-v0.1",
    )
    nutrient_backend = "rules" if mode == "rules_only" else settings.reasoner_backend
    nutrient = await route_nutrient_ph_ec_reasoner(
        specialist_input,
        specialist_mode,
        "pomona-nutrient-ph-ec-reasoner-v0.1",
        nutrient_backend,
    )
    agronomy_calc = _agronomy_estimate(farm_context)
    crop_input = _combined_input(farm_context, sensor)
    tomato = derive_tomato_risk(crop_input) if farm_context.get("crop") == "tomato" else {
        "risk_labels": [],
        "missing_data": [],
        "safe_next_checks": ["use a crop-specific reasoner for this crop"],
        "blocked_actions": [],
        "human_review_required": False,
    }

    all_risk_labels = list(dict.fromkeys([
        *quality["data_quality_labels"],
        *water["irrigation_risk_labels"],
        *nutrient["nutrient_risk_labels"],
        *tomato["risk_labels"],
    ]))
    safety_input = {
        "farm_context": farm_context,
        "sensor": sensor,
        "sensor_quality": quality,
        "risk_labels": all_risk_labels,
        "actor": actor,
        "proposed_command": proposed_command or {"action_type": "continue_monitoring"},
    }
    safety = derive_actuator_gate(safety_input)
    safety_triage = route_safety_triage_reasoner(
        safety_input,
        specialist_mode,
        "pomona-safety-triage-reasoner-v0.1",
    )
    blocked_actions = list(dict.fromkeys([
        *water["blocked_actions"],
        *nutrient["blocked_actions"],
        *tomato["blocked_actions"],
        *safety["blocked_actions"],
    ]))
    human_review = bool(
        quality["human_review_required"]
        or water["human_review_required"]
        or nutrient["human_review_required"]
        or tomato["human_review_required"]
        or safety["human_approval_required"]
    )
    guarded_context = {
        "risk_labels": all_risk_labels,
        "blocked_actions": blocked_actions,
        "safe_next_checks": list(dict.fromkeys([
            *quality["safe_next_checks"],
            *water["safe_next_checks"],
            *nutrient["safe_next_checks"],
            *tomato["safe_next_checks"],
            *safety["safe_alternatives"],
        ])),
        "human_review_required": human_review,
    }
    advisor = await explain(
        "Explain the guarded Pomona software-validation result.",
        sensor,
        backend="stub",
        guarded_context=guarded_context,
    )
    result = {
        "pipeline_id": pipeline_id,
        "evaluated_at": evaluated_at.isoformat().replace("+00:00", "Z"),
        "scenario_id": scenario_id,
        "mode": mode,
        "source": "deterministic_guarded_pipeline",
        "input": {"farm_context": farm_context, "sensor": sensor, "expected_fields": fields},
        "sensor_quality": quality,
        "water_irrigation": water,
        "nutrient_ph_ec": nutrient,
        "crop_risk": tomato,
        "agronomy_calc": agronomy_calc,
        "agronomist": {
            "backend": advisor["backend"],
            "explanation": advisor["explanation"],
            "safety_note": advisor["safety_note"],
        },
        "safety": safety,
        "safety_triage": safety_triage,
        "final_decision": {
            "risk_level": "high" if blocked_actions or human_review else "routine",
            "blocked_actions": blocked_actions,
            "human_review_required": human_review,
            "safe_next_checks": guarded_context["safe_next_checks"],
        },
    }
    write_pipeline_audit({
        "pipeline_id": pipeline_id,
        "evaluated_at": result["evaluated_at"],
        "scenario_id": scenario_id,
        "risk_level": result["final_decision"]["risk_level"],
        "blocked_actions": blocked_actions,
        "human_review_required": human_review,
    })
    return result
