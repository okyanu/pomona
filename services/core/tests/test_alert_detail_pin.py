"""The in-process engine's `alert_detail` is a copy of Core's (the engine cannot import Core's package next to the
router's, so it copies; docs/design/multi-device-zones-slice3.md 3.4). This pins the copy to the original: both are
called on sample pipeline results, and the two constants and the function source must agree. Runs in the Core venv."""
import inspect
import sys
from pathlib import Path

import pytest

SERVICE_DIR = Path(__file__).resolve().parents[1]
ROOT = SERVICE_DIR.parents[1]
sys.path.insert(0, str(SERVICE_DIR))
for module_name in list(sys.modules):
    if module_name == "app" or module_name.startswith("app."):
        del sys.modules[module_name]
sys.path.insert(0, str(ROOT / "examples" / "simulators"))

import inprocess_pomona as engine
import app.outcome_feed as feed

LONG = "check the probe " * 60  # 960 characters: over the 500-character cut

SAMPLE_RESULTS = [
    {},
    {"sensor_quality": None},
    {"sensor_quality": {}},
    {"sensor_quality": {"safe_next_checks": None}},
    {"sensor_quality": {"safe_next_checks": []}},
    {"sensor_quality": {"safe_next_checks": ["continue routine monitoring"]}},
    {"sensor_quality": {"safe_next_checks": ["inspect pH probe calibration and units before using this reading"]}},
    {"sensor_quality": {"safe_next_checks": ["continue routine monitoring", "compare ec with a meter", "re-seat the probe"]}},
    {"sensor_quality": {"safe_next_checks": ["", "a", None, 7, "continue routine monitoring", "b"]}},
    {"sensor_quality": {"safe_next_checks": [LONG]}},
    {"sensor_quality": {"safe_next_checks": ["x" * 499]}},
    {"sensor_quality": {"safe_next_checks": ["x" * 500]}},
    {"sensor_quality": {"safe_next_checks": ["x" * 501]}},
    {"sensor_quality": {"safe_next_checks": ["a" * 300, "b" * 300]}},
    {"sensor_quality": {"safe_next_checks": ["continue routine monitoring"] * 3, "data_quality_labels": ["stuck_value"]}},
]


@pytest.mark.parametrize("result", SAMPLE_RESULTS, ids=range(len(SAMPLE_RESULTS)))
def test_the_engines_alert_detail_equals_cores_on_sample_results(result):
    assert engine.alert_detail(result) == feed.alert_detail(result)


def test_the_cut_and_the_routine_line_are_the_same_in_both():
    assert engine.DETAIL_MAX_CHARS == feed.DETAIL_MAX_CHARS == 500
    assert engine.ROUTINE_CHECK == feed.ROUTINE_CHECK
    assert len(engine.alert_detail({"sensor_quality": {"safe_next_checks": [LONG]}})) == 500


def test_the_function_source_is_the_same_apart_from_the_docstring():
    def body(function):
        source = inspect.getsource(function)
        return source[source.index('"""', source.index('"""') + 3) + 3:]  # after the closing docstring quotes

    assert body(engine.alert_detail) == body(feed.alert_detail)
