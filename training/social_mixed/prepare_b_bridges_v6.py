"""Training-only inference scaffolds, preserving original hard tasks and all held-out rows."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
from training.social_mixed.audit_zero_signal import audit_task,interface_check,VALUES
from training.b_sft.preference_contract import belief
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'examples/social_mixed/data_reasoning_v5_candidate'
OUT=ROOT/'examples/social_mixed/data_reasoning_v6'


def read(p):return [json.loads(l) for l in p.read_text().splitlines()]
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest()


def main():
    OUT.mkdir(exist_ok=True)
    for p in SOURCE.glob('*.jsonl'):shutil.copyfile(p,OUT/p.name)
    tasks=read(SOURCE/'bp_train.jsonl');cached={r['id']:r for r in json.loads((ROOT/'new/zero_signal_data_audit_v1/tasks.json').read_text())}
    old={t['id']:t for t in read(ROOT/'examples/social_mixed/data_binary_linear_v3/bp_train.jsonl')}
    checks=[];extra=[]
    for task in tasks:
        if task['task']!='B' or (task['kernel'],task['completion_mode']) not in {('B1','linear'),('B2','linear'),('B2','binary')}:continue
        if len(task['input']['voluntary_history'])!=1 or task['input']['private_results']:continue
        if task['id'] in cached and task['input']==old[task['id']]['input'] and task['teacher']==old[task['id']]['teacher']:
            result=cached[task['id']]
        else:
            result,_=audit_task(task)
        trace=result['trace'][0];q=task['input']['queries'][0]
        table=[];posterior={}
        for name,value in VALUES.items():
            indices=[i for i,w in enumerate(trace['worlds']) if w[q['player']][q['goal']]==value]
            prior=sum(trace['prior'][i] for i in indices)
            mass=sum(trace['prior'][i]*trace['observed_action_likelihood_by_world'][i] for i in indices)
            table.append(dict(preference=name,prior=prior,likelihood=mass/prior if prior else 0.))
            posterior[name]=mass
        total=sum(posterior.values());assert total>0
        posterior={k:v/total for k,v in posterior.items()}
        assert belief(posterior)==task['teacher']['gold']
        # Full-support controls must be in the bridge bank too.
        for stage in ('likelihood','procedure'):
            t=deepcopy(task);t['id']=digest([task['id'],'b-bridge-v6',stage])[:20]
            t['native_task_id']=t['id'];t['b_bridge']=dict(version='b-bridge-v6',stage=stage,parent_id=task['id'],table=table if stage=='likelihood' else [])
            t['semantic_id']=digest([t['input'],t['b_bridge']]);t['periodic_validation']=False
            t['training_ready']=True;t['review_status']='teacher_checked_training_scaffold'
            extra.append(t)
        checks.append(dict(id=task['id'],kernel=task['kernel'],mode=task['completion_mode'],table=table,gold=task['teacher']['gold']))
        print(task['id'],flush=True)
    assert any(len(c['gold']['possible_preferences'])==3 for c in checks)
    from training.social_mixed.b_bridge_requests import request
    for t in extra:assert interface_check(t,request_builder=request)['all_passed']
    train=tasks+extra
    (OUT/'bp_train.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in train))
    (OUT/'requests_train.jsonl').write_text(''.join(json.dumps(dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))))+'\n' for t in train))
    (OUT/'b_bridge_audit.json').write_text(json.dumps(checks,indent=2))
    manifest=json.loads((SOURCE/'manifest.json').read_text())
    manifest.update(dataset_version='reasoning-v6-b-bridges',active=True,parent_manifest_sha256=hashlib.sha256((SOURCE/'manifest.json').read_bytes()).hexdigest())
    rel='training/social_mixed/b_bridge_requests.py';manifest['prompt_sources'][rel]=hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()
    manifest['files']={p.name:dict(count=len(p.read_text().splitlines()),sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in OUT.glob('*.jsonl')}
    manifest['coverage']['bp_train']=dict(Counter(t['kernel'] for t in train));manifest['mode_counts']['bp_train']=dict(Counter(t['completion_mode'] for t in train))
    manifest['b_bridges']=dict(parents=len(checks),added=len(extra),independent_new_structures=0,heldout_unchanged=True)
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(manifest['b_bridges'])

if __name__=='__main__':main()
