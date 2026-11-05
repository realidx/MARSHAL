"""Source-matched terminal certification probe on frozen raw parents.

Membership is independent of solver outcomes. No Q/S/D, prompt or model calls.
"""
from collections import defaultdict,Counter
from concurrent.futures import ProcessPoolExecutor,as_completed
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

from new.strategic_game_v1_20261021.rules import StrategicRules,VERSION
from new.strategic_game_v1_20261021.pool import write,stable,ROOT
from new.game_design_feasibility_20261021.design import count_public_tree
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import save_reference
from training.strategic_slices.equilibrium import certify_policy,solve_equilibrium
from training.strategic_slices.freeze import source_identity

OPTIONS=dict(max_nodes=100000,max_sweeps=128,max_candidates=6,max_joint_cells=16384,
    max_joint_evaluations=320,large_tree_ordered_sweeps=2,epsilon=1e-8)


def worker(job):
    parent,out=job;pid=parent['id'];start=time.monotonic();phase='construct'
    result=dict(parent_id=pid,index=parent['index'],configuration=parent['configuration'],
        seed=parent['seed'],status='started')
    try:
        rules=StrategicRules(parent['raw']);counts=count_public_tree(rules)
        assert counts==parent['preflight']
        result['preflight']=counts
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),
            lookahead_rr=3,seconds=60,**OPTIONS)
        assert len(tree.entries)==counts['public_histories'] and not tree.cutoff_leaves
        assert all(e.node.state.is_terminal for e in tree.entries if e.actor is None)
        result['construction_seconds']=time.monotonic()-start
        phase='solve';t=time.monotonic();tree.deadline=t+90
        tree.solve();result['solver_seconds']=time.monotonic()-t
        phase='independent_audit';tree.deadline=time.monotonic()+60
        checked=certify_policy(tree,epsilon=OPTIONS['epsilon'])
        if checked is None:raise ValueError('Independent terminal deviation/support audit failed')
        native=tree.audit_native()
        reference=out/'cases'/pid/'reference.npz';reference.parent.mkdir(parents=True,exist_ok=True)
        save_reference(reference,tree)
        result.update(status='certified',certificate=tree.certificate,
            independent_certificate=checked['certificate'],native_audit=native,
            reference_sha256=sha256(reference.read_bytes()).hexdigest(),
            reference_file=str(reference.relative_to(out)))
    except Exception as e:
        result.update(status='unavailable',failed_phase=phase,reason=f'{type(e).__name__}: {e}',
            oracle_label=None)
    result['elapsed_seconds']=time.monotonic()-start
    write(out/'cases'/pid/'result.json',result)
    return result


def main():
    pool=Path('new/strategic_game_v1_20261021/parents_100_v1')
    out=Path('new/strategic_game_v1_20261021/probe_12_v1')
    out.mkdir(parents=True,exist_ok=False)
    parents=[json.loads(line) for line in (pool/'parents.jsonl').read_text().splitlines()]
    cells=defaultdict(list)
    for parent in parents:cells[stable(parent['configuration'])].append(parent)
    chosen=[p for key in sorted(cells) for p in cells[key][:2]]
    assert len(chosen)==12
    sources=source_identity()
    for rel in ['new/game_design_feasibility_20261021/design.py',
                'new/strategic_game_v1_20261021/rules.py',
                'new/strategic_game_v1_20261021/pool.py',
                'new/strategic_game_v1_20261021/probe.py',
                'new/strategic_game_v1_20261021/test_rules.py']:
        sources[rel]=sha256((ROOT/rel).read_bytes()).hexdigest()
    for rel in sources:
        dst=out/'source'/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dst)
    defaults={label:{k:v.default for k,v in inspect.signature(fn).parameters.items()
        if v.default is not inspect.Parameter.empty} for label,fn in
        [('tree',BoundedPrivateWindow.__init__),('solver',solve_equilibrium)]}
    snapshot=dict(version='strategic-parents-100-certification-probe-v1',status='launched-not-completed',
        parent='strategic-parents-100-two-round-unknown-query-v1',game_version=VERSION,
        actual_argv=sys.argv,parents_file=str(pool/'parents.jsonl'),
        parents_sha256=sha256((pool/'parents.jsonl').read_bytes()).hexdigest(),
        chosen_ids=[p['id'] for p in chosen],
        selection='First two frozen indices in each of six predeclared configuration strata; no metric-based selection',
        resolved_config=dict(options=OPTIONS,lookahead_rr=3,workers=3,
            construction_seconds=60,solver_seconds=90,independent_audit_seconds=60,
            all_leaves_native_terminal=True,unchanged_defaults=defaults),
        source_hashes=sources,
        sampling_reward_advantage='Not applicable: exact terminal strategy certification only, no rollouts/training',
        model='NOT_USED',prompt='NOT_USED',Q_S_D='NOT_COMPUTED',production_changed=False,
        environment=dict(python=sys.version,executable=sys.executable,numpy=np.__version__,
            scipy=scipy.__version__,platform=platform.platform(),
            pythonpath=os.environ.get('PYTHONPATH','NOT_RECORDED'),threads={k:os.environ.get(k,'NOT_RECORDED')
            for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}))
    write(out/'pipeline_snapshot.json',snapshot)
    results=[]
    with ProcessPoolExecutor(max_workers=3) as executor:
        futures=[executor.submit(worker,(parent,out)) for parent in chosen]
        for future in as_completed(futures):
            result=future.result();results.append(result)
            print(json.dumps({k:result.get(k) for k in ('index','status','failed_phase','reason','elapsed_seconds')}),flush=True)
    results.sort(key=lambda row:row['index'])
    write(out/'results.json',results)
    write(out/'COMPLETE.json',dict(attempted=len(results),expected=len(chosen),
        outcomes=dict(Counter(r['status'] for r in results)),
        source_identity_verified=all(sha256((ROOT/rel).read_bytes()).hexdigest()==h for rel,h in sources.items()),
        snapshot_sha256=sha256((out/'pipeline_snapshot.json').read_bytes()).hexdigest(),
        parent_membership_unchanged=sha256((pool/'parents.jsonl').read_bytes()).hexdigest()==snapshot['parents_sha256']))


if __name__=='__main__':main()
