"""Test helper, run by the model-router venv's Python: `router_vclock.py PORT`.

The real model-router app under uvicorn, with its pipeline clock following each reading's sample time (+1 s), as the
in-process engine does: a simulated 2-hour run is then not judged against the wall clock (test_multi_device_feed.py).
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

router_dir = Path(__file__).resolve().parents[2] / "model-router"
sys.path.insert(0, str(router_dir))

import uvicorn  # noqa: E402
import app.main as main  # noqa: E402
from app import pipeline  # noqa: E402

pipeline.write_pipeline_audit = lambda record: None
real = pipeline.evaluate_pipeline


async def evaluate(farm_context, sensor, *args, **kwargs):
    sample = datetime.fromisoformat(str(sensor["timestamp"]).replace("Z", "+00:00"))
    pipeline._now = lambda value=sample + timedelta(seconds=1): value
    return await real(farm_context, sensor, *args, **kwargs)


main.evaluate_pipeline = evaluate
uvicorn.run(main.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
