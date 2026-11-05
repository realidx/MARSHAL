"""Predeclared feasibility sweep; failures retained, no model calls or new S/D."""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import inspect
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np
import scipy

from new.game_design_feasibility_20261021.design import generate, BudgetRules, count_public_tree, VERSION
from new.offer_budget_mechanism_20261021.research import contingent_values
from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_terminal_teacher import Investigate
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import save_reference
from training.strategic_slices.equilibrium import solve_equilibrium, certify_policy

ROOT=Path(__file__).resolve().parents[2]


def write(path,obj):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2); f.write('\n')


def cases():
    """All target-rule changes are separate games, never solver pruning."""
    configurations=[]
    for players,actions,goals in [(2,[2,1],2),(2,[2,1],3),(2,[2,2],3),
                                 (3,[1,1,1],2),(3,[1,1,1],3),(3,[2,1,1],3)]:
        for rounds,query,offer in [(2,1,1),(2,1,2),(3,1,1),(3,2,1)]:
            for targets in ['all','hidden-unobserved']:
                configurations.append(dict(players=players,actions=actions,goals=goals,
                    rounds=rounds,hidden=3,query_limit=query,offer_limit=offer,
                    query_targets=targets))
    # More hidden cells: value/probability support cost tested separately.
    configurations.append(dict(players=2,actions=[2,1],goals=3,rounds=2,hidden=4,
        query_limit=1,offer_limit=1,query_targets='all'))
    configurations.append(dict(players=2,actions=[2,1],goals=3,rounds=2,hidden=2,
        query_limit=1,offer_limit=1,query_targets='all'))
    return configurations


def root_metrics(tree,seconds):
    """Terminal root action values; query prohibition is NOT the new S."""
    ego=tree.entries[0].actor
    tree.deadline=time.monotonic()+seconds
    full=contingent_values(tree,ego)
    blocked=contingent_values(tree,ego,forbid_queries=True)
    rows=[]; entry=tree.entries[0]
    query=[a for a,x in enumerate(entry.actions) if isinstance(x,Investigate)]
    ordinary=[a for a in range(len(entry.actions)) if a not in query]
    offers=[a for a,x in enumerate(entry.actions) if x.to_dict().get('action')=='OFFER']
    for ids in tree.information_groups[0]:
        mass=float(tree.world_weights[ids].sum())
        weight=tree.world_weights[ids]/mass
        q=np.array([weight@full[c][ids,ego] for c in entry.children])
        noq=np.array([weight@blocked[c][ids,ego] for c in entry.children])
        qbest=float(q[query].max()) if query else None
        rows.append(dict(own=list(tree.worlds[int(ids[0])][ego]),prior_mass=mass,
            Q=q.tolist(),Q_span=float(q.max()-q.min()),
            query_gap=None if qbest is None else qbest-float(q[ordinary].max()),
            query_access=float(q.max()-noq[ordinary].max()),
            mean_offer_regret=float(np.mean(q.max()-q[offers])) if offers else None))
    return dict(actor=ego,actions=[a.to_dict() for a in entry.actions],cells=rows,
        root_strict_query_mass=sum(r['prior_mass'] for r in rows if r['query_gap'] is not None and r['query_gap']>1e-8),
        root_query_inferior_mass=sum(r['prior_mass'] for r in rows if r['query_gap'] is not None and r['query_gap'] < -1e-8),
        root_mean_Q_span=sum(r['prior_mass']*r['Q_span'] for r in rows),
        root_query_access=sum(r['prior_mass']*r['query_access'] for r in rows),
        scope='Initial proposal only; root cells weighted by prior. This is not current-node omission S or model D.')


