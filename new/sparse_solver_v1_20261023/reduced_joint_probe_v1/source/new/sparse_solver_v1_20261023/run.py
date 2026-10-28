"""Independent sparse candidate, complete native acceptance, saved provenance."""
import argparse
from pathlib import Path
import time

import numpy as np

from .common import parents, sha, snapshot, write
from .probe import build
from .sequence import SequenceGame, VERSION
from training.strategic_slices.common import save_reference
from training.strategic_slices.equilibrium import certify_policy, local_policy_audit, _reach, _means
from training.b_sft.decision_policy import optimal_indices


def diagnostics(tree):
    tree.deadline=time.monotonic()+60
    result=certify_policy(tree,epsilon=1e-8)
    audit=dict(tree.equilibrium_audit)
    if 'local_policy_audit' not in audit:
        audit['local_policy_audit']=local_policy_audit(tree,epsilon=1e-8)
    local=audit['local_policy_audit']
    summary=dict(max_root_gain=audit['max_own_deviation_gain'],
        max_local_supported_gain=local['max_local_supported_action_gain'],
        own_local_failures=len(local['own_failures']),response_tie_failures=len(local['failures']))
    return result,audit,summary


def repair_offpath(tree,passes,mode='continuation'):
    """Candidate-only completion; a fresh full certificate is always required."""
    events=[]
    for iteration in range(passes+1):
        result,audit,summary=diagnostics(tree)
        events.append(dict(iteration=iteration,**summary))
        if result is not None:return result,events
        if iteration==passes:break
        local=audit['local_policy_audit']
        failed=local['own_failures']+local['failures']
        if not failed:break
        if mode=='contingent-br':
            updates={p:tree.response(p)[0] for p in {f['player'] for f in failed}}
            for f in failed:
                i,c,p=f['index'],f['cell'],f['player']
                ids=tree.information_groups[i][c]
                tree.policy[i][:,ids]=updates[p][i][:,ids]
        else:
            # Local tie repair MUST use the actual continuation, not a new
            # complete BR's arbitrary choices at later own-utility ties.
            depth={0:0};layers={}
            for i,e in enumerate(tree.entries):
                for child in e.children:depth[child]=depth[i]+1
            for f in failed:layers.setdefault(depth[f['index']],set()).add((f['index'],f['cell']))
            for _,cells in sorted(layers.items(),reverse=True):
                values=tree.evaluate();reaches={p:_reach(tree,p) for p in range(tree.n)}
                for i,c in sorted(cells):
                    p=tree.entries[i].actor;ids=tree.information_groups[i][c]
                    means=_means(tree,values,reaches[p],i,ids)
                    admissible=optimal_indices(means,p,tree.entries[i].actions)
                    current=tree.policy[i][:,ids[0]].copy()
                    probs=np.zeros_like(current);probs[admissible]=current[admissible]
                    if probs.sum()<=1e-12:probs[admissible]=1./len(admissible)
                    else:probs/=probs.sum()
                    tree.policy[i][:,ids]=probs[:,None]
    return None,events


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--indices',default='74')
    parser.add_argument('--seconds',type=float,default=30.)
    parser.add_argument('--repair-passes',type=int,default=4)
    parser.add_argument('--disp',action='store_true')
    parser.add_argument('--backend',choices=('milp','double-oracle','gambit','reduced-br','reduced-joint'),default='milp')
    parser.add_argument('--repair-mode',choices=('continuation','contingent-br'),default='continuation')
    parser.add_argument('--initial-reference',type=Path)
    args=parser.parse_args()
    if args.seconds<=0 or args.repair_passes<0:parser.error('Invalid budgets')
    indices=list(map(int,args.indices.split(',')))
    snapshot(args.output,dict(indices=indices,backend=args.backend,implementation=VERSION,seconds=args.seconds,
        construction_seconds=30,audit_seconds=60,epsilon=1e-8,
        repair_passes=args.repair_passes,disp=args.disp,initialization='uniform',
        repair_mode=args.repair_mode,
        initial_reference=(dict(path=str(args.initial_reference),sha256=sha(args.initial_reference))
                           if args.initial_reference else None),
        horizon='all native terminal; no cutoff',
        elimination='pointwise backward dominance, response pointwise lexicographic; no state/history merging',
        candidate='ordinary two-player own-payoff Nash via sparse sequence form binary complementarity',
        acceptance='unchanged full-tree private-information BR, local support, response social tie, native audit',
        payoff_shift='1-min(native terminal utility), preference invariant',
        MILP='SciPy milp / bundled HiGHS; feasibility tolerances 1e-9, mip_rel_gap=0; time limit per parent',
        polish='chosen binary support LP, HiGHS primal/dual tolerance 1e-10, same time budget',
        model='NOT_USED',Q='NOT_COMPUTED',S='NOT_COMPUTED',D='NOT_MEASURED'))
    pool=parents();rows=[]
    for index in indices:
        path=args.output/'cases'/str(index);path.mkdir(parents=True)
        row=dict(index=index,parent_id=pool[index]['id'],status='started')
        start=time.monotonic();phase='construction'
        try:
            tree=build(pool[index]);phase='sequence_export'
            if args.backend.startswith('reduced-'):
                from .engine import ReducedEngine
                game=ReducedEngine(tree)
            else:game=SequenceGame(tree)
            row.update(nodes=len(tree.entries),worlds=tree.w,cutoff_leaves=len(tree.cutoff_leaves),
                reduction=game.red.dimensions(),export_seconds=time.monotonic()-start)
            phase=args.backend
            if args.initial_reference:
                with np.load(args.initial_reference) as data:flat=data['probabilities']
                offset=0
                for probs in tree.policy:
                    if probs is not None:
                        probs[:]=flat[offset:offset+probs.size].reshape(probs.shape);offset+=probs.size
                if offset!=len(flat):raise ValueError('Initial native policy length mismatch')
                realizations=[];info=dict(status='loaded_explicit_native_candidate')
            elif args.backend=='double-oracle':
                from .double_oracle import solve
                realizations,info=solve(game,seconds=args.seconds)
            elif args.backend=='gambit':
                from .gambit_backend import solve
                realizations,info=solve(game,path,seconds=args.seconds)
            elif args.backend=='reduced-br':
                realizations,info,_=game.iterate(seconds=args.seconds)
            elif args.backend=='reduced-joint':
                from .joint import solve
                realizations,info=solve(game,seconds=args.seconds)
            else:realizations,info=game.solve(args.seconds,args.disp)
            row['solver']=info
            if realizations is None:
                row['status']='candidate_unavailable'
            else:
                phase='native_certification';tree.deadline=time.monotonic()+60
                if not args.initial_reference and not args.backend.startswith('reduced-'):game.install(realizations)
                save_reference(path/'candidate.npz',tree)
                result,events=repair_offpath(tree,args.repair_passes,args.repair_mode)
                row['native_diagnostics']=events
                row['status']='certified_native_terminal' if result is not None else 'candidate_rejected_by_native_contract'
                if result is not None:
                    row['certificate']=result['certificate'];row['native_audit']=tree.audit_native()
                    assert not row['native_audit']['cutoff_leaves']
                    save_reference(path/'reference.npz',tree)
                    row['reference_sha256']=sha(path/'reference.npz')
                else:save_reference(path/'rejected_after_completion.npz',tree)
        except Exception as exc:
            row.update(status='error',failed_phase=phase,error=f'{type(exc).__name__}: {exc}')
        row['elapsed_seconds']=time.monotonic()-start
        write(path/'result.json',row);rows.append(row);write(args.output/'results.json',rows)
        print({k:row[k] for k in ('index','status','elapsed_seconds')},flush=True)


if __name__=='__main__':main()
