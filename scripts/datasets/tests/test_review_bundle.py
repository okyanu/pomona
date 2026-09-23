import importlib.util
import json
import sys
from pathlib import Path
from datetime import datetime
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prepare_sensor_quality_review_bundle import expanded_cases, build, digest


def test_explicit_extended_expectations():
    path=Path(__file__).resolve().parents[3]/'services/model-router/app/sensor_quality.py'
    spec=importlib.util.spec_from_file_location('review_rules',path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    rows=expanded_cases()
    assert len(rows)==123
    for row in rows:
        i=row['input']; got=module.derive_sensor_quality(i['farm_context'],i['sensor'],i['expected_fields'],now=datetime.fromisoformat(i['current_time']))
        for key,value in row['expected_output'].items():
            assert (sorted(got[key])==sorted(value)) if isinstance(value,list) else got[key]==value


def test_bundle_immutable_and_overlap_removed(tmp_path):
    source=tmp_path/'source'; source.mkdir()
    for split in ('train','validation','test'):
        (source/f'{split}.jsonl').write_text(json.dumps(expanded_cases()[0])+'\n')
    out=tmp_path/'bundle'; manifest=build(source,out)
    assert manifest['overlap_exclusions']['train']
    assert not manifest['training_run'] and not manifest['release_approved']
    for name,sha in manifest['files'].items(): assert digest(out/name)==sha
    with pytest.raises(FileExistsError): build(source,out)