def solve(job):
    index,config,seed,options,out=job
    start=time.monotonic(); result=dict(index=index,config=config,seed=seed,status='started')
    phase='generation'
    try:
        structure={k:config[k] for k in ('players','actions','goals','rounds','hidden')}
        raw=generate(seed,**structure)
        rules=BudgetRules(raw,**{k:config[k] for k in ('query_limit','offer_limit','query_targets')})
        counts=count_public_tree(rules); result.update(counts=counts)
        write(out/f'cases/{index}/raw.json',raw)
        if counts['public_histories']>options['max_nodes'] or counts['node_world_pairs']>options['max_node_world_pairs']:
            result.update(status='resource_preflight_skip',reason='Predeclared full-tree resource budget exceeded; no oracle label')
        else:
            phase='construction'; t=time.monotonic()
            tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
                world_weights=world_weights(rules.worlds,raw['background_prior']),
                lookahead_rr=config['rounds']+1,seconds=options['solver_seconds'],
                max_nodes=options['max_nodes'],max_sweeps=64,max_candidates=6,
                max_joint_cells=4096,max_joint_evaluations=160,large_tree_ordered_sweeps=2)
            result['construction_seconds']=time.monotonic()-t
            assert not tree.cutoff_leaves and len(tree.entries)==counts['public_histories']
            phase='solve_and_certify'; t=time.monotonic()
            tree.deadline=time.monotonic()+options['solver_seconds']
            tree.solve(); result['solver_seconds']=time.monotonic()-t
            result['certificate']=tree.certificate
            phase='independent_audit'; tree.deadline=time.monotonic()+options['analysis_seconds']
            result['independent_certificate']=certify_policy(tree,epsilon=1e-8)['certificate']
            result['native_audit']=tree.audit_native()
            write(out/f'cases/{index}/certificate.json',result['certificate'])
            save_reference(out/f'cases/{index}/reference.npz',tree)
            result['status']='certified'
            phase='root_metrics'
            result['root_metrics']=root_metrics(tree,options['analysis_seconds'])
    except Exception as e:
        result.update(status=('certified_metrics_unavailable' if result.get('certificate') else 'unavailable'),
            phase=phase,reason=f'{type(e).__name__}: {e}')
    result['elapsed_seconds']=time.monotonic()-start
    write(out/f'cases/{index}/result.json',result)
    return result


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--seeds',type=int,default=2)
    parser.add_argument('--max-nodes',type=int,default=30000)
    parser.add_argument('--max-node-world-pairs',type=int,default=900000)
    parser.add_argument('--solver-seconds',type=float,default=20)
    parser.add_argument('--analysis-seconds',type=float,default=30)
    args=parser.parse_args(); args.output.mkdir(parents=True,exist_ok=False)
    options={k:v for k,v in vars(args).items() if k!='output'}
    configs=cases()
    jobs=[(i,config,2026102200+s,options,args.output)
          for i,(config,s) in enumerate((c,s) for c in configs for s in range(args.seeds))]
    source_paths=['new/game_design_feasibility_20261021/design.py',
        'new/game_design_feasibility_20261021/run.py',
        'new/game_design_feasibility_20261021/test_design.py',
        'new/offer_budget_mechanism_20261021/research.py',
        'training/b_sft/social_private_teacher.py','training/b_sft/shared_teacher.py',
        'training/b_sft/social_terminal_teacher.py','training/b_sft/decision_policy.py',
        'training/b_sft/preference_contract.py','training/strategic_slices/bounded.py',
        'training/strategic_slices/equilibrium.py','training/strategic_slices/common.py',
        'third_party/negotiation_benchmark/src/benac_p/state.py',
        'third_party/negotiation_benchmark/src/benac_p/endgame.py',
        'third_party/negotiation_benchmark/src/benac_p/schema.py']
    hashes={}
    for rel in source_paths:
        hashes[rel]=sha256((ROOT/rel).read_bytes()).hexdigest()
        dest=args.output/'source'/rel; dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/rel,dest)
    defaults={name:{k:v.default for k,v in inspect.signature(fn).parameters.items()
                       if v.default is not inspect.Parameter.empty}
              for name,fn in [('tree',BoundedPrivateWindow.__init__),('solver',solve_equilibrium)]}
    snapshot=dict(version=VERSION,status='launched-not-completed',actual_argv=sys.argv,
        options=options,configurations=configs,seeds=[2026102200+s for s in range(args.seeds)],
        jobs=len(jobs),sources=hashes,unchanged_solver_defaults=defaults,
        changes=['Configurable integer investigation and immediate nonrefundable offer budgets',
            'Independent uniform preference support without positive-goal/all-neutral-goal admission filters',
            'Goal requirements may include two commitments from one player',
            'Explicit separate-game all vs hidden-unobserved investigation target menus'],
        rule_warning='Removing known/redundant query actions changes the game and signaling possibilities; not claimed equilibrium-preserving pruning.',
        selection='Every predeclared configuration/seed recorded; skips and failures retained. No Q/S/D-based acceptance or seed replacement.',
        terminal='Native terminal only, no nonterminal cutoff allowed',
        solver='Existing complete-tree general-sum candidate search and independent deviation/local response-tie audit; no global convergence or uniqueness guarantee',
        sampling='No model calls or rollout sampling; root diagnostics use full support and exact expectations',
        reward_advantage_training='Not applicable; no training, prompt or production default changes',
        S_D='Not computed; root query access and query-vs-nonquery are auxiliary mechanism diagnostics, not new S or D',
        environment=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,
            executable=sys.executable,platform=platform.platform(),
            threads={key:os.environ.get(key,'NOT_RECORDED') for key in
                ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')},
            pythonpath=os.environ.get('PYTHONPATH','NOT_RECORDED')))
    write(args.output/'pipeline_snapshot.json',snapshot)
    rows=[]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(solve,job) for job in jobs]
        for f in as_completed(futures):
            row=f.result(); rows.append(row)
            print(json.dumps({k:row.get(k) for k in ('index','status','phase','elapsed_seconds','reason')},ensure_ascii=False),flush=True)
    rows.sort(key=lambda r:r['index'])
    write(args.output/'results.json',rows)
    write(args.output/'COMPLETE.json',dict(completed=len(rows),expected=len(jobs),
        source_identity_verified=all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items()),
        snapshot_sha256=sha256((args.output/'pipeline_snapshot.json').read_bytes()).hexdigest()))


if __name__=='__main__':
    main()
