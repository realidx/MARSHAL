"""Resource-only retry of missing quota profiles; retain all failed attempts."""
import argparse
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

from new.offer_quota_original_pool_20261021.full_pool_v1 import metrics
from new.offer_budget_mechanism_20261021.research import OfferQuotaRules, audit_quota
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import save_reference
from training.strategic_slices.pipeline_versions import registered_snapshot

ROOT=Path(__file__).resolve().parents[2]
VERSION='original-100-offer-quota-resource-retry-v3'


def digest(p):
    return sha256(p.read_bytes()).hexdigest()


def write(p,value):
    with p.open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2)
        f.write('\n')


def retry(job):
    parent,source_string,out_string,seconds,evaluations=job
    source,out=Path(source_string),Path(out_string)
    pid,raw=parent['id'],parent['raw']
    base=source/f'{pid}_baseline.json'
    if not base.exists():
        earlier=json.loads((source/f'{pid}_status.json').read_text())
        base=Path(earlier['baseline_source'])
    status=dict(parent_id=pid,split=parent['split'],players=parent['players'],binding=True,
                retry_of=str(source/f'{pid}_status.json'),baseline_source=str(base),baseline_sha256=digest(base))
    start=time.monotonic();phase='quota_solve'
    try:
        rules=OfferQuotaRules(raw,1)
        tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,raw['background_prior']),
            lookahead_rr=len(rules.spec.round_robin),max_nodes=160000,seconds=seconds,
            max_joint_evaluations=evaluations,max_candidates=12,max_joint_cells=8192,
            max_sweeps=256,large_tree_ordered_sweeps=8).solve()
        assert not tree.cutoff_leaves
        phase='quota_audit';tree.deadline=time.monotonic()+180
        audit=tree.audit_native();quota_audit=audit_quota(tree)
        phase='quota_metrics'
        measured=metrics(tree,180)
        save_reference(out/f'{pid}_quota_reference.npz',tree)
        measured.update(status='new-full-terminal-certified-quota-profile',certificate=tree.certificate,
            native_audit=audit,quota_audit=quota_audit,nodes=len(tree.entries),
            reference_sha256=digest(out/f'{pid}_quota_reference.npz'))
        write(out/f'{pid}_quota.json',measured)
        baseline=json.loads(base.read_text())
        shutil.copyfile(base,out/base.name)
        status.update(status='complete-resolved',quota='resource-retry-certified-full-terminal-profile',
            baseline_summary=baseline['summary'],quota_summary=measured['summary'],
            baseline_payoffs=baseline['ex_ante_payoffs'],quota_payoffs=measured['ex_ante_payoffs'],
            baseline_nodes=baseline['nodes'],quota_nodes=len(tree.entries))
    except Exception as exc:
        status.update(status='missing-result',failed_phase=phase,reason=f'{type(exc).__name__}: {exc}',oracle_label=None)
    status['seconds']=time.monotonic()-start
    write(out/f'{pid}_status.json',status)
    return status


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=2)
    p.add_argument('--solver-seconds',type=float,default=300)
    p.add_argument('--max-joint-evaluations',type=int,default=1280)
    args=p.parse_args()
    source=args.source_run
    assert (source/'COMPLETE.json').exists()
    args.output.mkdir(parents=True,exist_ok=False)
    registered=registered_snapshot('terminal-node-regret-grpo-readable-v8','terminal-readable-named-v2')
    summary=json.loads((source/'summary.json').read_text())
    missing=[r for r in summary['results'] if r['status']=='missing-result']
    assert all(r['failed_phase']=='quota_solve' for r in missing), 'Do not reinterpret other failures as solver failures'
    original=source
    while not (original/'parents.json').exists():
        original=Path(json.loads((original/'pipeline_snapshot.json').read_text())['parent_run'])
    parents={p['id']:p for p in json.loads((original/'parents.json').read_text())}
    write(args.output/'pipeline_snapshot.json',dict(version=VERSION,status='launched-not-completed',
        parent_run=str(source),actual_argv=sys.argv,
        actual_options={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        active_training=registered,
        resolved_config=dict(parent_game_config='exactly source run',offer_limit=1,
            solver_seconds=args.solver_seconds,max_joint_evaluations=args.max_joint_evaluations,
            analysis_seconds=180,epsilon=1e-8,max_nodes=160000,max_candidates=12,max_joint_cells=8192,
            max_sweeps=256,large_tree_ordered_sweeps=8,initialization='uniform',
            parent_ids=[r['parent_id'] for r in missing],
            baseline='reuse validated original baseline bytes with source hash',
            change='Increase existing wall/sweep/candidate/history-cell/nonlinear evaluation budgets; algorithm/physical game/objective/tolerance unchanged',
            failure='missing label, never zero information value'),
        input_hashes={str(p):digest(p) for p in [source/n for n in ('pipeline_snapshot.json','summary.json','COMPLETE.json')]+[original/'parents.json']},
        source_manifest={str(p.relative_to(ROOT)):digest(p) for p in (
            Path(__file__),ROOT/'new/offer_quota_original_pool_20261021/full_pool_v1.py',
            ROOT/'new/offer_budget_mechanism_20261021/research.py',ROOT/'training/strategic_slices/bounded.py',
            ROOT/'training/strategic_slices/equilibrium.py')},
        model_identity='none',reward_advantage_training='not applicable',
        runtime=dict(python=sys.version,numpy=np.__version__,platform=platform.platform(),
            environment={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}),
        gpu_used=False,production_changed=False))
    src=args.output/'source';src.mkdir();shutil.copyfile(__file__,src/Path(__file__).name)
    results=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        jobs=[(parents[r['parent_id']],str(source),str(args.output),args.solver_seconds,args.max_joint_evaluations) for r in missing]
        futures=[executor.submit(retry,j) for j in jobs]
        for f in as_completed(futures):
            r=f.result();results.append(r)
            print(json.dumps(r,ensure_ascii=False),flush=True)
    write(args.output/'summary.json',dict(version=VERSION,status='completed-all-retries',
        results=results,attempted=len(results),certified=sum(r['status']=='complete-resolved' for r in results),
        failure_imputation=False,production_changed=False))
    write(args.output/'COMPLETE.json',dict(pipeline_snapshot_sha256=digest(args.output/'pipeline_snapshot.json'),
        summary_sha256=digest(args.output/'summary.json')))


if __name__=='__main__':
    main()
