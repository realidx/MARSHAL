"""Independent three-player BP geometries with three unresolved preferences."""
from copy import copy,deepcopy
from itertools import product
import json
from training.social_mixed.prepare_reasoning_v4 import OUT,ROOT,read,task_at,stable,root_episode
from training.social_mixed.structure_coverage import geometry_id
from training.b_sft.build_bp_pilot import raw_fixture,final_setup
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.preference_contract import profile,belief


def main():
    packs={name:read(OUT/(name+'.jsonl')) for name in ('bp_train','bp_validation','bp_test','selfplay_train','selfplay_validation')}
    for name in ('bp_train','bp_validation'):
        packs[name]=[t for t in packs[name] if not t.get('reasoning_geometry_source')]
    occupied={geometry_id(t.get('input',t.get('raw'))['game']) for ts in packs.values() for t in ts}
    occupied|={geometry_id(t['raw']['game']) for t in read(ROOT/'examples/final_evaluation/benac_a_v1/resets.jsonl')}
    candidates=[]
    for seed in range(2000,5000):
        raw,_=raw_fixture(seed)
        if raw['game']['n_players']!=3 or len(raw['game']['goals'])!=4:continue
        family=geometry_id(raw['game'])
        if family in occupied:continue
        occupied.add(family)
        raw['type_catalogues']['0']=[raw['own_preferences']]
        raw['type_catalogues']['1']=[list(v)+[1] for v in product((1,0,-1),repeat=3)]
        split='train' if len(candidates)<4 else 'validation'
        candidates.append(dict(seed=seed,split=split,raw=raw,family=family))
        if len(candidates)==8:break
    assert len(candidates)==8
    (OUT/'geometry_candidate_freeze.json').write_text(json.dumps(candidates,indent=2))
    log=[]
    for candidate in candidates:
        for mode in ('binary','linear'):
            raw=deepcopy(candidate['raw'])
            for g in raw['game']['goals']:g['binary']=mode=='binary'
            raw,setup=final_setup(raw,1);raw,public,_=expand_support(raw);raw['background_prior']=profile('balanced')
            base=deepcopy(next(t for t in packs['bp_'+candidate['split']] if t['kernel']=='B1' and t['background_profile']=='balanced'))
            base.update(id=f'geometry-v4-{candidate["seed"]}-{mode}',completion_mode=mode,family=candidate['family'],reasoning_geometry_source=candidate['seed'])
            base['input']=dict(public_preferences=public,background_prior=profile('balanced'))
            try:
                root,_=root_episode(stable([raw,setup]));rows=[]
                for action in root.tree.entries[0].actions:
                    a=action.to_dict()
                    if a.get('action')=='INVESTIGATE':continue
                    e=copy(root);e.weights=root.weights.copy()
                    try:e.observe(a);e._weights(0,raw['own_preferences'],[])
                    except ValueError:continue
                    for goal in range(3):
                        previous=belief(root.belief(1,goal,observer=0,own=raw['own_preferences'])['preference_weights'])
                        rows.append(task_at(base,e,setup,[a],[],'B',(1,goal),previous))
                    p=task_at(base,e,setup,[a],[],'P')
                    if p:rows.append(p)
                # At most two complete evidence branches per mode/geometry.
                # Prefer different labels, then stable native event serialization;
                # selection uses teacher semantics only, never model performance.
                branches={}
                for row in rows:branches.setdefault(stable(row['input']['voluntary_history']),[]).append(row)
                chosen=[];covered=set()
                while branches and len(chosen)<2:
                    key=min(branches,key=lambda k:(-len({r['answer_signature'] for r in branches[k]}-covered),k))
                    unit=branches.pop(key);chosen.append(unit);covered|={r['answer_signature'] for r in unit}
                rows=[row for unit in chosen for row in unit]
                packs['bp_'+candidate['split']].extend(rows)
                event=dict(seed=candidate['seed'],split=candidate['split'],mode=mode,tasks=len(rows),status='ok')
            except Exception as exc:event=dict(seed=candidate['seed'],mode=mode,status='unavailable',error=repr(exc))
            log.append(event);print(json.dumps(event),flush=True);root_episode.cache_clear()
    (OUT/'geometry_build.json').write_text(json.dumps(log,indent=2))
    for name in ('bp_train','bp_validation'):
        (OUT/(name+'.jsonl')).write_text(''.join(json.dumps(t)+'\n' for t in packs[name]))

if __name__=='__main__':main()
