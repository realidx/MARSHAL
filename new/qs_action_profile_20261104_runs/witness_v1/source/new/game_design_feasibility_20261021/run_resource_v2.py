"""Separate smaller-support/longer-budget follow-up; no edits to sweep v1."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import time

import numpy as np
import scipy

from new.game_design_feasibility_20261021.design import generate,BudgetRules,count_public_tree
from new.game_design_feasibility_20261021.run import write,root_metrics
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.equilibrium import certify_policy
from training.strategic_slices.common import save_reference

ROOT=Path(__file__).resolve().parents[2]
OPTIONS=dict(max_nodes=180000,max_node_world_pairs=1700000,solver_seconds=60,
    analysis_seconds=45,max_sweeps=128,max_candidates=6,max_joint_cells=16384,
    max_joint_evaluations=320,large_tree_ordered_sweeps=2)


def configs():
    rows=[]
    for n,a,g,h,menu in [(2,[2,1],2,1,'all'),(2,[2,1],2,2,'all'),
        (2,[2,1],3,2,'all'),(3,[1,1,1],2,1,'hidden-unobserved'),
        (3,[1,1,1],2,2,'hidden-unobserved')]:
        rows.append(dict(players=n,actions=a,goals=g,hidden=h,rounds=2,
            query_limit=1,offer_limit=1,query_targets=menu))
    return rows


def one(job):
    index,config,seed,out=job; start=time.monotonic()
    row=dict(index=index,config=config,seed=seed,status='started')
    phase='generation'; tree=None
    try:
        raw=generate(seed,**{k:config[k] for k in ('players','actions','goals','hidden','rounds')})
        write(out/f'cases/{index}/raw.json',raw)
        rules=BudgetRules(raw,**{k:config[k] for k in ('query_limit','offer_limit','query_targets')})
        row['counts']=count_public_tree(rules)
        if row['counts']['public_histories']>OPTIONS['max_nodes'] or row['counts']['node_world_pairs']>OPTIONS['max_node_world_pairs']:
            row.update(status='resource_preflight_skip',reason='Predeclared resource budget exceeded')
        else:
            phase='construction';t=time.monotonic()
            tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
                world_weights=world_weights(rules.worlds,raw['background_prior']),
                lookahead_rr=3,seconds=60,
                **{k:OPTIONS[k] for k in ('max_nodes','max_sweeps','max_candidates',
                    'max_joint_cells','max_joint_evaluations','large_tree_ordered_sweeps')})
            row['construction_seconds']=time.monotonic()-t
            assert not tree.cutoff_leaves and len(tree.entries)==row['counts']['public_histories']
            phase='solve_and_certify';tree.deadline=time.monotonic()+OPTIONS['solver_seconds'];t=time.monotonic()
            tree.solve();row['solver_seconds']=time.monotonic()-t
            row['certificate']=tree.certificate
            phase='independent_audit';tree.deadline=time.monotonic()+OPTIONS['analysis_seconds']
            checked=certify_policy(tree,epsilon=1e-8)
            if checked is None:raise ValueError('Independent certification failed')
            row['independent_certificate']=checked['certificate'];row['native_audit']=tree.audit_native()
            save_reference(out/f'cases/{index}/reference.npz',tree)
            row['status']='certified'
            phase='root_metrics';row['root_metrics']=root_metrics(tree,OPTIONS['analysis_seconds'])
    except Exception as e:
        row.update(status=('certified_metrics_unavailable' if row.get('status')=='certified'
            else 'unavailable'),phase=phase,reason=f'{type(e).__name__}: {e}')
    row['elapsed_seconds']=time.monotonic()-start
    write(out/f'cases/{index}/result.json',row)
    return row


def main():
    out=Path('new/game_design_feasibility_20261021/sweep_resource_v2')
    out.mkdir(parents=True,exist_ok=False)
    base=Path('new/game_design_feasibility_20261021/sweep_v1/pipeline_snapshot.json')
    previous=json.loads(base.read_text())
    files=list(previous['sources'])+['new/game_design_feasibility_20261021/run_resource_v2.py']
    hashes={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in files}
    for p in hashes:
        dst=out/'source'/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,dst)
    jobs=[(i,c,2026102200+s,out) for i,(c,s) in enumerate((c,s) for c in configs() for s in range(2))]
    snapshot=dict(version='parameterized-native-feasibility-resource-v2',status='launched-not-completed',
        parent='parameterized-native-feasibility-v1',changes=['Hidden support reduced to 1/2 cells',
        '180000 node and 1700000 node-world pair guards','60s solve,45s audit/metrics',
        '128 sweeps,16384 joint cells,320 evaluations; other numerical tolerances unchanged'],
        actual_argv=sys.argv,options=OPTIONS,workers=2,seeds=[2026102200,2026102201],
        configurations=configs(),jobs=len(jobs),sources=hashes,
        parent_run_sha256=sha256(base.read_bytes()).hexdigest(),
        game_contract='Same independent-uniform/no-positive-admission generator and two explicit target-menu variants as v1; full native terminal',
        model_D_prompt_training='Not run or changed; query mechanism diagnostics are not new S or D',
        admission='All specified seeds/configurations retained, no replacement by success',
        environment=dict(python=sys.version,numpy=np.__version__,scipy=scipy.__version__,platform=platform.platform(),
            executable=sys.executable,pythonpath=os.environ.get('PYTHONPATH','NOT_RECORDED'),
            threads={k:os.environ.get(k,'NOT_RECORDED') for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS',
                'MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}))
    write(out/'pipeline_snapshot.json',snapshot)
    rows=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(one,j) for j in jobs]):
            row=f.result();rows.append(row)
            print(json.dumps({k:row.get(k) for k in ('index','status','phase','reason','elapsed_seconds')}),flush=True)
    write(out/'results.json',sorted(rows,key=lambda r:r['index']))
    write(out/'COMPLETE.json',dict(completed=len(rows),expected=len(jobs),
        source_identity_verified=all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items()),
        snapshot_sha256=sha256((out/'pipeline_snapshot.json').read_bytes()).hexdigest()))


if __name__=='__main__':main()
