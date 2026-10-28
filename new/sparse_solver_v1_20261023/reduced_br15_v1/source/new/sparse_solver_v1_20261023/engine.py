"""Small, exact array engine after belief-independent backward elimination.

Only resolved constant subtrees become vector leaves. Every remaining public
history, world, information cell and native action remains distinct. Candidate
BRs preserve the current distribution among admissible own/social ties; the
independent native audit uses the original implementation and full tree.
"""
import hashlib
import time

import numpy as np

from .reduction import Reduction
from training.b_sft.decision_policy import is_offer_response
from training.b_sft.shared_teacher import TOL


class ReducedEngine:
    def __init__(self,tree):
        self.tree=tree;self.red=Reduction(tree);self.red.install()
        depth={0:0};active=[];leaves=[]
        def visit(i):
            if self.red.known[i].all():leaves.append(i);return
            active.append(i)
            for child in tree.entries[i].children:
                depth[child]=depth[i]+1;visit(child)
        visit(0)
        self.nodes=sorted(active+leaves);self.slots={i:s for s,i in enumerate(self.nodes)}
        self.active=active;self.layers=[]
        groups={}
        for i in active:
            e=tree.entries[i]
            partition=tuple(tuple(ids) for ids in tree.information_groups[i])
            key=(depth[i],e.actor,len(e.actions),is_offer_response(e.actions),partition)
            groups.setdefault(key,[]).append(i)
        for key,nodes in sorted(groups.items(),key=lambda kv:kv[0][:4]):
            slots=np.array([self.slots[i] for i in nodes])
            children=np.array([[self.slots[c] for c in tree.entries[i].children] for i in nodes])
            self.layers.append((nodes,slots,children,key[1],key[3],
                                [np.array(ids) for ids in key[4]]))
        self.leaves=np.array([self.slots[i] for i in leaves])
        self.payoffs=np.stack([self.red.payoffs[i] for i in leaves])

    def values(self):
        tree=self.tree;v=np.empty((len(self.nodes),tree.w,tree.n));v[self.leaves]=self.payoffs
        for nodes,slots,children,_,_,_ in reversed(self.layers):
            probs=np.stack([tree.policy[i] for i in nodes])
            v[slots]=np.einsum('baw,bawp->bwp',probs,v[children])
        return v

    def response(self,player):
        tree=self.tree
        reach=np.zeros((len(self.nodes),tree.w));reach[self.slots[0]]=tree.world_weights
        policies=[]
        for nodes,slots,children,actor,_,_ in self.layers:
            probs=np.stack([tree.policy[i] for i in nodes]);policies.append(probs)
            reach[children]=reach[slots,None,:]*(1. if actor==player else probs)
        values=np.empty((len(self.nodes),tree.w,tree.n));values[self.leaves]=self.payoffs
        updates={}
        for (nodes,slots,children,actor,response,groups),probs in reversed(list(zip(self.layers,policies))):
            tree._check();av=values[children]
            if actor==player:
                old=probs;probs=np.zeros_like(probs)
                for worlds in groups:
                    mass=reach[np.ix_(slots,worlds)].copy();zero=mass.sum(axis=1)==0
                    mass[zero]=tree.world_weights[worlds];mass/=mass.sum(axis=1)[:,None]
                    means=np.einsum('bawp,bw->bap',av[:,:,worlds],mass)
                    own=means[:,:,player];best=own>=own.max(axis=1)[:,None]-TOL
                    if response:
                        others=means.sum(axis=2)-own
                        best&=others>=np.where(best,others,-np.inf).max(axis=1)[:,None]-TOL
                    p=old[:,:,worlds[0]]*best
                    empty=p.sum(axis=1)<=0;p[empty]=best[empty]
                    p/=p.sum(axis=1)[:,None];probs[:,:,worlds]=p[:,:,None]
                updates.update((i,p) for i,p in zip(nodes,probs))
            values[slots]=np.einsum('baw,bawp->bwp',probs,av)
        return updates,values[self.slots[0]]

    def signature(self):
        digest=hashlib.sha256()
        for i in self.active:digest.update(self.tree.policy[i].tobytes())
        return digest.digest()

    def local_screen(self,epsilon=1e-8):
        tree=self.tree;values=self.values()
        worst=0.;ties=0;failed=[]
        for player in range(tree.n):
            reach=np.zeros((len(self.nodes),tree.w));reach[self.slots[0]]=tree.world_weights
            for nodes,slots,children,actor,_,_ in self.layers:
                probs=np.stack([tree.policy[i] for i in nodes])
                reach[children]=reach[slots,None,:]*(1. if actor==player else probs)
            for nodes,slots,children,actor,response,groups in self.layers:
                if actor!=player:continue
                probs=np.stack([tree.policy[i] for i in nodes]);av=values[children]
                for cell,worlds in enumerate(groups):
                    mass=reach[np.ix_(slots,worlds)].copy();zero=mass.sum(axis=1)==0
                    mass[zero]=tree.world_weights[worlds];mass/=mass.sum(axis=1)[:,None]
                    means=np.einsum('bawp,bw->bap',av[:,:,worlds],mass)
                    own=means[:,:,player];best=own.max(axis=1)
                    support=probs[:,:,worlds[0]]>TOL
                    gains=best-np.where(support,own,np.inf).min(axis=1)
                    bad=gains>epsilon;worst=max(worst,float(gains.max()))
                    if response:
                        admissible=own>=best[:,None]-TOL;others=means.sum(axis=2)-own
                        rejected=admissible&(others<np.where(admissible,others,-np.inf).max(axis=1)[:,None]-TOL)
                        t=(probs[:,:,worlds[0]]*rejected).sum(axis=1)>TOL
                        ties+=int(t.sum());bad|=t
                    failed.extend((nodes[j],cell) for j in np.flatnonzero(bad))
        return dict(worst=worst,ties=ties,failed=failed)

    def iterate(self,seconds=30,max_sweeps=256):
        """Deterministic inertia BR search; no convergence/acceptance shortcut."""
        tree=self.tree;start=time.monotonic();events=[];profiles=[]
        active_initial={i:tree.policy[i].copy() for i in self.active}
        starts=[('uniform',False),('first',False),('last',False),
                ('uniform',True),('first',True),('last',True)]
        for init,synchronous in starts:
            for i in self.active:
                tree.policy[i]=active_initial[i].copy()
                if init!='uniform':
                    tree.policy[i][:]=0.;tree.policy[i][0 if init=='first' else -1]=1.
            self.red.install();seen=set();history=[]
            for sweep in range(max_sweeps):
                if time.monotonic()-start>=seconds:
                    return None,dict(status='search_timeout',events=events),profiles
                signature=self.signature()
                if signature in seen:break
                seen.add(signature)
                history.append({i:tree.policy[i].copy() for i in self.active})
                history=history[-3:]
                if synchronous:
                    updates=[self.response(p)[0] for p in range(tree.n)]
                    for u in updates:
                        for i,p in u.items():tree.policy[i]=p
                else:
                    for p in range(tree.n):
                        updates,_=self.response(p)
                        for i,probs in updates.items():tree.policy[i]=probs
                local=self.local_screen()
                if not local['failed']:
                    return True,dict(status='reduced_local_candidate',events=events,
                        initialization=init,synchronous=synchronous,sweeps=sweep+1,
                        reduced_public_nodes=len(self.nodes)),profiles
            local=self.local_screen()
            events.append(dict(initialization=init,synchronous=synchronous,
                sweeps=sweep+1,worst=local['worst'],ties=local['ties'],failed=len(local['failed'])))
            profiles.extend(history)
        return None,dict(status='BR_cycles',events=events,reduced_public_nodes=len(self.nodes)),profiles
