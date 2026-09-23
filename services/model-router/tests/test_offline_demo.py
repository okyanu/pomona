import subprocess
import sys
from pathlib import Path


def test_offline_demo_runs_three_guarded_scenarios():
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run([sys.executable, str(root / "scripts/demo_local.py")],
                            cwd=root, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert '"scenario": "routine"' in result.stdout
    assert '"scenario": "high_ec_and_humidity"' in result.stdout
    assert '"scenario": "missing_ph"' in result.stdout
    assert result.stdout.count('"approval_available": false') == 3
