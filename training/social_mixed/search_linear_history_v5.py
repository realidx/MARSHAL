"""Linear-only native teacher search; exports additions without modifying v4."""
from copy import copy,deepcopy
from itertools import product
import json
from training.social_mixed.prepare_reasoning_v4 import *
from training.b_sft.build_bp_pilot import raw_fixture
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.preference_contract import profile


def main():
    from training.social_mixed.prepare_reasoning_v5 import OUT as DEST
    DEST.mkdir(exist_ok=True)
    packs={s:[t for t in read(OUT/('bp_'+s+'.jsonl')) if not t.get('decision_search_source')] for s in ('train','validation')};owners={}
    for split in ('train','validation','test'):
        for t in read(OUT/('bp_'+split+'.jsonl')):owners[geometry_id(t['input']['game'])]=split
    for split in packs:
        for t in read(OUT/('selfplay_'+split+'.jsonl')):owners[geometry_id(t['raw']['game'])]=split
    protected={geometry_id(t['raw']['game']) for t in read(ROOT/'examples/final_evaluation/benac_a_v1/resets.jsonl')}
    candidates=[]
    for seed in range(3000,3100):
        raw,_=raw_fixture(seed)
        if raw['game']['n_players']!=2 or len(raw['game']['goals'])<3:continue
        family=geometry_id(raw['game']);split=owners.get(family,'validation' if int(family[:2],16)%3==0 else 'train')
        if family in protected or split=='test':continue
        owners[family]=split;candidates.append(dict(seed=seed,raw=raw,split=split,family=family))
        if len(candidates)==32:break
    (DEST/'linear_history_search_freeze.json').write_text(json.dumps(candidates,indent=2));log=[];additions={s:[] for s in packs}
    for candidate in candidates:
        raw=deepcopy(candidate['raw']);g=len(raw['game']['goals']);raw['type_catalogues']['0']=[raw['own_preferences']]
        raw['type_catalogues']['1']=[list(v)+[1] for v in product((1,0,-1),repeat=g-1)]
        raw['game']['round_robin']=[1,0]
        for goal in raw['game']['goals']:goal['binary']=False
        raw,public,_=expand_support(raw);raw['background_prior']=profile('balanced')
        split=candidate['split'];base=deepcopy(next(t for t in packs[split] if t['kernel']=='B1' and t['background_profile']=='balanced'))
        base.update(id='linear-history-v5-'+str(candidate['seed']),family=candidate['family'],completion_mode='linear',decision_search_source=candidate['seed'])
        base['input']=dict(public_preferences=public,background_prior=profile('balanced'))
        found=[];linked={}
        try:
            root,_=root_episode(stable([raw,[]]));front=[(root,[])]
            for depth in range(4):
                nxt=[]
                for node,events in front:
                    entry=node.tree.entries[node.index]
                    if entry.actor is None:continue
                    if entry.actor==0:
                        p=task_at(base,node,[],events,[],'P')
                        if p and p['teacher']['history_changes_acceptable']:
                            def change(goal):
                                before=root.belief(1,goal,observer=0,own=raw['own_preferences'])['preference_weights']
                                after=node.belief(1,goal,observer=0,own=raw['own_preferences'])['preference_weights']
                                return sum(abs(after[k]-before[k]) for k in before)
                            goal=max(range(g-1),key=change)
                            b=task_at(base,node,[],events,[],'B',(1,goal))
                            p['linked_b_id']=b['id'];linked[p['id']]=b;found.append(p)
                    for a in entry.actions:
                        if a.to_dict().get('action')=='INVESTIGATE':continue
                        child=copy(node)
                        try:child.observe(a.to_dict());child._weights(0,raw['own_preferences'],[])
                        except ValueError:continue
                        nxt.append((child,events+[a.to_dict()]))
                front=nxt
            found=sorted(found,key=lambda t:t['id'])[:2]
            additions[split].extend(found+[linked[p['id']] for p in found]);event=dict(seed=candidate['seed'],split=split,found=len(found),status='ok')
        except Exception as exc:event=dict(seed=candidate['seed'],split=split,status='unavailable',error=repr(exc))
        log.append(event);print(json.dumps(event),flush=True);root_episode.cache_clear()
    for split,rows in additions.items():(DEST/('linear_history_'+split+'.jsonl')).write_text(''.join(json.dumps(t)+'\n' for t in rows))
    (DEST/'linear_history_search_audit.json').write_text(json.dumps(log,indent=2))

if __name__=='__main__':main()
