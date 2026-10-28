"""Frozen100 structural audit + predeclared26 bounded-reference CPU probe."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from functools import lru_cache
import hashlib
import inspect
from itertools import product
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np
import scipy

from new.decision_window_v1_20261022.window import DecisionWindow, VERSION, decision_horizon
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.common import save_reference
from training.strategic_slices.equilibrium import certify_policy, solve_equilibrium
from training.strategic_slices.freeze import source_identity

ROOT=Path(__file__).resolve().parents[2]
OPTIONS=dict(max_nodes=100000,max_sweeps=128,max_candidates=6,
             max_joint_cells=16384,max_joint_evaluations=320,
             large_tree_ordered_sweeps=2,epsilon=1e-8)
DATA_SHA='30fb0f7d012f33f5d175650258698e9ba46cd88cafc64da39f848a69c4bfd3ad'


def write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def opening_size(rules, cutoff):
    """Count histories with physical-state caching, never merge solver infosets."""
    n=rules.spec.n_players
    masks=tuple((1<<a)-1 for a in rules.spec.n_actions_per_player)
    hidden=[sum(len({r[g] for r in rules.catalogues[p]})>1
                for g in range(len(rules.spec.goals))) for p in range(n)]

    @lru_cache(None)
    def count(turn, committed, queries, offers):
        if turn==cutoff:return 1
        actor=rules.spec.round_robin[turn]
        nodes=1+count(turn+1,committed,queries,offers)
        if queries[actor]<rules.query_limit:
            q=list(queries);q[actor]+=1
            targets=max(0,sum(hidden)-hidden[actor]-queries[actor])
            nodes+=targets*count(turn+1,committed,tuple(q),offers)
        if offers[actor]<rules.offer_limit:
            o=list(offers);o[actor]+=1;o=tuple(o)
            reject=count(turn+1,committed,queries,o)
            for partner in range(n):
                if partner==actor:continue
                available=[]
                for p in (actor,partner):
                    remaining=masks[p]^committed[p]
                    available.append([0]+[1<<a for a in range(rules.spec.n_actions_per_player[p])
                                          if remaining&(1<<a)])
                for own,other in product(*available):
                    if own==other==0:continue
                    changed=list(committed);changed[actor]|=own;changed[partner]|=other
                    nodes+=1+reject+count(turn+1,tuple(changed),queries,o)
        return nodes
    return count(0,(0,)*n,(0,)*n,(0,)*n)


def root_values(tree):
    """Own contingent BR to ONE selected other-player profile, cutoff utility.

    This is a bounded root-Q diagnostic, not new S, model D, selection, or a
    claim about full-game Q. Query/nonquery gaps are pre-answer acquisition
    comparisons, never the contribution of an already available answer.
    """
    focal=tree.entries[0].actor
    updates,_=tree.response(focal)
    policy=[None if p is None else p.copy() for p in tree.policy]
    for index,probs in updates.items():policy[index]=probs
    values=tree.evaluate(policy)
    actions=tree.entries[0].actions
    query=[i for i,a in enumerate(actions) if a.to_dict()['action']=='INVESTIGATE']
    ordinary=[i for i in range(len(actions)) if i not in query]
    output=[]
    for ids in tree.groups[focal]:
        weights=tree.world_weights[ids];weights=weights/weights.sum()
        q=[float(weights@values[c][ids,focal]) for c in tree.entries[0].children]
        maximum=max(q)
        output.append(dict(own_type=list(tree.worlds[ids[0]][focal]),
            prior_mass=float(tree.world_weights[ids].sum()),Q=q,
            own_optimal_actions=[i for i,v in enumerate(q) if maximum-v<=1e-8],
            best_investigate_minus_best_nonquery=(max(q[i] for i in query)-max(q[i] for i in ordinary)
                                                 if query else None)))
    return dict(actions=[a.to_dict() for a in actions],private_contexts=output,
                meaning='Fixed selected opponents; own complete contingent best response within this window only')


def worker(parent, output, budgets):
    start=time.monotonic();phase='construct';tree=None
    result=dict(index=parent['index'],parent_id=parent['id'],configuration=parent['configuration'],
                status='started',version=VERSION)
    try:
        rules=StrategicRules(parent['raw'])
        tree=DecisionWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),
            seconds=budgets['construct_seconds'],**OPTIONS)
        result.update(construction_seconds=time.monotonic()-start,nodes=len(tree.entries),
                      cutoff_leaves=len(tree.cutoff_leaves),horizon=tree.horizon)
        assert len(tree.entries)==opening_size(rules,tree.cutoff)
        phase='solve';t=time.monotonic();tree.deadline=t+budgets['solve_seconds']
        tree.solve();result['solve_seconds']=time.monotonic()-t
        phase='independent_audit';t=time.monotonic();tree.deadline=t+budgets['audit_seconds']
        checked=certify_policy(tree,epsilon=OPTIONS['epsilon'])
        if checked is None:raise ValueError('Independent bounded-game certification failed')
        native=tree.audit_native();result['audit_seconds']=time.monotonic()-t
        phase='bounded_root_Q';tree.deadline=time.monotonic()+budgets['audit_seconds']
        q=root_values(tree)
        result.update(status='certified_bounded',certificate=tree.certificate,
                      independent_certificate=checked['certificate'],native_audit=native,
                      bounded_root_Q=q)
        path=output/'cases'/parent['id']/'reference.npz'
        path.parent.mkdir(parents=True,exist_ok=True);save_reference(path,tree)
        result.update(reference=str(path.relative_to(output)),reference_sha256=sha(path))
    except Exception as exc:
        result.update(status='unavailable',failed_phase=phase,
                      reason=f'{type(exc).__name__}: {exc}',oracle_label=None)
        if tree is not None:
            result['last_equilibrium_audit']=getattr(tree,'equilibrium_audit',None)
    result['elapsed_seconds']=time.monotonic()-start
    write(output/'cases'/parent['id']/'result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--solve-seconds',type=float,default=20)
    args=parser.parse_args()
    if args.workers<1 or args.solve_seconds<=0:parser.error('Positive budgets required')
    output=args.output.resolve();output.mkdir(parents=True,exist_ok=False)
    pool=ROOT/'new/strategic_game_v1_20261021/parents_100_v1/parents.jsonl'
    assert sha(pool)==DATA_SHA
    parents=list(map(json.loads,pool.read_text().splitlines()))
    strata=defaultdict(list)
    for p in parents:strata[json.dumps(p['configuration'],sort_keys=True)].append(p)
    initial12={p['index'] for group in strata.values() for p in group[:2]}
    missing=json.loads((ROOT/'new/remote_solver_results_20261022/SUMMARY.json').read_text())['unavailable_indices']
    indices=sorted(initial12|set(missing))
    chosen=[p for p in parents if p['index'] in indices]
    budgets=dict(construct_seconds=20,solve_seconds=args.solve_seconds,audit_seconds=30)
    sources=source_identity()
    for directory in ('new/decision_window_v1_20261022','new/strategic_game_v1_20261021',
                      'new/game_design_feasibility_20261021'):
        for path in (ROOT/directory).glob('*.py'):sources[str(path.relative_to(ROOT))]=sha(path)
    for rel in sources:
        path=output/'source'/rel;path.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/rel,path)
    defaults={name:{k:p.default for k,p in inspect.signature(fn).parameters.items()
                    if p.default is not inspect.Parameter.empty}
              for name,fn in [('solver',solve_equilibrium)]}
    snapshot=dict(version=VERSION,created_on='2026-10-22',kind='CPU_RESEARCH_PROBE',
        actual_argv=sys.argv,parents_sha256=DATA_SHA,
        source_hashes=sources,resolved_config=dict(options=OPTIONS,budgets=budgets,
            workers=args.workers,initialization='uniform',search_backend='unchanged original repository solver',
            horizon='entrance anchored through next focal proposal and full response; earlier native terminal',
            leaf_score='current binding commitment utility; no continuation',
            acceptance='complete bounded tree private-information BR, local support and response social ties',
            selection='first two frozen indices per original stratum union remote15 failures; fixed before outcomes',
            solve_indices=indices,structural_indices=list(range(100)),solver_defaults=defaults),
        environment=dict(python=sys.version,executable=sys.executable,numpy=np.__version__,
            scipy=scipy.__version__,platform=platform.platform(),
            threads={k:os.environ.get(k,'NOT_RECORDED') for k in
                     ['OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS']}),
        model='NOT_USED',prompt='NOT_USED',training_reward_advantage='NOT_APPLICABLE',
        Q='bounded root-Q diagnostics only',S='NOT_IMPLEMENTED',D='NOT_MEASURED',
        production_active='terminal-node-regret-grpo-readable-v8',production_changed=False,
        reuse='native transition/payoff/info-set/search/audit code reused; no old reference imported',
        comparison='Different horizon and local20s budget; not a causal timing comparison to historical remote runs')
    write(output/'pipeline_snapshot.json',snapshot)
    structure=[]
    for parent in parents:
        rules=StrategicRules(parent['raw']);h=decision_horizon(rules,rules.initial())
        nodes=opening_size(rules,h['cutoff'])
        full=opening_size(rules,len(rules.spec.round_robin))
        assert full==parent['preflight']['public_histories']
        structure.append(dict(index=parent['index'],configuration=parent['configuration'],
            full_nodes=full,window_nodes=nodes,node_ratio=nodes/full,horizon=h))
    write(output/'structure_100.json',structure)
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(worker,p,output,budgets) for p in chosen]
        for future in as_completed(futures):
            row=future.result();results.append(row)
            write(output/'progress.json',dict(completed=len(results),expected=len(chosen),
                counts=dict(Counter(r['status'] for r in results))))
            print(json.dumps({k:row.get(k) for k in ['index','status','nodes','reason','elapsed_seconds']}),flush=True)
    results.sort(key=lambda r:r['index']);write(output/'results.json',results)
    identity=all(sha(ROOT/rel)==expected for rel,expected in sources.items())
    write(output/'COMPLETE.json',dict(attempted=len(results),expected=len(chosen),
        counts=dict(Counter(r['status'] for r in results)),source_identity_verified=identity,
        membership_unchanged=sha(pool)==DATA_SHA,snapshot_sha256=sha(output/'pipeline_snapshot.json'),
        new_S_D_or_training=False))
    if not identity:raise RuntimeError('Sources changed during run')


if __name__=='__main__':main()
