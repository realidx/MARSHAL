"""General-sum fictitious-play candidates, proper realization averaging.

No general-sum convergence guarantee or automatic label acceptance. Full native
certification follows any support polish. Averaging is over complete own plans,
not pointwise behavioral probabilities.
"""
import argparse
from pathlib import Path
import time

import numpy as np
from scipy.optimize import root

from .common import parents,sha,snapshot,write
from .engine import ReducedEngine
from .probe import build
from .run import repair_offpath
from .sequence import SequenceGame
from .social_joint import SocialResidual
from training.b_sft.decision_policy import is_offer_response
from training.strategic_slices.equilibrium import _means,_reach
from training.strategic_slices.common import save_reference


def polish(engine,threshold=.05):
    tree=engine.tree;values=tree.evaluate();reach={p:_reach(tree,p) for p in range(tree.n)}
    for i in engine.active:
        p=tree.entries[i].actor
        for c,ids in enumerate(tree.information_groups[i]):
            means=_means(tree,values,reach[p],i,ids);own=means[:,p]
            allowed=own>=own.max()-threshold
            if is_offer_response(tree.entries[i].actions) and np.ptp(own)<=1e-9:
                others=means.sum(axis=1)-own;allowed&=others>=others.max()-threshold
            probs=tree.policy[i][:,ids[0]]*allowed
            if probs.sum()<=0:probs=allowed.astype(float)
            tree.policy[i][:,ids]=(probs/probs.sum())[:,None]
    events=[];supports={}
    values=tree.evaluate();reach={p:_reach(tree,p) for p in range(tree.n)}
    for i in engine.active:
        p=tree.entries[i].actor
        for c,ids in enumerate(tree.information_groups[i]):
            probs=tree.policy[i][:,ids[0]];active=np.flatnonzero(probs>1e-7)
            means=_means(tree,values,reach[p],i,ids);own=means[:,p]
            if len(active)>1 and np.ptp(own[active])>1e-10:
                supports[i,c]=tuple(int(a) for a in active)
    for i,c in engine.local_screen()['failed']:
        p=tree.entries[i].actor;ids=tree.information_groups[i][c]
        own=_means(tree,values,reach[p],i,ids)[:,p]
        active=set(int(a) for a in np.flatnonzero(tree.policy[i][:,ids[0]]>1e-7));active.add(int(np.argmax(own)))
        supports[i,c]=tuple(sorted(active))
    for iteration in range(12):
        tree._check()
        if not supports:break
        system=SocialResidual(tree,set(supports),supports)
        if len(system.x0)>1024:return None,dict(status='polish_dimension_guard',variables=len(system.x0),events=events)
        method='hybr' if len(system.x0)<=256 else 'krylov'
        options=(dict(xtol=1e-11,maxfev=200*len(system.x0)) if method=='hybr'
                 else dict(fatol=1e-12,maxiter=200,line_search='armijo'))
        solution=root(system.residual,system.x0,method=method,options=options)
        tree.policy=system.normalized_policy(solution.x)
        for i,c in supports:
            ids=tree.information_groups[i][c];probs=tree.policy[i][:,ids[0]].copy();probs[probs<1e-8]=0.
            if probs.sum()>0:tree.policy[i][:,ids]=(probs/probs.sum())[:,None]
        engine.repair_responses();local=engine.local_screen()
        events.append(dict(iteration=iteration,variables=len(solution.x),local_gain=local['worst'],
            ties=local['ties'],failed=len(local['failed'])))
        if not local['failed']:return True,dict(status='polished_candidate',events=events)
        for i,c in list(supports):
            ids=tree.information_groups[i][c];supports[i,c]=tuple(int(a) for a in np.flatnonzero(tree.policy[i][:,ids[0]]>1e-8))
        values=tree.evaluate();reach={p:_reach(tree,p) for p in range(tree.n)}
        for i,c in local['failed']:
            p=tree.entries[i].actor;ids=tree.information_groups[i][c]
            own=_means(tree,values,reach[p],i,ids)[:,p]
            active=set(supports.get((i,c),tuple(int(a) for a in np.flatnonzero(tree.policy[i][:,ids[0]]>1e-8))))
            active.add(int(np.argmax(own)));supports[i,c]=tuple(sorted(active))
        for i,c in supports:
            ids=tree.information_groups[i][c];probs=tree.policy[i][:,ids[0]].copy()
            probs[list(supports[i,c])]+=.01;probs/=probs.sum();tree.policy[i][:,ids]=probs[:,None]
    return None,dict(status='polish_unavailable',events=events)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--index',type=int,default=25);parser.add_argument('--seconds',type=float,default=180)
    args=parser.parse_args();snapshot(args.output,dict(backend='realization-fictitious-play-polish-v1',
        index=args.index,seconds=args.seconds,iterations=1200,checkpoints=[100,400,1200],
        epsilon=1e-8,initialization='uniform',average='uniform complete own realization plans',
        update_order=[0,1],nearbest_prune=.05,candidate_snap=1e-8,repair_passes=8,
        horizon='native terminal',guarantee='none for general sum; native full certificate mandatory'))
    parent=parents()[args.index];tree=build(parent);engine=ReducedEngine(tree);game=SequenceGame(tree)
    tree.deadline=time.monotonic()+args.seconds;start=time.monotonic();row=dict(index=args.index,parent_id=parent['id'])
    totals=[game.realization(tree.policy,p) for p in range(2)];counts=[1,1];events=[]
    row['status']='candidate_unavailable'
    try:
        for iteration in range(1,1201):
            for p in range(2):
                updates,_=engine.response(p);policy=list(tree.policy)
                for i,probs in updates.items():policy[i]=probs
                br=game.realization(policy,p);totals[p]+=br;counts[p]+=1
                for i,probs in updates.items():tree.policy[i]=probs
                game.install([totals[q]/counts[q] for q in range(2)])
            if iteration in (100,400,1200):
                average=[None if p is None else p.copy() for p in tree.policy]
                ok,info=polish(engine);events.append(dict(iteration=iteration,polish=info))
                write(args.output/'events.json',events)
                if ok:
                    checked,diagnostic=repair_offpath(tree,8);row['native_diagnostics']=diagnostic
                    if checked is not None:
                        row['status']='certified_native_terminal';row['certificate']=checked['certificate']
                        row['native_audit']=tree.audit_native();path=args.output/'cases'/str(args.index)
                        path.mkdir(parents=True,exist_ok=True);save_reference(path/'reference.npz',tree)
                        row['reference_sha256']=sha(path/'reference.npz');break
                tree.policy=average
    except Exception as exc:row.update(status='error',error=f'{type(exc).__name__}: {exc}')
    row.update(events=events,elapsed_seconds=time.monotonic()-start)
    write(args.output/'cases'/str(args.index)/'result.json',row);write(args.output/'results.json',[row])
    print({k:row[k] for k in ('index','status','elapsed_seconds')},flush=True)


if __name__=='__main__':main()
