"""Support-based local indifference solving with exact zero off-path support.

Positive probabilities use a softmax bounded away from zero. Omitted actions
are EXACTLY zero, so residual evaluation and native certification use the SAME
zero-reach prior convention. This avoids solving a limiting posterior and then
silently changing beliefs when tiny probabilities are snapped after solving.
"""
import time

import numpy as np
from scipy.optimize import least_squares

from training.strategic_slices.equilibrium import _JointResidual, _means, _reach

VERSION='reduced-fixed-support-indifference-v1'


class Indifference:
    def __init__(self,tree,supports):
        self.base=_JointResidual(tree,set(supports),action_supports=supports)
        self.base._compile();self.x0=[];self.segments=[]
        for i,ids,start,k in self.base.offsets:
            probs=self.base.x0[start:start+k]
            probs=np.maximum(probs,1e-3);probs/=probs.sum()
            offset=len(self.x0)
            self.x0.extend(np.log(probs[:-1]/probs[-1]))
            self.segments.append((start,k,offset))
        self.x0=np.clip(np.array(self.x0),-15,15)

    def unpack(self,z):
        x=self.base.x0.copy()
        for start,k,offset in self.segments:
            logits=np.r_[z[offset:offset+k-1],0.];logits-=logits.max()
            p=np.exp(logits);p/=p.sum();x[start:start+k]=p
        return x

    def residual(self,z):
        b=self.base;b.tree._check();x=self.unpack(z)
        policy=b._base_array.copy()
        rows,actions,worlds,variables=b._assignment;policy[rows,actions,worlds]=x[variables]
        values=b._constant_array.copy()
        for slots,children in b._layers:
            values[slots]=np.einsum('baw,bawp->bwp',policy[slots,:children.shape[1]],values[children])
        differences={}
        for starts,ids,children,parents,path_actions,actors,k,length in b._batches:
            reach=b.tree.world_weights[ids].copy()
            if length:reach*=policy[parents[:,:,None],path_actions[:,:,None],ids[:,None,:]].prod(axis=1)
            zero=reach.sum(axis=1)==0;reach[zero]=b.tree.world_weights[ids[zero]]
            reach/=reach.sum(axis=1)[:,None]
            own=np.einsum('baw,bw->ba',values[children[:,:,None],ids[:,None,:],actors[:,None,None]],reach)
            for j,start in enumerate(starts):differences[int(start)]=own[j,:-1]-own[j,-1]
        return np.concatenate([differences[start] for start,_,_ in self.segments])


def solve(engine,seconds=60,max_iterations=16):
    start=time.monotonic();tree=engine.tree;tree.deadline=start+seconds
    ok,front,alternatives=engine.iterate(seconds=min(seconds*.2,15.))
    if ok:return True,dict(backend=VERSION,status='BR_candidate',front=front)
    events=[]
    for alt in sorted(alternatives,key=lambda a:a['score']):
        for i,p in alt['final'].items():tree.policy[i]=p.copy()
        history=alt['history'];supports={}
        for i in engine.active:
            for c,ids in enumerate(tree.information_groups[i]):
                if (i,c) in engine.red.fixed:continue
                union=set()
                for h in history:union.update(int(a) for a in np.flatnonzero(h[i][:,ids[0]]>1e-9))
                if len(union)>1:supports[i,c]=tuple(sorted(union))
        for i in engine.active:tree.policy[i]=np.mean([h[i] for h in history],axis=0)
        seen=set()
        for iteration in range(max_iterations):
            tree._check()
            signature=tuple(sorted(supports.items()))
            if signature in seen:break
            seen.add(signature)
            if supports:
                system=Indifference(tree,supports)
                if len(system.x0):
                    result=least_squares(system.residual,system.x0,bounds=(-18.,18.),
                        xtol=1e-12,ftol=1e-12,gtol=1e-12,max_nfev=300)
                    residual=float(np.max(np.abs(system.residual(result.x))))
                    tree.policy=system.base.normalized_policy(system.unpack(result.x))
                else:residual=0.
            else:residual=0.
            before=engine.local_screen()
            # Resolve only response failures using actual selected continuation.
            for _ in range(2):
                if not engine.repair_responses():break
            local=engine.local_screen()
            events.append(dict(initialization=alt['initialization'],synchronous=alt['synchronous'],
                iteration=iteration,cells=len(supports),variables=sum(len(s)-1 for s in supports.values()),
                indifference_residual=residual,local_gain=local['worst'],ties=local['ties'],failed=len(local['failed'])))
            if not local['failed']:
                return True,dict(backend=VERSION,status='support_local_candidate',front=front,events=events)
            # Full legal-action separation; support grows only by a maximizer.
            values=tree.evaluate();reaches={p:_reach(tree,p) for p in range(tree.n)}
            for i,c in local['failed']:
                p=tree.entries[i].actor;ids=tree.information_groups[i][c]
                own=_means(tree,values,reaches[p],i,ids)[:,p]
                best=int(np.argmax(own));active=set(supports.get((i,c),
                    tuple(int(a) for a in np.flatnonzero(tree.policy[i][:,ids[0]]>1e-9))))
                # Infeasible equality support: discard an inferior action that
                # the bounded solve already pushed towards its probability edge.
                probs=tree.policy[i][:,ids[0]]
                tiny=[a for a in active if probs[a]<1e-6 and own[best]-own[a]>1e-8]
                active.difference_update(tiny);active.add(best)
                supports[i,c]=tuple(sorted(active))
                # Single-action support is represented exactly, including zero
                # probability paths, rather than an infinitesimal likelihood.
                if len(active)==1:
                    tree.policy[i][:,ids]=0.;tree.policy[i][best,ids]=1.
    return None,dict(backend=VERSION,status='support_unavailable',front=front,events=events)
