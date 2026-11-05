"""Mine reachable evidence/action-switch pairs without assuming hidden truth is observed."""
import argparse
from collections import deque, defaultdict
from copy import deepcopy
import json
from pathlib import Path
import time

from training.social_mixed.frozen.training.b_sft.structure_audit import Fixture, digest, TOL
from training.social_mixed.frozen.benac_p.endgame_diagnose import decode_action
from training.social_mixed.frozen.benac_p.endgame import SearchLimit
from training.social_mixed.frozen.benac_p.endgame_partner import InformationStateRequired


def decision_key(node):
    public=node.state.public_state().copy()
    public.pop('transcript',None)
    return digest(dict(public=public,pending=None if node.pending is None else node.pending.to_dict()))


def disjoint(left,right):
    if left['actions'] != right['actions']:return False
    return not set(left['optimal_actions']) & set(right['optimal_actions'])


def mine_fixture(raw,max_nodes=3000,max_decisions=64,depth=2):
    start=time.monotonic()
    result=dict(id=raw['id'],witness=None,unmatched_state_example=None,visited=0,
                status='complete',limitations='Same physical state and own goals; differing observable histories. Does not prove natural-language B is causally used by a model.')
    try:
        if any(not g.get('binary',True) for g in raw['game']['goals']):
            raise ValueError('Linear fixture unsupported')
        f=Fixture(raw,max_nodes)
        queue=deque([(f.root,raw.get('history',[]),0)])
        seen=set();groups=defaultdict(list);all_rows=[]
        while queue:
            if result['visited']>=max_decisions:
                result['status']='decision_budget';break
            node,history,d=queue.popleft()
            full=digest(history)
            if full in seen:continue
            seen.add(full)
            if node.state.is_terminal:continue
            result['visited']+=1
            q=f.search.q_values(node);best=max(v for _,v in q)
            row=dict(history=history,support=f.support(node),physical_key=decision_key(node),
                     actions=[a.to_dict() for a,_ in q],q=[v for _,v in q],
                     optimal_actions=[i for i,(_,v) in enumerate(q) if best-v<=TOL])
            # Replay every exported observation from the original prior, not a
            # manually restricted singleton-world node.
            replay=f.search.replay([decode_action(a) for a in history])
            if decision_key(replay)!=row['physical_key'] or f.support(replay)!=row['support']:
                raise ValueError('Independent replay mismatch')
            for old in groups[row['physical_key']]:
                if old['support']!=row['support'] and disjoint(old,row):
                    result['witness']=dict(left=old,right=row,fixture=raw)
                    result['status']='found';break
            if result['witness']:break
            for old in all_rows:
                if result['unmatched_state_example'] is None and old['support']!=row['support'] and disjoint(old,row):
                    result['unmatched_state_example']=dict(left=old,right=row,
                        warning='Physical state differs: cannot isolate evidence; not an accepted witness.')
            groups[row['physical_key']].append(row);all_rows.append(row)
            if d<depth:
                for action,_ in q:
                    for b in f.window_step(node,action):
                        if not b.node.state.is_terminal:
                            queue.append((b.node,history+[action.to_dict()]+[e['action'] for e in b.evidence],d+1))
        result['searched_depth']=depth
    except (SearchLimit,InformationStateRequired,ValueError) as exc:
        result.update(status='unavailable',reason=f'{type(exc).__name__}: {exc}')
    result['seconds']=round(time.monotonic()-start,3)
    return result


def verify_witness(witness,max_nodes=3000):
    """Independently recompute both observations and Q tables before acceptance."""
    rows=[]
    for side in ('left','right'):
        expected=witness[side]
        raw=deepcopy(witness['fixture']);raw['history']=expected['history']
        f=Fixture(raw,max_nodes);q=f.search.q_values(f.root);best=max(v for _,v in q)
        row=dict(history=raw['history'],physical_key=decision_key(f.root),support=f.support(f.root),
                 actions=[a.to_dict() for a,_ in q],q=[v for _,v in q],
                 optimal_actions=[i for i,(_,v) in enumerate(q) if best-v<=TOL])
        for key in ('physical_key','support','actions','optimal_actions'):
            if row[key]!=expected[key]:raise ValueError('Witness mismatch: '+key)
        if len(row['q'])!=len(expected['q']) or any(abs(a-b)>TOL for a,b in zip(row['q'],expected['q'])):
            raise ValueError('Witness mismatch: Q values')
        rows.append(row)
    if rows[0]['physical_key']!=rows[1]['physical_key'] or rows[0]['support']==rows[1]['support'] or not disjoint(*rows):
        raise ValueError('Not a matched-state evidence/action-switch witness')
    return True


