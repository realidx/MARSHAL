"""Use old certified policy as numerical initialization for a new quota game.

Every quota history is a legal old history. Project the old behavioral profile
onto the retained action menu, then run the unchanged all-player full-terminal
solver and independent checks. Old Q/payoffs are never used as new labels.
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
from training.strategic_slices.terminal_candidates import restore_reference

ROOT=Path(__file__).resolve().parents[2]
VERSION='original-100-offer-quota-projected-initialization-v5'


def digest(p):return sha256(p.read_bytes()).hexdigest()
def write(p,value):
    with p.open('x') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')
def key(action):return json.dumps(action.to_dict(),sort_keys=True,separators=(',',':'))


def project(base,new):
    assert base.worlds==new.worlds
    stack=[(0,0)];nodes=zero_columns=removed=0
    while stack:
        bi,ni=stack.pop();b,n=base.entries[bi],new.entries[ni]
        assert b.actor==n.actor and b.node.pending==n.node.pending
        assert b.node.state.turn_index==n.node.state.turn_index
        assert b.node.state.snapshot_commitments()==n.node.state.snapshot_commitments()
        nodes+=1
        if n.actor is None:continue
        assert all(np.array_equal(x,y) for x,y in zip(base.information_groups[bi],new.information_groups[ni]))
        indices={key(a):i for i,a in enumerate(b.actions)}
        take=[indices[key(a)] for a in n.actions]
        p=base.policy[bi][take].copy();mass=p.sum(axis=0)
        zero=mass==0;p[:,~zero]/=mass[~zero];p[:,zero]=1/len(n.actions)
        new.policy[ni]=p;zero_columns+=int(zero.sum());removed+=len(b.actions)-len(n.actions)
        for a,child in enumerate(n.children):stack.append((b.children[take[a]],child))
    assert nodes==len(new.entries)
    return dict(mapped_nodes=nodes,removed_action_rows=removed,zero_mass_world_columns_uniformized=zero_columns,
                history_matching='recursive action-identity map; actor/pending/turn/commitments/private-information cells checked')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source-run',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--solver-seconds',type=float,default=240)
    args=p.parse_args();source,out=args.source_run,args.output
    assert (source/'COMPLETE.json').exists();out.mkdir(parents=True,exist_ok=False)
    missing=[r for r in json.loads((source/'summary.json').read_text())['results'] if r['status']=='missing-result']
    original=source
    while not (original/'parents.json').exists():original=Path(json.loads((original/'pipeline_snapshot.json').read_text())['parent_run'])
    parents={p['id']:p for p in json.loads((original/'parents.json').read_text())}
    pool=ROOT/'new/local_data/strategic_slices_oracle_consistent_candidates_v4'
    refs={r['parent_id']:r for r in map(json.loads,(pool/'references.jsonl').read_text().splitlines())}
    active=registered_snapshot('terminal-node-regret-grpo-readable-v8','terminal-readable-named-v2')
    config=dict(parent_ids=[r['parent_id'] for r in missing],offer_limit=1,
        initialization='project exact original saved behavioral profile onto each new legal action menu; renormalize, uniform if retained probability mass is zero',
        baseline_use='numerical starting point only; all players re-optimize and independent certification required; no old Q labels',
        solver_seconds=args.solver_seconds,analysis_seconds=180,epsilon=1e-8,max_nodes=160000,
        max_joint_evaluations=1280,max_candidates=12,max_joint_cells=8192,max_sweeps=256,large_tree_ordered_sweeps=8,
        physical_game='unchanged from quota study')
    write(out/'pipeline_snapshot.json',dict(version=VERSION,status='launched-not-completed',parent_run=str(source),
        actual_argv=sys.argv,resolved_config=config,active_training=active,
        inputs={str(p):digest(p) for p in [source/n for n in ('pipeline_snapshot.json','summary.json','COMPLETE.json')]+[pool/'parents.jsonl',pool/'references.jsonl']},
        source_manifest={str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__),ROOT/'new/offer_quota_original_pool_20261021/full_pool_v1.py',ROOT/'new/offer_budget_mechanism_20261021/research.py',ROOT/'training/strategic_slices/bounded.py',ROOT/'training/strategic_slices/equilibrium.py')},
        model_identity='none',reward_advantage_training='not applicable',
        runtime=dict(python=sys.version,numpy=np.__version__,platform=platform.platform(),environment={k:os.environ.get(k) for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','VECLIB_MAXIMUM_THREADS','NUMEXPR_NUM_THREADS')}),
        production_changed=False,gpu_used=False))
    shutil.copyfile(__file__,out/Path(__file__).name);results=[]
    for old in missing:
        pid=old['parent_id'];raw=parents[pid]['raw'];base_path=Path(old['baseline_source']);ref=refs[pid]
        start=time.monotonic();phase='projected_initialization'
        status=dict(parent_id=pid,split=old['split'],players=old['players'],binding=True,baseline_source=str(base_path),baseline_sha256=digest(base_path),retry_of=str(source/f'{pid}_status.json'))
        tree=None
        try:
            baseline=restore_reference(raw,ref,pool/ref['file'])
            rules=OfferQuotaRules(raw,1)
            tree=BoundedPrivateWindow(rules,rules.initial(),rules.worlds,
                world_weights=world_weights(rules.worlds,raw['background_prior']),lookahead_rr=len(rules.spec.round_robin),
                max_nodes=160000,seconds=args.solver_seconds,max_joint_evaluations=1280,max_candidates=12,
                max_joint_cells=8192,max_sweeps=256,large_tree_ordered_sweeps=8)
            projection=project(baseline,tree)
            write(out/f'{pid}_projection.json',projection)
            tree.initialization='projected-original-profile-'+ref['sha256']
            del baseline
            phase='quota_solve';tree.solve()
            assert not tree.cutoff_leaves
            phase='quota_audit';tree.deadline=time.monotonic()+180
            audit=tree.audit_native();bookkeeping=audit_quota(tree)
            phase='quota_metrics';m=metrics(tree,180)
            save_reference(out/f'{pid}_quota_reference.npz',tree)
            m.update(status='new-full-terminal-certified-quota-profile',certificate=tree.certificate,
                native_audit=audit,quota_audit=bookkeeping,nodes=len(tree.entries),initialization_projection=projection,
                reference_sha256=digest(out/f'{pid}_quota_reference.npz'))
            write(out/f'{pid}_quota.json',m);shutil.copyfile(base_path,out/base_path.name)
            b=json.loads(base_path.read_text())
            status.update(status='complete-resolved',quota='certified-after-projected-original-profile-initialization',
                baseline_summary=b['summary'],quota_summary=m['summary'],baseline_payoffs=b['ex_ante_payoffs'],
                quota_payoffs=m['ex_ante_payoffs'],baseline_nodes=b['nodes'],quota_nodes=len(tree.entries))
        except Exception as exc:
            status.update(status='missing-result',failed_phase=phase,reason=f'{type(exc).__name__}: {exc}',oracle_label=None,
                last_equilibrium_audit=None if tree is None else getattr(tree,'equilibrium_audit',None))
        status['seconds']=time.monotonic()-start;write(out/f'{pid}_status.json',status);results.append(status)
        print(json.dumps({k:v for k,v in status.items() if k not in ('last_equilibrium_audit',)},ensure_ascii=False),flush=True)
    write(out/'summary.json',dict(version=VERSION,status='completed-projected-initialization-attempts',results=results,
        attempted=len(results),certified=sum(r['status']=='complete-resolved' for r in results),production_changed=False))
    write(out/'COMPLETE.json',dict(pipeline_snapshot_sha256=digest(out/'pipeline_snapshot.json'),summary_sha256=digest(out/'summary.json')))


if __name__=='__main__':main()
