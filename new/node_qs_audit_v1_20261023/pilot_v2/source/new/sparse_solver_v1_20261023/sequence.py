"""Sparse two-player general-sum sequence form and complementarity MILP.

The MILP is a candidate generator for ordinary own-payoff Nash, NOT a proof
of the stronger native off-path/social contract. No dense sequence tableau.
Payoffs are shifted positive; this preserves preferences and bounds every
counterfactual dual value by prior(cell) * max_shifted_terminal_payoff.
"""
from dataclasses import dataclass
import time
import warnings

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import block_diag, bmat, coo_matrix, csr_matrix, eye, vstack

from .reduction import Reduction

VERSION = 'sparse-sequence-complementarity-milp-v1'


@dataclass
class Cell:
    index: int
    cell: int
    parent: int
    sequences: tuple
    actions: tuple
    mass: float


class SequenceGame:
    def __init__(self, tree, reduction=True):
        if tree.n != 2:
            raise ValueError('Sequence bilinear payoff backend supports exactly two players')
        self.tree = tree
        self.red = Reduction(tree)
        if not reduction:
            self.red.fixed.clear()
            self.red.known[:] = False
            for i,e in enumerate(tree.entries):
                if e.actor is None:
                    self.red.known[i] = True
                    self.red.payoffs[i] = e.payoff
        self.cells = [{}, {}]
        self.counts = [1, 1]
        self.leaves = []
        self.shift = 1. - min(float(e.payoff.min()) for e in tree.entries if e.actor is None)
        self.upper = self.shift + max(float(e.payoff.max()) for e in tree.entries if e.actor is None)
        for w in range(tree.w):
            self._visit(0,w,(0,0))
        self.E = [self._flow(p) for p in range(2)]
        rows=[s[0] for s,_,_ in self.leaves]
        cols=[s[1] for s,_,_ in self.leaves]
        self.A=[]
        for p in range(2):
            data=[weight*(payoff[p]+self.shift) for _,weight,payoff in self.leaves]
            a=coo_matrix((data,(rows,cols)),shape=tuple(self.counts)).tocsr()
            a.sum_duplicates();self.A.append(a)

    def _visit(self,i,w,seq):
        self.tree._check()
        if self.red.known[i,w]:
            self.leaves.append((seq,self.tree.world_weights[w],self.red.payoffs[i,w]))
            return
        entry=self.tree.entries[i];p=entry.actor
        key=(i,int(self.red.cell_ids[i][w]));actions=tuple(self.red.allowed(i,w))
        if len(actions)==1:
            self._visit(entry.children[actions[0]],w,seq)
            return
        if key not in self.cells[p]:
            childseq=tuple(range(self.counts[p],self.counts[p]+len(actions)))
            self.counts[p]+=len(actions)
            ids=self.tree.information_groups[i][key[1]]
            self.cells[p][key]=Cell(i,key[1],seq[p],childseq,actions,
                                  float(self.tree.world_weights[ids].sum()))
        cell=self.cells[p][key]
        if cell.parent!=seq[p] or cell.actions!=actions:
            raise ValueError('Sequence export violates perfect recall/information set consistency')
        for a,s in zip(actions,cell.sequences):
            updated=list(seq);updated[p]=s
            self._visit(entry.children[a],w,tuple(updated))

    def _flow(self,p):
        rows=[0];cols=[0];data=[1.]
        for row,cell in enumerate(self.cells[p].values(),1):
            rows.append(row);cols.append(cell.parent);data.append(-1.)
            rows.extend([row]*len(cell.sequences));cols.extend(cell.sequences)
            data.extend([1.]*len(cell.sequences))
        return coo_matrix((data,(rows,cols)),shape=(len(self.cells[p])+1,self.counts[p])).tocsr()

    def realization(self,policy,p):
        r=np.zeros(self.counts[p]);r[0]=1.
        for cell in self.cells[p].values():
            ids=self.tree.information_groups[cell.index][cell.cell]
            r[list(cell.sequences)]=r[cell.parent]*policy[cell.index][list(cell.actions),ids[0]]
        return r

    def install(self,realizations):
        self.red.install()
        for p,r in enumerate(realizations):
            for cell in self.cells[p].values():
                ids=self.tree.information_groups[cell.index][cell.cell]
                probs=np.maximum(r[list(cell.sequences)],0.)
                if probs.sum()<=1e-12:
                    continue  # off-path completion is separate and independently audited
                probs/=probs.sum()
                self.tree.policy[cell.index][:,ids]=0.
                self.tree.policy[cell.index][np.ix_(cell.actions,ids)]=probs[:,None]

    def sparse_bytes(self):
        return sum(m.data.nbytes+m.indices.nbytes+m.indptr.nbytes for m in self.E+self.A)

    def solve(self,seconds=30,disp=False):
        """Binary support disjunction implements r >= 0, g >= 0, r*g = 0."""
        n0,n1=self.counts;k0,k1=[e.shape[0] for e in self.E]
        ns=n0+n1;nk=k0+k1
        E,F=self.E;A,B=self.A
        # Variable order: x, y, v0, v1, z0, z1.
        # Explicit zero blocks retain all variable-column dimensions.
        flow=__import__('scipy').sparse.hstack((block_diag((E,F)),csr_matrix((nk,nk+ns))),format='csr')
        G=bmat([[csr_matrix((n0,n0)),-A,E.T,csr_matrix((n0,k1))],
                [-B.T,csr_matrix((n1,n1)),csr_matrix((n1,k0)),F.T]],format='csr')
        masses=[np.r_[1.,[c.mass for c in self.cells[p].values()]] for p in range(2)]
        bound=[]
        for p in range(2):
            limit=np.zeros(self.counts[p]);limit[0]=self.upper
            for c in self.cells[p].values():limit[list(c.sequences)]=self.upper*c.mass
            bound.append(limit)
        M=np.concatenate(bound)
        sparse=__import__('scipy').sparse
        lower=sparse.hstack((G,csr_matrix((ns,ns))),format='csr')
        upper=sparse.hstack((G,sparse.diags(M)),format='csr')
        support=sparse.hstack((eye(ns),csr_matrix((ns,nk)),-eye(ns)),format='csr')
        matrix=vstack((flow,lower,upper,support),format='csc')
        target=np.zeros(nk);target[0]=target[k0]=1.
        lb=np.r_[target,np.zeros(ns),np.full(ns,-np.inf),np.full(ns,-np.inf)]
        ub=np.r_[target,np.full(ns,np.inf),M,np.zeros(ns)]
        variable_upper=np.r_[np.ones(ns),self.upper*np.concatenate(masses),np.ones(ns)]
        integrality=np.r_[np.zeros(ns+nk,dtype=int),np.ones(ns,dtype=int)]
        start=time.monotonic()
        options=dict(time_limit=float(seconds),mip_rel_gap=0.,presolve=True,disp=disp,
                     mip_feasibility_tolerance=1e-9,primal_feasibility_tolerance=1e-9,
                     dual_feasibility_tolerance=1e-9)
        with warnings.catch_warnings(record=True) as caught:
            result=milp(np.zeros(len(variable_upper)),integrality=integrality,
                bounds=Bounds(np.zeros(len(variable_upper)),variable_upper),
                constraints=LinearConstraint(matrix,lb,ub),options=options)
        info=dict(status=int(result.status),message=result.message,
            elapsed_seconds=time.monotonic()-start,sequences=self.counts,
            information_sets=[len(c) for c in self.cells],payoff_nonzeros=[a.nnz for a in self.A],
            sparse_game_bytes=self.sparse_bytes(),milp_nonzeros=matrix.nnz,
            milp_shape=matrix.shape,options=options,
            warnings=[str(w.message) for w in caught],
            max_shifted_payoff=self.upper,payoff_shift=self.shift)
        if result.x is None:
            return None,info
        x=result.x.copy()
        z=x[ns+nk:]>.5
        # Independent high-accuracy linear feasibility polish of chosen support.
        plower=np.zeros(ns+nk);pupper=variable_upper[:ns+nk].copy()
        pupper[:ns][~z]=0.
        eq=vstack((flow[:,:ns+nk],G[z]),format='csr')
        rhs=np.r_[target,np.zeros(z.sum())]
        polished=linprog(np.zeros(ns+nk),A_ub=-G,b_ub=np.zeros(ns),
            A_eq=eq,b_eq=rhs,bounds=list(zip(plower,pupper)),method='highs',
            options=dict(primal_feasibility_tolerance=1e-10,dual_feasibility_tolerance=1e-10,
                         time_limit=float(seconds)))
        info['polish_status']=int(polished.status)
        if polished.success:x[:ns+nk]=polished.x
        g=G@x[:ns+nk]
        info.update(max_flow_residual=float(np.max(np.abs(flow@x-target))),
            minimum_dual_slack=float(g.min()),
            max_complementarity=float(np.max(np.abs(x[:ns]*g))))
        return (x[:n0],x[n0:ns]),info
