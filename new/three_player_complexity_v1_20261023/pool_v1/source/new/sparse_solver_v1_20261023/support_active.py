"""Finite-support repair: fix numerical zero actions before resolving beliefs."""
import argparse
from pathlib import Path
import time

import numpy as np
from scipy.optimize import root

from .common import parents,sha,snapshot,write
from .engine import ReducedEngine
from .probe import build
from .run import repair_offpath
from .social_joint import SocialResidual
from training.strategic_slices.equilibrium import _means,_reach
from training.b_sft.decision_policy import optimal_indices
from training.strategic_slices.common import save_reference

VERSION='exact-zero-support-active-set-v1'


def solve(engine,seconds=90):
    tree=engine.tree;start=time.monotonic();tree.deadline=start+seconds
    ok,front,alternatives=engine.iterate(seconds=min(seconds*.2,15.))
    events=[];engine.active_events=events
    if ok:return True,dict(status='BR_candidate',events=events)
    for alt in sorted(alternatives,key=lambda a:a['score']):
        history=alt['history'];supports={}
        for i,p in alt['final'].items():tree.policy[i]=p.copy()
        for i in engine.active:
            for cell,ids in enumerate(tree.information_groups[i]):
                if (i,cell) in engine.red.fixed:continue
                union=set()
                for h in history:union.update(int(a) for a in np.flatnonzero(h[i][:,ids[0]]>1e-9))
                if len(union)>1:supports[i,cell]=tuple(sorted(union))
        for key in engine.local_screen()['failed']:
            i,c=key;ids=tree.information_groups[i][c]
            supports.setdefault(key,tuple(int(a) for a in np.flatnonzero(tree.policy[i][:,ids[0]]>1e-9)))
        for i in engine.active:tree.policy[i]=np.mean([h[i] for h in history],axis=0)
        seen={}
        for iteration in range(40):
            tree._check();system=SocialResidual(tree,set(supports),supports)
            method='hybr' if len(system.x0)<=256 else 'krylov'
            options=(dict(xtol=1e-11,maxfev=200*len(system.x0)) if method=='hybr'
                     else dict(fatol=1e-12,maxiter=200,line_search='armijo'))
            result=root(system.residual,system.x0,method=method,options=options)
            tree.policy=system.normalized_policy(result.x)
            for i,c in supports:
                ids=tree.information_groups[i][c];p=tree.policy[i][:,ids[0]].copy()
                p[p<1e-8]=0.
                if p.sum()>0:tree.policy[i][:,ids]=(p/p.sum())[:,None]
            local=engine.local_screen()
            if local['failed']:
                engine.repair_responses();local=engine.local_screen()
            events.append(dict(initialization=alt['initialization'],synchronous=alt['synchronous'],
                iteration=iteration,cells=len(supports),variables=len(result.x),
                residual=float(np.max(np.abs(system.residual(result.x)))),
                own_gain=local['worst'],ties=local['ties'],failed=len(local['failed'])))
            if not local['failed']:return True,dict(status='active_support_candidate',front=front,events=events)
            # Drop numerical zeros from the NEXT system itself. Their exact
            # absence determines zero-reach beliefs during root evaluation.
            for i,c in list(supports):
                ids=tree.information_groups[i][c]
                supports[i,c]=tuple(int(a) for a in np.flatnonzero(tree.policy[i][:,ids[0]]>1e-8))
            values=tree.evaluate();reaches={p:_reach(tree,p) for p in range(tree.n)}
            for i,c in local['failed']:
                p=tree.entries[i].actor;ids=tree.information_groups[i][c]
                means=_means(tree,values,reaches[p],i,ids)
                best=optimal_indices(means,p,tree.entries[i].actions)
                current=set(int(a) for a in np.flatnonzero(tree.policy[i][:,ids[0]]>1e-8))
                current.update(int(a) for a in best);supports[i,c]=tuple(sorted(current))
            signature=tuple(sorted(supports.items()));count=seen.get(signature,0);seen[signature]=count+1
            if count>=2:break
            for i,c in supports:
                ids=tree.information_groups[i][c];active=list(supports[i,c])
                probs=tree.policy[i][:,ids[0]].copy();probs[[a for a in range(len(probs)) if a not in active]]=0.
                probs[active]+=0.02;probs/=probs.sum();tree.policy[i][:,ids]=probs[:,None]
    return None,dict(status='active_support_unavailable',front=front,events=events)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--index',type=int,default=25);parser.add_argument('--seconds',type=float,default=90)
    args=parser.parse_args();snapshot(args.output,dict(backend=VERSION,index=args.index,
        seconds=args.seconds,initialization='uniform/first/last ordered/synchronous',
        epsilon=1e-8,candidate_snap_and_support_threshold=1e-8,support_seed_mass=.02,
        structural_response_social_equations=True,root_evaluations=200,attempts_per_start=40,
        cycle_limit=2,repair_passes=8,build_seconds=30,audit_seconds=60,horizon='native terminal'))
    parent=parents()[args.index];tree=build(parent);engine=ReducedEngine(tree)
    row=dict(index=args.index,parent_id=parent['id'],backend=VERSION);start=time.monotonic()
    try:
        ok,info=solve(engine,args.seconds);row['solver']=info
        row['status']='candidate_unavailable'
        if ok:
            checked,diagnostic=repair_offpath(tree,8);row['native_diagnostics']=diagnostic
            row['status']='certified_native_terminal' if checked is not None else 'native_rejected'
            if checked is not None:
                row['certificate']=checked['certificate'];row['native_audit']=tree.audit_native()
                path=args.output/'cases'/str(args.index);path.mkdir(parents=True,exist_ok=True)
                save_reference(path/'reference.npz',tree);row['reference_sha256']=sha(path/'reference.npz')
    except Exception as exc:
        row.update(status='error',error=f'{type(exc).__name__}: {exc}',events=getattr(engine,'active_events',[]))
    row['elapsed_seconds']=time.monotonic()-start
    write(args.output/'cases'/str(args.index)/'result.json',row);write(args.output/'results.json',[row])
    print({k:row[k] for k in ('index','status','elapsed_seconds')},flush=True)


if __name__=='__main__':main()
