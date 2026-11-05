"""Restricted-plan Nash + exact sparse sequence LP best-response oracles.

No zero-sum assumption. Restricted-game complementarity is solved by HiGHS
MILP. New full contingent plans are added, never averaged pointwise. A mixed
plan is converted through its realization plan (perfect recall). This finite
algorithm has no useful general polynomial-time guarantee; budgets fail closed.
"""
import time

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import csr_matrix

from .sequence import SequenceGame, Cell

VERSION='sparse-realization-double-oracle-v1'


def matrix_nash(a,b,seconds=5.):
    # Reuse independently tested support disjunction on a one-infoset game.
    game=SequenceGame.__new__(SequenceGame)
    m,n=a.shape;game.counts=[m+1,n+1]
    game.E=[csr_matrix(np.r_[np.r_[1.,np.zeros(k)][None,:],
                               np.r_[-1.,np.ones(k)][None,:]]) for k in (m,n)]
    game.cells=[{(0,0):Cell(0,0,0,tuple(range(1,k+1)),tuple(range(k)),1.)}
                for k in (m,n)]
    game.shift=1.-min(float(a.min()),float(b.min()))
    game.upper=game.shift+max(float(a.max()),float(b.max()))
    game.A=[]
    for payoff in (a,b):
        matrix=np.zeros((m+1,n+1));matrix[1:,1:]=payoff+game.shift
        game.A.append(csr_matrix(matrix))
    result,info=game.solve(seconds)
    if result is None:return None,info
    x,y=result[0][1:],result[1][1:]
    x=np.maximum(x,0);x/=x.sum();y=np.maximum(y,0);y/=y.sum()
    gaps=[float(np.max(a@y)-x@a@y),float(np.max(x@b)-x@b@y)]
    info['restricted_regrets']=gaps
    if max(gaps)>1e-9:return None,info
    return (x,y),info


def best_response(game,p,opponent):
    target=np.zeros(game.E[p].shape[0]);target[0]=1.
    coefficient=game.A[p]@opponent if p==0 else game.A[p].T@opponent
    result=linprog(-coefficient,A_eq=game.E[p],b_eq=target,
        bounds=(0,1),method='highs',options=dict(primal_feasibility_tolerance=1e-10,
                                               dual_feasibility_tolerance=1e-10))
    if not result.success:raise ValueError(f'Sequence LP BR failed: {result.message}')
    return result.x,float(-result.fun)


def solve(game,seconds=30.,max_iterations=128,epsilon=1e-11):
    start=time.monotonic();events=[]
    game.red.install()
    initial=[game.realization(game.tree.policy,p) for p in range(2)]
    plans=[[best_response(game,p,initial[1-p])[0]] for p in range(2)]
    for iteration in range(max_iterations):
        left=seconds-(time.monotonic()-start)
        if left<=0:return None,dict(status='timeout',events=events,elapsed_seconds=time.monotonic()-start)
        r0=np.stack(plans[0]);r1=np.stack(plans[1])
        a=(r0@game.A[0]@r1.T)-game.shift
        b=(r0@game.A[1]@r1.T)-game.shift
        mixed,meta=matrix_nash(a,b,seconds=min(left,5.))
        if mixed is None:return None,dict(status='restricted_nash_unavailable',events=events,meta=meta)
        realizations=[mixed[p]@r for p,r in enumerate((r0,r1))]
        br=[best_response(game,p,realizations[1-p]) for p in range(2)]
        values=[float(realizations[0]@game.A[p]@realizations[1]) for p in range(2)]
        gaps=[br[p][1]-values[p] for p in range(2)]
        events.append(dict(iteration=iteration,plans=list(a.shape),gaps=gaps,
                           meta_seconds=meta['elapsed_seconds']))
        if max(gaps)<=epsilon:
            return realizations,dict(status='full_sequence_own_nash',events=events,
                elapsed_seconds=time.monotonic()-start,
                algorithm=VERSION,sequences=game.counts,sparse_game_bytes=game.sparse_bytes())
        added=0
        for p in range(2):
            if gaps[p]>epsilon:
                r=br[p][0]
                if any(np.allclose(r,old,atol=1e-10,rtol=0) for old in plans[p]):
                    continue
                plans[p].append(r);added+=1
        if not added:return None,dict(status='numerical_stall',events=events)
    return None,dict(status='iteration_limit',events=events)
