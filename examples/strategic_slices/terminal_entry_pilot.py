"""Small terminal-only entrance-generation pilot; no training or corpus replacement."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from collections import Counter
import numpy as np
from training.b_sft.preference_contract import world_weights
from training.b_sft.social_private_teacher import PrivateInvestigationRules, observed_slots
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.bounded_data import public_entrances
from training.strategic_slices.build import measure_entrance
from training.strategic_slices.common import digest,replay_node,save_reference,write_json
from training.strategic_slices.diagnose_bounded import count_bounded_nodes,root_entrances

CONFIG=dict(max_k=3,min_c=.1,min_increment=.05,min_s=.05)

def entrance_features(rules, raw, node):
    actor=rules.actor(node)
    commitments=node.state.snapshot_commitments()
    future=list(rules.spec.round_robin[node.state.turn_index:])
    observed=set(observed_slots(node,actor))
    groups={}
    for world in rules.worlds:
        key=(world[actor],tuple(world[p][g] for p,g in sorted(observed)))
        groups.setdefault(key,[]).append(world)
    informative=False
    for action in rules.actions(node):
        a=action.to_dict()
        if a.get('action')=='INVESTIGATE':
            informative |= any(len({w[a['player']][a['goal']] for w in worlds})>1 for worlds in groups.values())
    unresolved=sum(any(not commitments[a['player_id']][a['action_id']] for a in g['required_actions'])
                   for g in raw['game']['goals'])
    free=sum(not bit for row in commitments for bit in row)
    return dict(repeated_focal_proposal=future.count(actor)>=2,
        potential_later_response=any(p!=actor for p in future[1:]),
        informative_query_available=bool(informative),query_budget_available=not bool(node.state.investigation_used[actor]),
        unresolved_goals=unresolved,uncommitted_bits=free,
        commitment_stratum='none' if free==sum(map(len,commitments)) else ('complete' if not free else 'partial'))

def sampled_roots(rules,seed):
    roots={tuple(h):(n,'uniform') for h,n in public_entrances(rules,seed,12,1000)}
    # Add paths that preserve choices more often, without conditioning on a world.
    rng=np.random.default_rng(seed+10000)
    for _ in range(12):
        node=rules.initial();history=[]
        while rules.actor(node) is not None:
            actions=rules.actions(node)
            idle=[i for i,a in enumerate(actions) if a.to_dict().get('action')=='PASS' or a.to_dict().get('response')=='REJECT']
            ai=int(rng.choice(idle)) if idle and rng.random()<.65 else int(rng.integers(len(actions)))
            node=rules._apply(node,actions[ai]);history.append(ai)
            if rules.actor(node) is not None:roots.setdefault(tuple(history),(node,'pass-reject-biased'))
    return [(h,n,origin) for h,(n,origin) in roots.items()]

def generate(source, fresh=False):
    if fresh:
        from training.strategic_slices.build import sample_parent
        chosen=[]
        for i in range(8):
            seed=2026100400+i;players=2 if i<4 else 3
            raw=sample_parent(seed,players,rounds=3)
            chosen.append(dict(id=digest(raw)[:24],players=players,raw=raw,
                origin=dict(kind='fresh-native-random',generator_seed=seed,private_support='unchanged')))
    else:
        parents=[json.loads(x) for x in (source/'train_parents.jsonl').read_text().splitlines()]
        chosen=[]
        for kind,n in [('source-derived-information-acquisition',2),('random',2),('random',3)]:
            eligible=[p for p in parents if p['players']==n and (p['origin']['kind']=='source-derived-information-acquisition')==(kind!='random')]
            chosen.extend(sorted(eligible,key=lambda p:p['id'])[:2])
    cases=[];screen=[]
    for pi,parent in enumerate(chosen):
        rules=PrivateInvestigationRules(parent['raw']);total=len(rules.spec.round_robin)
        roots=sampled_roots(rules,20261004+pi)
        pool=[]
        for history,node,sampling in roots:
            remaining=total-node.state.turn_index
            if node.pending is not None or remaining not in (1,2,3):continue
            count=count_bounded_nodes(rules,node,total)['unfolded_public_history_nodes']
            item=dict(parent_id=parent['id'],history=list(history),remaining=remaining,nodes=count,
                **entrance_features(rules,parent['raw'],node),sampling=sampling,players=parent['players'],origin=parent['origin'])
            screen.append(item)
            if count<=15000:pool.append(item)
        # One seeded representative per structural stratum; tree size is only a budget gate.
        for remaining in (3,2,1):
            eligible=[r for r in pool if r['remaining']==remaining]
            strata={}
            for item in eligible:
                key=(item['commitment_stratum'],item['query_budget_available'],item['informative_query_available'],item['repeated_focal_proposal'],item['potential_later_response'],item['unresolved_goals']>0)
                strata.setdefault(key,[]).append(item)
            ordered=sorted(strata,key=lambda key:(not(key[2] and (key[3] or key[4]) and key[5]),not key[5],digest((parent['id'],remaining,key))))
            for key in ordered[:3]:
                item=min(strata[key],key=lambda r:digest((20261004,r['history'])))
                cases.append(dict(item,raw=parent['raw'],name=f'entry_{len(cases)}'))
        if parent['origin']['kind']=='source-derived-information-acquisition':
            for history in parent['raw'].get('slice_setup_histories',[]):
                node=replay_node(rules,history)
                count=count_bounded_nodes(rules,node,total)['unfolded_public_history_nodes']
                if count<=15000:
                    duplicate=next((c for c in cases if c['parent_id']==parent['id'] and c['history']==history),None)
                    if duplicate is not None:
                        duplicate['also_prescribed_control']=True
                        continue
                    cases.append(dict(parent_id=parent['id'],history=history,remaining=total-node.state.turn_index,
                        nodes=count,players=parent['players'],origin=parent['origin'],
                        sampling='prescribed-mechanism-control',raw=parent['raw'],name=f'control_{pi}'))
    return cases,screen

def worker(out,i):
    c=json.loads((out/'cases.json').read_text())[i];start=time.monotonic()
    rules=PrivateInvestigationRules(c['raw']);node=replay_node(rules,c['history'])
    tree=BoundedPrivateWindow(rules,node,rules.worlds,world_weights=world_weights(rules.worlds,c['raw']['background_prior']),lookahead_rr=len(rules.spec.round_robin),max_nodes=15000,seconds=6).solve()
    solved=time.monotonic();audit=tree.audit_native()
    assert all(e.node.state.is_terminal for e in tree.entries if e.actor is None)
    assert len(tree.entries)==c['nodes']
    rows=[];curves=[]
    for entrance in root_entrances(tree):
        entrance.update(history=c['history'],absolute_cutoff=tree.cutoff,entrance_policy='world-independent-public-prefix-v1')
        measured,curve=measure_entrance(tree,entrance,c['parent_id'],CONFIG)
        rows.extend(measured);curves.append(dict(entrance=entrance,curve=curve))
    save_reference(out/f'reference_{i}.npz',tree)
    write_json(out/f'result_{i}.json',dict(status='certified',case={k:v for k,v in c.items() if k!='raw'},
        solve_seconds=solved-start,total_seconds=time.monotonic()-start,certificate=tree.certificate,audit=audit,slices=rows,curves=curves))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--source',type=Path,default=Path('new/local_data/strategic_slices_production_v4'));p.add_argument('--worker',type=int)
    p.add_argument('--fresh',action='store_true',help='Eight new random three-round parents; no private-support reduction or oracle preselection')
    p.add_argument('--behavior-information',action='store_true',help='Opt into versioned query + future public-history S screening')
    args=p.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    if args.behavior_information:CONFIG['measure_public_behavior']=True
    if args.worker is not None:worker(out,args.worker);return
    start=time.monotonic();cases,screen=generate(args.source,args.fresh)
    write_json(out/'cases.json',cases);write_json(out/'screening.json',screen)
    def launch(i):
        with (out/f'worker_{i}.log').open('w') as log:
            try:
                command=[sys.executable,__file__,'--output',str(out),'--worker',str(i)]
                if args.behavior_information:command.append('--behavior-information')
                result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,timeout=20,env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'))
                status='failed' if result.returncode else 'certified'
            except subprocess.TimeoutExpired:status='timeout'
        if status=='certified':return json.loads((out/f'result_{i}.json').read_text())
        if status=='failed' and 'SearchLimit: Shared teacher wall budget exceeded' in (out/f'worker_{i}.log').read_text():
            status='solver_time_budget'
        if status=='failed' and 'SearchLimit: Joint mixed equilibrium search did not pass complete deviation/tie checks' in (out/f'worker_{i}.log').read_text():
            status='uncertified_reference'
        return dict(status=status,case={k:v for k,v in cases[i].items() if k!='raw'},oracle_label=None,log=f'worker_{i}.log')
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(launch,range(len(cases))))
    rows=[s for r in results if r['status']=='certified' for s in r['slices']]
    summary=dict(scope=('Eight fresh random parents with original private support; small deterministic seed batch, not training-ready data.' if args.fresh else 'Convenience pilot on six already selected train parents; not random-parent yield or training-ready data.')+' Structural query/future-turn flags are proxies, not proof of intuitive strategic completeness.',
        config=CONFIG,screened=len(screen),over_node_budget=sum(r['nodes']>15000 for r in screen),attempted=len(cases),statuses=dict(Counter(r['status'] for r in results)),
        retained_slices=len(rows),positive_S=sum(s['information_positive'] for s in rows),seconds=time.monotonic()-start,results=results)
    write_json(out/'summary.json',summary)
    print({k:v for k,v in summary.items() if k!='results'})
    for r in results:print(r['case']['name'],r['case']['players'],r['case']['origin'],r['status'],len(r.get('slices',[])),sum(s['information_positive'] for s in r.get('slices',[])))

if __name__=='__main__':main()
