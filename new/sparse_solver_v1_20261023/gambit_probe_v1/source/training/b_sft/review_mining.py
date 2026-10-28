"""Bounded supplementary search for evidence/action switches without local tie flags."""
from collections import deque,defaultdict
from copy import deepcopy
import json
from pathlib import Path
import time

from training.b_sft.social_rollout import build,queries_for
from training.b_sft.dataset_review import belief,timeline,conservative_b_masks
from training.b_sft.evidence_switch import decision_key
from training.b_sft.structure_audit import digest,TOL


def mine(raw,budget=1500,decisions=64,depth=3,seconds=8):
    start=time.monotonic();result=dict(id=raw['id'],visited=0,status='complete',witness=None,tie_sensitive_pairs=0)
    try:
        s,node,types,_=build(raw,budget);queries=queries_for(types,s.ego)
        queue=deque([(node,raw.get('history',[]),0)]) if s.actor(node)==s.ego else deque(
            (b.node,raw.get('history',[])+[e['action'] for e in b.evidence],0) for b in s.advance(node))
        seen=set();groups=defaultdict(list)
        while queue:
            if result['visited']>=decisions or time.monotonic()-start>seconds:
                result['status']='budget';break
            node,history,d=queue.popleft();key=digest(history)
            if key in seen or node.state.is_terminal:continue
            seen.add(key);result['visited']+=1
            q=s.q_values(node);best=max(v for _,v in q)
            row=dict(history=history,B=belief(node,types,s.ego),actions=[a.to_dict() for a,_ in q],
                     q=[v for _,v in q],optimal_actions=[i for i,(_,v) in enumerate(q) if best-v<=TOL])
            for old in groups[decision_key(node)]:
                if old['B']==row['B'] or old['actions']!=row['actions'] or set(old['optimal_actions'])&set(row['optimal_actions']):continue
                for item in (old,row):
                    if 'B_masks' not in item:item['B_masks']=conservative_b_masks(timeline(dict(raw,history=item['history']),budget),queries)
                if not all(m['set_mask'] and m['favored_mask'] for item in (old,row) for m in item['B_masks']):
                    result['tie_sensitive_pairs']+=1;continue
                result.update(status='found',witness=dict(fixture=raw,left=old,right=row,
                    scope='Matched physical state, fixed own goal/prior, different public histories and disjoint best actions. No local tie-sensitive B update found; not robustness to arbitrary partner strategies.'))
                break
            if result['witness']:break
            groups[decision_key(node)].append(row)
            if d<depth:
                for a,_ in q:
                    for b in s.step(node,a):
                        if not b.node.state.is_terminal:queue.append((b.node,history+[a.to_dict()]+[e['action'] for e in b.evidence],d+1))
    except (RuntimeError,ValueError) as exc:result.update(status='unavailable',reason=str(exc))
    result['seconds']=round(time.monotonic()-start,3)
    return result


def run(out,seed=110000,seeds=36,seconds=90):
    from training.b_sft.coverage_batch import make_game
    if out.exists():raise ValueError('Use a new output directory')
    out.mkdir(parents=True);start=time.monotonic();results=[]
    with (out/'attempts.jsonl').open('w') as f:
        for i in range(seeds):
            if time.monotonic()-start>seconds:break
            try:
                raw,_=make_game(seed+i,3,1,4,'single' if i%2==0 else 'multi_partner')
                r=mine(raw,seconds=min(8,seconds-(time.monotonic()-start)))
            except (RuntimeError,ValueError) as exc:r=dict(id=str(seed+i),status='invalid_configuration',reason=str(exc))
            results.append(r);f.write(json.dumps(r)+'\n');f.flush()
            print(json.dumps({k:v for k,v in r.items() if k!='witness'}),flush=True)
            if r.get('witness'):
                (out/'witness.json').write_text(json.dumps(r['witness'],indent=2)+'\n');break
    (out/'summary.json').write_text(json.dumps(dict(attempts=len(results),found=any(r.get('witness') for r in results),
        statuses={s:sum(r['status']==s for r in results) for s in {r['status'] for r in results}},seconds=time.monotonic()-start,
        limits='Budgets checked at seed/node boundaries; this is not a hard timeout. Bounded non-hit is not absence.',training_ready=False),indent=2)+'\n')


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--seed',type=int,default=110000)
    p.add_argument('--seeds',type=int,default=36);p.add_argument('--seconds',type=float,default=90);a=p.parse_args()
    if min(a.seeds,a.seconds)<=0:p.error('Positive budgets required')
    run(a.output_dir,a.seed,a.seeds,a.seconds)
