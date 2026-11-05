"""Explain a rejected candidate, without turning it into a reference."""
import argparse
from pathlib import Path
import time

import numpy as np

from .run import snapshot
from .metrics import stable
from new.sparse_solver_v1_20261023.common import ROOT, parents, sha, write
from new.sparse_solver_v1_20261023.probe import build
from training.strategic_slices.equilibrium import certify_policy, local_policy_audit, _reach, _means
from training.b_sft.social_private_teacher import observed_slots


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    paths=[ROOT/'new/sparse_solver_v1_20261023/boundary25_v1'/name
           for name in ('normalized_candidate.npz','snapped_candidate.npz')]
    snapshot(args.output,dict(operation='Explain rejected terminal25; no search, repair or accepted labels',
        index=25,epsilon=1e-8,tie_tolerance=1e-9,build_seconds=60,audit_seconds=180),
        {i:dict(path=p,sha256=sha(p)) for i,p in enumerate(paths)})
    parent=parents()[25];tree=build(parent,seconds=60);output=[]
    for path in paths:
        with np.load(path) as data: flat=data['probabilities']
        cursor=0
        for p in tree.policy:
            if p is not None: p[:]=flat[cursor:cursor+p.size].reshape(p.shape);cursor+=p.size
        assert cursor==len(flat);tree.deadline=time.monotonic()+180
        cert=certify_policy(tree,epsilon=1e-8);assert cert is None
        audit=tree.equilibrium_audit;values=tree.evaluate()
        local=local_policy_audit(tree,values,epsilon=1e-8)
        reaches={p:_reach(tree,p) for p in range(tree.n)}
        joint=[None]*len(tree.entries);joint[0]=tree.world_weights.copy()
        for i,entry in enumerate(tree.entries):
            for ai,ch in enumerate(entry.children):joint[ch]=joint[i]*tree.policy[i][ai]
        failures=[]
        for fail in local['own_failures']:
            i,c,p=fail['index'],fail['cell'],fail['player'];entry=tree.entries[i]
            ids=tree.information_groups[i][c];means=_means(tree,values,reaches[p],i,ids)
            mass=float(reaches[p][i][ids].sum())
            weights=reaches[p][i][ids] if mass>0 else tree.world_weights[ids]
            weights=weights/weights.sum()
            failures.append(dict(**fail,turn=entry.node.state.turn_index,
                phase='response' if entry.node.pending else 'proposal',
                own_type=tree.worlds[ids[0]][p],
                own_answers=[(a,g,tree.worlds[ids[0]][a][g]) for a,g in observed_slots(entry.node,p)],
                counterfactual_mass=mass,actual_reference_mass=float(joint[i][ids].sum()),
                belief='conditional_prior_fallback' if mass==0 else 'positive_counterfactual',
                actions=[a.to_dict() for a in entry.actions],Q=means[:,p].tolist(),
                probabilities=tree.policy[i][:,ids[0]].tolist(),
                best_actions=np.flatnonzero(means[:,p]>=means[:,p].max()-1e-9).tolist(),
                history=[e.to_dict() for e in entry.node.state.transcript],
                pending=None if entry.node.pending is None else entry.node.pending.to_dict(),
                worlds=[dict(world=tree.worlds[wi],probability=float(w)) for wi,w in zip(ids,weights)]))
        output.append(dict(candidate=str(path.relative_to(ROOT)),candidate_sha256=sha(path),
            max_root_gain=audit['max_own_deviation_gain'],
            max_local_supported_gain=local['max_local_supported_action_gain'],
            own_failures=failures,response_tie_failures=local['failures'],
            failures_zero_CF=sum(f['counterfactual_mass']==0 for f in failures),
            failures_positive_CF=sum(f['counterfactual_mass']>0 for f in failures),
            failures_positive_actual_reach=sum(f['actual_reference_mass']>0 for f in failures)))
    write(args.output/'diagnosis.json',dict(parent=parent,results=output,
        interpretation='Rejected ordinary-root-Nash candidates; full local/off-path rationality not established. No impossibility claim.'))
    write(args.output/'COMPLETE.json',dict(accepted_labels=False,diagnosis_sha256=sha(args.output/'diagnosis.json'),
        snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    for r in output:print({k:v for k,v in r.items() if k not in ('own_failures','response_tie_failures')},flush=True)


if __name__=='__main__':main()
