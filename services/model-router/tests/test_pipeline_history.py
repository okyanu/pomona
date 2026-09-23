"""Pipeline temporal history coverage."""

import asyncio
from datetime import datetime, timedelta, timezone

from app.pipeline import evaluate_pipeline


def test_pipeline_passes_history_into_sensor_quality():
    start = datetime(2026, 9, 23, 10, tzinfo=timezone.utc)
    history = []
    for step in range(4):
        history.append(
            {
                "ph": 6.0,
                "ec_ms_cm": 2.0,
                "air_temperature_c": 24.0 + (step % 2) * 0.1,
                "humidity_pct": 60.0,
                "soil_moisture_pct": 40.0,
                "timestamp": (start + timedelta(minutes=20 * step)).isoformat(),
            }
        )
    sensor = {
        "ph": 6.0,
        "ec_ms_cm": 2.0,
        "air_temperature_c": 24.0,
        "humidity_pct": 60.0,
        "soil_moisture_pct": 40.0,
        "timestamp": (start + timedelta(minutes=100)).isoformat(),
    }
    # Freeze after prior variation so stuck_value can fire.
    history[0]["air_temperature_c"] = 24.0
    history[1]["air_temperature_c"] = 24.1
    history[2]["air_temperature_c"] = 24.0
    history[3]["air_temperature_c"] = 24.0
    sensor["air_temperature_c"] = 24.0
    result = asyncio.run(
        evaluate_pipeline(
            {"crop": "tomato", "system_type": "greenhouse_substrate", "zone_id": "a"},
            sensor,
            ["ph", "ec_ms_cm", "air_temperature_c", "humidity_pct", "soil_moisture_pct"],
            {"action_type": "continue_monitoring"},
            "dashboard",
            "rules_only",
            history=history,
        )
    )
    assert result["input"]["history_frames"] == 4
    assert "stuck_value" in result["sensor_quality"]["data_quality_labels"]
    assert result["final_decision"]["human_review_required"] is True
