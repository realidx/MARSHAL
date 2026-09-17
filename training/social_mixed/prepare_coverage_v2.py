"""Versioned development expansion and frozen structural test; no model selection."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
from training.social_mixed.prepare_distribution_curriculum import ROOT, read, sha, stable, transform, root_episode, SOURCE
from training.social_mixed.structure_coverage import geometry_id, audit

OUT = ROOT/'examples/social_mixed/data_distribution_v2'

def main():
    if OUT.exists():
        raise ValueError('Refusing to overwrite a frozen pack')
    old = ROOT/'examples/social_mixed/data_distribution_v1'
    OUT.mkdir()
    for name in ('bp_train.jsonl','bp_validation.jsonl','selfplay_train.jsonl','selfplay_validation.jsonl','diagnostics.jsonl','p4_links.json','requests_train.jsonl'):
        shutil.copyfile(old/name, OUT/name)
    manifest = json.loads((old/'manifest.json').read_text())
    assignments = {r['id']:r for r in read(ROOT/'examples/social_bp/response_only_v1/kernels_v1/assignments.jsonl')}
    occupied = {geometry_id(t.get('input',t.get('raw'))['game']) for name in ('bp_train','bp_validation','selfplay_train','selfplay_validation') for t in read(OUT/(name+'.jsonl'))}
    rows = read(OUT/'bp_validation.jsonl'); tests=[]; errors=[]; seen=set()
    # One preselected source per kernel and geometry. No model results consulted.
    candidates=[]
    for t in sorted(read(SOURCE), key=lambda t:t['id']):
        if t['split'] not in ('validation','test'):continue
        assignment=assignments.get(t['id'],{})
        kernel=t.get('kernel',assignment.get('kernel'))
        if not kernel or kernel=='A0' or assignment.get('deferred'):continue
        family=geometry_id(t['input']['game'])
        if t['split']=='test' and family in occupied:continue
        key=(t['split'],kernel,family)
        if key in seen:continue
        seen.add(key);candidates.append((t,kernel,family))
    # Freeze candidate IDs before solving; failures stay in the report.
    (OUT/'candidate_freeze.json').write_text(json.dumps([dict(id=t['id'],kernel=k,family=f,split=t['split']) for t,k,f in candidates],indent=2)+'\n')
    with (OUT/'expansion_progress.jsonl').open('w') as log:
        for t,kernel,family in candidates:
            for mode in ('binary','linear','mixed'):
                if t['split']=='validation' and mode=='binary':continue
                x=deepcopy(t)
                x['id']=sha(stable(['coverage-v2',t['id'],mode]).encode())[:20]
                for j,g in enumerate(x['input']['game']['goals']):g['binary']=mode=='binary' or (mode=='mixed' and j%2==0)
                event=dict(source_id=t['id'],kernel=kernel,mode=mode,split=t['split'])
                try:
                    result=transform(x,'balanced',kernel)
                    result.update(structure_family=family, coverage_source_id=t['id'])
                    if result['diagnostic_only']:raise ValueError('All legal actions accepted; excluded from scored core')
                    (tests if t['split']=='test' else rows).append(result)
                    event['status']='ok'
                except Exception as exc:
                    event.update(status='unavailable',error=f'{type(exc).__name__}: {exc}');errors.append(event)
                log.write(json.dumps(event)+'\n');log.flush();print(json.dumps(event),flush=True)
                root_episode.cache_clear()
    for name,data in [('bp_validation.jsonl',rows),('bp_test.jsonl',tests)]:
        (OUT/name).write_text(''.join(json.dumps(t)+'\n' for t in data))
    from training.b_sft.social_named_probe import request
    for split, tasks in [('validation', rows), ('test', tests)]:
        (OUT/('requests_'+split+'.jsonl')).write_text(''.join(json.dumps(dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))))+'\n' for t in tasks))
    manifest['candidate_freeze_sha256']=sha((OUT/'candidate_freeze.json').read_bytes())
    manifest['expansion_source_sha256']=sha(SOURCE.read_bytes())
    manifest['files']={}
    for path in OUT.glob('*.jsonl'):
        manifest['files'][path.name]=dict(count=len(path.read_text().splitlines()),sha256=sha(path.read_bytes()))
    manifest.update(dataset_version='coverage-v2',parent_manifest_sha256=sha((old/'manifest.json').read_bytes()), expansion_errors=errors,
                    evaluation_scope='validation is development; test candidate structures frozen before solver execution, never selected using model outcomes', model_calls=0)
    manifest['prompt_sources']={p:sha((ROOT/p).read_bytes()) for p in manifest['prompt_sources']}
    report=audit(OUT)
    if report['cross_split_families']:raise ValueError('Cross-split geometry detected')
    manifest['counts']={s:dict(__import__('collections').Counter(t['kernel'] for t in read(OUT/('bp_'+s+'.jsonl')))) for s in ('train','validation','test')}
    manifest['coverage']=report['counts']
    (OUT/'structure_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

if __name__=='__main__':main()
