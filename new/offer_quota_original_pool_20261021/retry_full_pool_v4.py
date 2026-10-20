"""Declared seeded-initialization fallback for the remaining uncertified game.

This changes numerical initialization, not the game or the acceptance test.
Seeds are tried in fixed order; stop at the first independently certified
profile, before computing its information metrics. All attempts are retained.
"""
import argparse
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
VERSION='original-100-offer-quota-seeded-search-v4'


def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,value):
    with p.open('x') as f:
        json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--solver-seconds',type=float,default=150)
    args=parser.parse_args()
    source,out=args.source_run,args.output
    assert (source/'COMPLETE.json').exists()
    out.mkdir(parents=True,exist_ok=False)
    source_summary=json.loads((source/'summary.json').read_text())
    missing=[r for r in source_summary['results'] if r['status']=='missing-result']
    original=source
    while not (original/'parents.json').exists():
        original=Path(json.loads((original/'pipeline_snapshot.json').read_text())['parent_run'])
    parents={p['id']:p for p in json.loads((original/'parents.json').read_text())}
    active=registered_snapshot('terminal-node-regret-grpo-readable-v8','terminal-readable-named-v2')
    seeds=(0,1,2)
    config=dict(parent_ids=[r['parent_id'] for r in missing],seeds=list(seeds),
        initialization='At each public node and each actor-information cell, draw Dirichlet(1,...,1) action probabilities using np.random.default_rng(seed); repeat identical probabilities across indistinguishable worlds',
        selection='First profile passing the same full-terminal certification, independent of measured Q/query value; later seeds skipped',
        offer_limit=1,solver_seconds=args.solver_seconds,analysis_seconds=180,
        epsilon=1e-8,max_nodes=160000,max_joint_evaluations=640,max_candidates=12,
        max_joint_cells=8192,max_sweeps=256,large_tree_ordered_sweeps=8,
        physical_game='identical to source run; no prior/utility/query/action/response-tie change',
        baseline='reuse original independently verified baseline bytes, preserving identity')
    write(out/'pipeline_snapshot.json',dict(version=VERSION,status='launched-not-completed',parent_run=str(source),
        actual_argv=sys.argv,actual_options={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
        active_training=active,resolved_config=config,
        inputs={str(source/n):digest(source/n) for n in ('pipeline_snapshot.json','summary.json','COMPLETE.json')},
        source_manifest={str(p.relative_to(ROOT)):digest(p) for p in (
            Path(__file__),ROOT/'new/offer_quota_original_pool_20261021/full_pool_v1.py',
            ROOT/'new/offer_budget_mechanism_20261021/research.py',ROOT/'training/strategic_slices/bounded.py',
            ROOT/'training/strategic_slices/equilibrium.py')},
        model_identity='none',reward_advantage_training='not applicable',
        runtime=dict(python=sys.version,numpy=np.__version__,platform=platform.platform(),
            environment={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}),
        production_changed=False,gpu_used=False))
    shutil.copyfile(__file__,out/Path(__file__).name)
    results=[]
    for old in missing:
        pid=old['parent_id'];raw=parents[pid]['raw'];base=Path(old['baseline_source'])
        status=dict(parent_id=pid,split=old['split'],players=old['players'],binding=True,
            baseline_source=str(base),baseline_sha256=digest(base),retry_of=str(source/f'{pid}_status.json'))
        attempts=[];start=time.monotonic()
        for seed in seeds:
            seed_dir=out/f'{pid}_seed_{seed}';seed_dir.mkdir()
            write(seed_dir/'pipeline_snapshot.json',dict(parent_snapshot=str(out/'pipeline_snapshot.json'),
                parent_sha256=digest(out/'pipeline_snapshot.json'),resolved_config=dict(config,actual_seed=seed)))
            tree=None;phase='quota_solve';attempt_start=time.monotonic()
            try:
                rules=OfferQuotaRules(raw,1)
                tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
                    world_weights=world_weights(rules.worlds,raw['background_prior']),
                    lookahead_rr=len(rules.spec.round_robin),max_nodes=160000,seconds=args.solver_seconds,
                    max_joint_evaluations=640,max_candidates=12,max_joint_cells=8192,
                    max_sweeps=256,large_tree_ordered_sweeps=8)
                rng=np.random.default_rng(seed)
                for i,entry in enumerate(tree.entries):
                    if entry.actor is None:continue
                    p=np.zeros_like(tree.policy[i])
                    for ids in tree.information_groups[i]:
                        probabilities=rng.dirichlet(np.ones(len(entry.actions)))
                        p[:,ids]=probabilities[:,None]
                    tree.policy[i]=p
                tree.initialization=f'public-dirichlet-infoset-seed-{seed}'
                tree.solve()
                assert not tree.cutoff_leaves
                # Certification is already complete here. No information
                # metric is consulted to choose this seed/profile.
                attempt=dict(seed=seed,status='certified-before-information-measurement',
                    certificate=tree.certificate,seconds=time.monotonic()-attempt_start)
                write(seed_dir/'certified.json',attempt)
                attempts.append(attempt)
                phase='quota_audit';tree.deadline=time.monotonic()+180
                native=tree.audit_native();bookkeeping=audit_quota(tree)
                phase='quota_metrics';measured=metrics(tree,180)
                save_reference(out/f'{pid}_quota_reference.npz',tree)
                measured.update(status='new-full-terminal-certified-quota-profile',certificate=tree.certificate,
                    native_audit=native,quota_audit=bookkeeping,nodes=len(tree.entries),
                    reference_sha256=digest(out/f'{pid}_quota_reference.npz'))
                write(out/f'{pid}_quota.json',measured)
                shutil.copyfile(base,out/base.name)
                baseline=json.loads(base.read_text())
                status.update(status='complete-resolved',selected_seed=seed,
                    quota='first-certified-declared-seeded-initialization',baseline_summary=baseline['summary'],
                    quota_summary=measured['summary'],baseline_payoffs=baseline['ex_ante_payoffs'],
                    quota_payoffs=measured['ex_ante_payoffs'],baseline_nodes=baseline['nodes'],quota_nodes=len(tree.entries))
                break
            except Exception as exc:
                failure=dict(seed=seed,status='missing-result',failed_phase=phase,
                    reason=f'{type(exc).__name__}: {exc}',oracle_label=None,
                    seconds=time.monotonic()-attempt_start)
                if tree is not None:
                    failure['last_equilibrium_audit']=getattr(tree,'equilibrium_audit',None)
                attempts.append(failure);write(seed_dir/'failed.json',failure)
                print(json.dumps(dict(parent=pid,seed=seed,status='failed',reason=failure['reason'])),flush=True)
                if phase!='quota_solve':raise
        if 'status' not in status:
            status.update(status='missing-result',failed_phase='quota_solve',reason=attempts[-1]['reason'],oracle_label=None)
        status.update(seconds=time.monotonic()-start,initialization_attempts=attempts)
        write(out/f'{pid}_status.json',status);results.append(status)
        print(json.dumps(dict(parent=pid,status=status['status'],seed=status.get('selected_seed'),seconds=status['seconds'])),flush=True)
    write(out/'summary.json',dict(version=VERSION,status='completed-all-declared-seed-attempts',
        results=results,attempted=len(results),certified=sum(r['status']=='complete-resolved' for r in results),
        production_changed=False))
    write(out/'COMPLETE.json',dict(pipeline_snapshot_sha256=digest(out/'pipeline_snapshot.json'),summary_sha256=digest(out/'summary.json')))


if __name__=='__main__':main()
