"""CPU-only release checks; never load a model, train, or submit a job."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from training.social_mixed.core import DATA, load_data
from training.social_mixed.curriculum_sampling import select
from training.social_mixed.structure_coverage import audit
from training.social_mixed.scoring_scope import ALLOWED_MODES, validate_rows


def check():
    data = load_data()
    manifest = json.loads((DATA/'manifest.json').read_text())
    if manifest.get('allowed_completion_modes') != list(ALLOWED_MODES):
        raise ValueError('Training release must explicitly exclude mixed completion rules')
    for name, expected in manifest.get('artifact_hashes', {}).items():
        if hashlib.sha256((DATA/name).read_bytes()).hexdigest() != expected:
            raise ValueError('Frozen auxiliary artifact changed: '+name)
    for name, record in manifest['files'].items():
        payload = (DATA/name).read_bytes()
        if hashlib.sha256(payload).hexdigest() != record['sha256']:
            raise ValueError('Frozen artifact changed: '+name)
        if name.startswith(('bp_', 'selfplay_')) or name == 'diagnostics.jsonl':
            validate_rows([json.loads(line) for line in payload.splitlines()], name)
        if len(payload.splitlines()) != record['count']:
            raise ValueError('Frozen artifact count changed: '+name)
    required = {'B1','B2','B3','P1','P2','P3','P4'}
    if not required <= {t['kernel'] for t in data['bp_train']}:
        raise ValueError('Incomplete training kernels')
    report = audit(DATA)
    if report['cross_split_families']:
        raise ValueError('Dependency geometry crosses splits')
    tested = set()
    p4_updates = 0
    for step in range(512):
        batch = select(data['bp_train'], step, 42)
        tested.update(t['id'] for t in batch)
        p4 = [t for t in batch if t['kernel']=='P4']
        if p4:
            p4_updates += 1
            if not {'query_only','ordinary_only'} <= {t['information_role'] for t in p4}:
                raise ValueError('P4 update lacks positive/negative control')
    if tested != {t['id'] for t in data['bp_train']}:
        raise ValueError('Training schedule leaves unused tasks')
    from training.social_mixed.validation import Validator
    validator=Validator(data,lambda requests: [])
    validation=validator.tasks
    cell = lambda t: (t['kernel'],t['completion_mode'],t.get('information_role','na'))
    if {cell(t) for t in validation} != {cell(t) for t in data['bp_validation'] if t['kernel']!='A0'}:
        raise ValueError('Development evaluation misses available cells')
    if not any(t['kernel']=='P4' and t.get('information_role')=='query_only' for t in validation):
        raise ValueError('Development evaluation cannot detect never-investigate')
    return dict(dataset=DATA.name, allowed_completion_modes=list(ALLOWED_MODES), mode_counts=manifest['mode_counts'], manifest_sha256=hashlib.sha256((DATA/'manifest.json').read_bytes()).hexdigest(),
                counts={k:len(v) for k,v in data.items()}, development_tasks_per_evaluation=len(validation),
                development_calls_per_evaluation=len(validation), development_selfplay_games=len(validator.resets),
                scheduled_training_tasks=len(tested), checked_updates=512, paired_p4_updates=p4_updates,
                structure_families_by_split=dict(Counter({split:len({r['structure_family'] for r in report['records'] if r['split']==split}) for split in ('train','validation','test')})),
                test_used_for_training_or_periodic_validation=False,
                scope='Static release checks only; no learning claim or GPU experiment',
                limitations=['Historical use of inherited test sources not independently established'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    result=check();payload=json.dumps(result,indent=2)+'\n'
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(payload)
    print(payload,end='')

if __name__=='__main__':main()
