import json
import subprocess
import sys
from pathlib import Path


def test_replay_passes_with_temporal_history():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/benchmark_sensor_fault_replay.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=20,
    )
    report = json.loads(result.stdout)
    rows = {row["scenario"]: row for row in report["scenarios"]}
    assert len(rows) == 8
    assert report["model_quality_evaluation"] is False
    assert rows["normal"]["false_positive"] == 0
    assert rows["spike"]["true_positive"] == 1
    assert rows["missing_ph"]["true_positive"] == 6
    assert rows["conflicting_probes"]["true_positive"] == 6
    assert rows["sustained_impossible_ph"]["true_positive"] == 6
    assert rows["dropout"]["false_negative"] == 0
    assert rows["dropout"]["true_positive"] == 3
    assert rows["slow_drift"]["false_negative"] == 0
    assert rows["stuck_value"]["false_negative"] == 0
    assert rows["stuck_value"]["true_positive"] >= 4
    assert report["passed"] is True
    assert result.returncode == 0
