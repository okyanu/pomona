"""Prepare immutable local evaluation/training artifacts; never train or upload.

Expected classification targets are explicit specifications, not detector output.
Freeze records artifact identity only, not model release approval.
"""
import argparse
import copy
import hashlib
import json
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

from build_sensor_quality_release_candidate import cases
from prepare_sensor_quality_training import prepare


def expanded_cases():
    rows = cases()
    base = next(r for r in rows if r['bucket'] == 'normal')

    def add(bucket, change, labels=(), missing=(), suspect=()):
        row = copy.deepcopy(base)
        row.update(id=f'extended-{len(rows):04d}', bucket=bucket)
        change(row['input'])
        row['expected_output'] = dict(data_quality_labels=list(labels), missing_fields=list(missing),
                                      suspect_fields=list(suspect), human_review_required=bool(labels or missing or suspect))
        rows.append(row)

    fields = {'ph': 'missing_ph', 'ec_ms_cm': 'missing_ec', 'air_temperature_c': 'missing_temperature',
              'humidity_pct': 'missing_humidity', 'soil_moisture_pct': 'missing_moisture'}
    for field, label in fields.items():
        for omitted in (False, True):
            def change(i, f=field, omit=omitted):
                if f not in i['expected_fields']: i['expected_fields'].append(f)
                if omit: i['sensor'].pop(f, None)
                else: i['sensor'][f] = None
            add(f'{label}_{omitted}', change, [label], [field])
        for value in (True, 'broken', 'NaN', 'Infinity', {}):
            add('invalid_' + field, lambda i, f=field, v=value: i['sensor'].update({f: v}),
                ['insufficient_context'], suspect=[field])
    bounds = [('ph', 3, 11, 'impossible_ph'), ('ec_ms_cm', 0, 12, 'impossible_ec'),
              ('air_temperature_c', -10, 65, 'impossible_temperature'), ('humidity_pct', 0, 100, 'impossible_humidity')]
    for field, low, high, label in bounds:
        for value, bad in ((low, False), (high, False), (low-.001, True), (high+.001, True)):
            add('boundary_' + field, lambda i, f=field, v=value: i['sensor'].update({f:v}),
                [label] if bad else [], suspect=[field] if bad else [])
    for seconds, labels in ((-3601,['stale_reading']),(-3600,[]),(60,[]),(61,['insufficient_context'])):
        add('clock_boundary', lambda i, s=seconds: i['sensor'].update(timestamp=(datetime.fromisoformat(i['current_time'])+timedelta(seconds=s)).isoformat()),
            labels, suspect=['timestamp'] if labels else [])
    for value in (None, 'broken', '2027-02-03T00:00:00'):
        add('invalid_clock', lambda i, v=value: i['sensor'].update(timestamp=v), ['insufficient_context'], suspect=['timestamp'])
    add('missing_clock', lambda i: i['sensor'].pop('timestamp'), ['insufficient_context'], suspect=['timestamp'])
    add('unit_mismatch', lambda i: i['sensor'].update(temperature_f=77), ['unit_mismatch'], suspect=['air_temperature_c','temperature_f'])
    for previous, bad in ((5.21,False),(5.0,True)):
        add('drift_boundary', lambda i,p=previous: i['sensor'].update(ph=6.0,previous_ph=p),
            ['sensor_drift_possible'] if bad else [], suspect=['ph','previous_ph'] if bad else [])
    for backup,bad in ((32.99,False),(33,True)):
        add('conflict_boundary', lambda i,b=backup: i['sensor'].update(air_temperature_c=25,backup_air_temperature_c=b),
            ['conflicting_readings'] if bad else [], suspect=['air_temperature_c','backup_air_temperature_c'] if bad else [])
    add('missing_context', lambda i:i.update(farm_context={}), ['insufficient_context'])
    add('empty_expected', lambda i:i.update(expected_fields=[]), ['insufficient_context'])
    add('compound_ranges', lambda i:i['sensor'].update(ph=12,ec_ms_cm=-1,humidity_pct=101),
        ['impossible_ph','impossible_ec','impossible_humidity'],suspect=['ph','ec_ms_cm','humidity_pct'])
    # Omit exact repeated inputs introduced by the boundary/missing specifications.
    seen = set(); unique = []
    for row in rows:
        key = json.dumps(row['input'],sort_keys=True)
        if key not in seen: unique.append(row); seen.add(key)
    return unique


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(source, destination):
    if destination.exists(): raise FileExistsError('Choose a new bundle directory')
    rows = expanded_cases()
    def key(i):
        i=copy.deepcopy(i); i.get('farm_context',{}).pop('zone_id',None)
        i.pop('current_time',None); i.get('sensor',{}).pop('timestamp',None)
        return json.dumps(i,sort_keys=True)
    holdout = {key(r['input']) for r in rows}
    # Remove exact content overlap ignoring identity/time across every supplied split.
    module_path = Path(__file__).resolve().parents[2]/'services/model-router/app/sensor_quality.py'
    spec = importlib.util.spec_from_file_location('review_sensor_quality', module_path)
    rules = importlib.util.module_from_spec(spec); spec.loader.exec_module(rules)
    filtered = {}; excluded = {}; quarantined = {}
    for split in ('train','validation','test'):
        records = [json.loads(x) for x in (source/f'{split}.jsonl').read_text().splitlines() if x.strip()]
        filtered[split] = []
        quarantined[split] = []
        for r in records:
            if key(r['input']) in holdout: continue
            i = r['input']
            if not i.get('current_time'):
                quarantined[split].append({'id':r['id'],'reason':'missing current_time'}); continue
            got = rules.derive_sensor_quality(i['farm_context'],i['sensor'],i['expected_fields'],
                    now=datetime.fromisoformat(i['current_time'].replace('Z','+00:00')))
            fields = ('data_quality_labels','missing_fields','suspect_fields')
            if any(set(got[k]) != set(r['expected_output'][k]) for k in fields) or got['human_review_required'] != r['expected_output']['human_review_required']:
                quarantined[split].append({'id':r['id'],'reason':'classification disagrees with current contract'}); continue
            filtered[split].append(r)
        excluded[split] = [r['id'] for r in records if key(r['input']) in holdout]
    destination.mkdir(parents=True)
    def write(path, records):
        path.write_text(''.join(json.dumps(r,sort_keys=True,allow_nan=False)+'\n' for r in records))
    write(destination/'holdout.jsonl',rows)
    provenance = {}
    for split, records in filtered.items():
        raw=destination/f'{split}.jsonl'; write(raw,records)
        provenance[split]=prepare(raw,destination/f'{split}.canonical.jsonl')
        provenance[split]['original_source_sha256']=digest(source/f'{split}.jsonl')
    manifest={'frozen':True,'release_approved':False,'training_run':False,'cases':len(rows),
              'source':str(source),'splits':provenance,'overlap_exclusions':excluded,'quarantined':quarantined,
              'rules_sha256':digest(module_path),
              'limits':['synthetic engineering contract, not field validation','semantic/template overlap not ruled out',
                        'holdout must never be used for training','legacy training targets not regenerated from new rules',
                        'prepared text bundle; not an executed or GPU-validated notebook'],
              'files':{p.name:digest(p) for p in destination.iterdir() if p.is_file()}}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return manifest


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source',type=Path); parser.add_argument('destination',type=Path)
    args=parser.parse_args(); print(json.dumps(build(args.source,args.destination),indent=2))
