"""Joint complementarity with exact response-only secondary objectives.

If ALL native terminal descendants give the responder the same payoff in each
compatible world, own utility is structurally indifferent under EVERY policy.
In those cells the equilibrium equation must optimize the others' payoff sum;
an own-only zero residual imposes no social optimality condition at all.
No weighted utility or altered tolerance is used. Remaining cells retain own
utility and the complete native social audit remains mandatory.
"""
import argparse
import time
from pathlib import Path

import numpy as np
from scipy.optimize import root

from .common import parents,sha,snapshot,write
from .engine import ReducedEngine
from .probe import build
from .run import repair_offpath
from training.b_sft.decision_policy import is_offer_response
from training.strategic_slices.common import save_reference
from training.strategic_slices.equilibrium import _JointResidual

VERSION='reduced-structural-response-social-joint-v1'


def structural_ties(tree):
    lower=[None]*len(tree.entries);upper=list(lower);cells=set()
    for i,e in reversed(list(enumerate(tree.entries))):
        if e.actor is None:lower[i]=upper[i]=e.payoff
        else:
            lower[i]=np.min(np.stack([lower[c] for c in e.children]),axis=0)
            upper[i]=np.max(np.stack([upper[c] for c in e.children]),axis=0)
            if is_offer_response(e.actions):
                for cell,ids in enumerate(tree.information_groups[i]):
                    if np.max(upper[i][ids,e.actor]-lower[i][ids,e.actor])<=1e-12:
                        cells.add((i,cell))
    return cells


class SocialResidual(_JointResidual):
    def __init__(self,tree,cells,action_supports=None):
        super().__init__(tree,cells,action_supports)
        if not hasattr(tree,'research_structural_response_ties'):
            tree.research_structural_response_ties=structural_ties(tree)
        self.social_starts={start for (i,c),(j,ids,start,k) in zip(self.cells,self.offsets)
                            if (i,c) in tree.research_structural_response_ties}

    def residual(self,x):
        self.tree._check()
        if not hasattr(self,'_batches'):self._compile()
        policy=self._base_array.copy();rows,actions,worlds,variables=self._assignment
        policy[rows,actions,worlds]=x[variables];values=self._constant_array.copy()
        for slots,children in self._layers:
            values[slots]=np.einsum('baw,bawp->bwp',policy[slots,:children.shape[1]],values[children])
        output=np.empty(len(x))
        for starts,ids,children,parents,path_actions,actors,k,length in self._batches:
            reach=self.tree.world_weights[ids].copy()
            if length:reach*=policy[parents[:,:,None],path_actions[:,:,None],ids[:,None,:]].prod(axis=1)
            zero=reach.sum(axis=1)==0;reach[zero]=self.tree.world_weights[ids[zero]]
            reach/=reach.sum(axis=1)[:,None]
            vectors=values[children[:,:,None],ids[:,None,:]]
            own=np.einsum('baw,bw->ba',values[children[:,:,None],ids[:,None,:],actors[:,None,None]],reach)
            social=np.einsum('bawp,bw->ba',vectors,reach)-own
            mask=np.array([int(start) in self.social_starts for start in starts])
            own[mask]=social[mask]
            positions=starts[:,None]+np.arange(k);p=x[positions];gap=x[starts+k,None]-own
            output[positions]=np.hypot(p,gap)-p-gap
            output[starts+k]=p.sum(axis=1)-1.
        return output


