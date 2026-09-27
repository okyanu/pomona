import importlib.util
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest

# Distinct package name avoids collisions with the other services in joint tests.
root=Path(__file__).resolve().parents[1]/"app"
spec=importlib.util.spec_from_file_location("twin_replay_test",root/"__init__.py",submodule_search_locations=[str(root)])
package=importlib.util.module_from_spec(spec); sys.modules[spec.name]=package; spec.loader.exec_module(package)
from twin_replay_test.replay import replay


def records():
    return [{"farm_id":"f","zone_id":"z","quality":"valid",
             "timestamp":(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(minutes=15*i)).isoformat(),
             "state":{"air_temperature_c":20+i}} for i in range(8)]


def test_persistence_tie_and_known_errors():
    result=replay(records(),split_index=3)
    metric=result["metrics_by_horizon_minutes"]["15"]["variables"]["air_temperature_c"]
    assert metric["twin"]==metric["persistence"]
    assert metric["twin"]=={"n":4,"mae":1.0,"rmse":1.0,"bias":-1.0}
    assert not result["parameters_fitted"] and not result["field_validated"]


def test_calibration_block_never_scored():
    rows=records(); before=replay(rows,split_index=3)
    rows[0]["state"]["air_temperature_c"]=70
    after=replay(rows,split_index=3)
    assert before["metrics_by_horizon_minutes"]==after["metrics_by_horizon_minutes"]
    assert before["dataset_sha256"]!=after["dataset_sha256"]


def test_gap_and_bad_quality_not_imputed():
    rows=records(); rows.pop(4); rows[3]["quality"]="suspect"
    result=replay(rows,split_index=3,horizons=(1,))
    assert result["rejected_quality_pairs"]==0  # rejected origin has no exact target
    assert result["metrics_by_horizon_minutes"]["15"]["missing_target_pairs"]==2
    rows=records(); rows[4]["quality"]="suspect"
    assert replay(rows,split_index=3,horizons=(1,))["rejected_quality_pairs"]==2


@pytest.mark.parametrize("mutation",[lambda r:r[0].update(zone_id="other"),
    lambda r:r[1].update(timestamp=r[0]["timestamp"]),
    lambda r:r[0]["state"].update(air_temperature_c=True)])
def test_rejects_invalid_logs(mutation):
    rows=records(); mutation(rows)
    with pytest.raises(ValueError): replay(rows,split_index=3)