def constructed(seed):
    """Small native rule structure; random preferences are hypotheses, not certificates."""
    import random
    rng=random.Random(seed)
    subsets=[[(0,0),(1,0)],[(0,0),(2,0)],[(1,0),(2,0)],[(0,0),(1,0),(2,0)]]
    goals=[dict(goal_id=i,binary=True,required_actions=[dict(player_id=p,action_id=a) for p,a in xs]) for i,xs in enumerate(subsets)]
    rows=[[rng.choice([-1,0,1]) for _ in goals] for p in range(3)]
    for row in rows:
        if 1 not in row:row[rng.randrange(4)]=1
    target=1;query=rng.choice([0,2,3])
    # Ensure every candidate type retains a positive goal.
    if not any(v==1 for i,v in enumerate(rows[target]) if i!=query):rows[target][(query+1)%4]=1
    types={str(p):[row] for p,row in enumerate(rows)}
    types[str(target)]=[row[:query]+[v]+row[query+1:] for v in [1,0,-1] for row in [rows[target]]]
    return dict(id=f'constructed-switch-{seed}',ego=0,
        game=dict(n_players=3,n_actions_per_player=[1,1,1],goals=goals,
                  round_robin=[0,1,2,2,1,0],max_changes=1,menu_enabled=True),
        own_preferences=rows[0],type_catalogues=types,query=dict(player=target,goals=[query]),
        history=[],source=dict(seed=seed,generator='evidence_switch.constructed',scope='Development construction, not a held-out sample'))


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--corpus',type=Path,nargs='*',default=[])
    p.add_argument('--constructed-seeds',type=int,default=0)
    p.add_argument('--seed',type=int,default=93000)
    p.add_argument('--max-nodes',type=int,default=3000)
    p.add_argument('--max-decisions',type=int,default=64)
    p.add_argument('--depth',type=int,default=2)
    p.add_argument('--output-dir',type=Path,required=True)
    args=p.parse_args(argv)
    if args.output_dir.exists():p.error('Use a new output directory')
    if min(args.max_nodes,args.max_decisions)<1 or min(args.depth,args.constructed_seeds)<0:p.error('Invalid budgets')
    args.output_dir.mkdir(parents=True)
    raws=[]
    for corpus in args.corpus:
        for line in (corpus/'certificates.jsonl').read_text().splitlines():
            c=json.loads(line)
            # Inspected test/OOD sources remain held out; never mine train seeds from them.
            if c['split'] in ('development','train'):raws.append(c['fixture'])
    raws += [constructed(s) for s in range(args.seed,args.seed+args.constructed_seeds)]
    results=[]
    with (args.output_dir/'attempts.jsonl').open('w') as out:
        for raw in raws:
            r=mine_fixture(raw,args.max_nodes,args.max_decisions,args.depth)
            results.append(r);out.write(json.dumps(r,ensure_ascii=False)+'\n');out.flush()
            print(json.dumps({k:r[k] for k in ('id','status','visited','seconds')}),flush=True)
            if r['witness']:
                verify_witness(r['witness'],args.max_nodes)
                fixtures=[]
                for side in ('left','right'):
                    item=deepcopy(raw);item['id']+='-'+side
                    item['history']=r['witness'][side]['history'];fixtures.append(item)
                (args.output_dir/'fixtures.json').write_text(json.dumps(dict(fixtures=fixtures),indent=2)+'\n')
                (args.output_dir/'witness.json').write_text(json.dumps(r['witness'],ensure_ascii=False,indent=2)+'\n')
                break
    summary=dict(attempts=len(results),found=any(r['witness'] for r in results),
                 statuses={s:sum(r['status']==s for r in results) for s in sorted({r['status'] for r in results})},
                 total_seconds=sum(r['seconds'] for r in results),training_ready=False,
                 note='A negative bounded search is not a proof of impossibility. Construction changes only native goals/preferences, not partner policy or legality.')
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')


if __name__=='__main__':main()