def solve(engine,seconds=120):
    start=time.monotonic();tree=engine.tree;tree.deadline=start+seconds
    ok,front,alternatives=engine.iterate(seconds=min(15.,seconds*.2))
    events=[];engine.social_events=events
    if ok:return True,dict(status='BR_candidate',front=front,events=events)
    for alt in sorted(alternatives,key=lambda a:a['score']):
        for i,p in alt['final'].items():tree.policy[i]=p.copy()
        histories=alt['history'];cells=set()
        for i in engine.active:
            for c,ids in enumerate(tree.information_groups[i]):
                if (i,c) in engine.red.fixed:continue
                if any(not np.allclose(h[i][:,ids[0]],histories[-1][i][:,ids[0]],atol=1e-10,rtol=0)
                       for h in histories[:-1]):cells.add((i,c))
        cells.update(engine.local_screen()['failed']);supports={}
        for i,c in cells:
            ids=tree.information_groups[i][c];support=set()
            for h in histories:support.update(int(a) for a in np.flatnonzero(h[i][:,ids[0]]>1e-9))
            supports[i,c]=tuple(sorted(support))
        for i in engine.active:tree.policy[i]=np.mean([h[i] for h in histories],axis=0)
        for attempt in range(8):
            tree._check()
            residual=SocialResidual(tree,cells,action_supports=supports)
            method='hybr' if len(residual.x0)<=256 else 'krylov'
            options=(dict(xtol=1e-11,maxfev=400*len(residual.x0)) if method=='hybr'
                     else dict(fatol=1e-12,maxiter=400,line_search='armijo'))
            result=root(residual.residual,residual.x0,method=method,options=options)
            tree.policy=residual.normalized_policy(result.x)
            # No blanket purification of already-valid response cells.
            for i,c in cells:
                ids=tree.information_groups[i][c];p=tree.policy[i][:,ids[0]].copy()
                p[p<1e-9]=0.
                if p.sum()>0:tree.policy[i][:,ids]=(p/p.sum())[:,None]
            local=engine.local_screen()
            events.append(dict(initialization=alt['initialization'],synchronous=alt['synchronous'],
                attempt=attempt,cells=len(cells),social_cells=len(residual.social_starts),
                variables=len(result.x),residual=float(np.max(np.abs(residual.residual(result.x)))),
                own_gain=local['worst'],ties=local['ties'],failed=len(local['failed'])))
            if not local['failed']:return True,dict(status='social_joint_candidate',front=front,events=events)
            for _ in range(2):
                if not engine.repair_responses():break
            local=engine.local_screen()
            if not local['failed']:return True,dict(status='social_joint_projected_candidate',front=front,events=events)
            additions=set(local['failed']);grew=False
            for key in additions:
                complete=tuple(range(len(tree.entries[key[0]].actions)))
                if supports.get(key)!=complete:grew=True
                supports[key]=complete
            new=additions-cells;cells.update(additions)
            if not new and not grew:break
    return None,dict(status='social_joint_unavailable',front=front,events=events)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--index',type=int,default=25);parser.add_argument('--seconds',type=float,default=120)
    args=parser.parse_args()
    snapshot(args.output,dict(backend=VERSION,index=args.index,seconds=args.seconds,
        operation='exact structural own-indifference response social equations',
        structural_test='all native terminal own-payoff extrema equal in every compatible world to 1e-12',
        horizon='native terminal',initialization='uniform/first/last ordered/synchronous',
        candidate_probability_snap=1e-9,epsilon=1e-8,repair_passes=8,build_seconds=30,
        audit_seconds=60,joint_attempts=8,root_evaluations=400,root_tolerances=1e-11))
    tree=build(parents()[args.index]);engine=ReducedEngine(tree)
    row=dict(index=args.index,parent_id=parents()[args.index]['id'],backend=VERSION)
    start=time.monotonic()
    try:
        ok,info=solve(engine,args.seconds);row['solver']=info
        if not ok:row['status']='candidate_unavailable'
        else:
            checked,diagnostic=repair_offpath(tree,8);row['native_diagnostics']=diagnostic
            row['status']='certified_native_terminal' if checked is not None else 'native_rejected'
            if checked is not None:
                row['certificate']=checked['certificate'];row['native_audit']=tree.audit_native()
                path=args.output/'cases'/str(args.index);path.mkdir(parents=True,exist_ok=True)
                save_reference(path/'reference.npz',tree);row['reference_sha256']=sha(path/'reference.npz')
    except Exception as exc:
        row.update(status='error',error=f'{type(exc).__name__}: {exc}',events=getattr(engine,'social_events',[]))
    row['elapsed_seconds']=time.monotonic()-start
    write(args.output/'cases'/str(args.index)/'result.json',row);write(args.output/'results.json',[row])
    print({k:row[k] for k in ('index','status','elapsed_seconds')},flush=True)


if __name__=='__main__':main()
