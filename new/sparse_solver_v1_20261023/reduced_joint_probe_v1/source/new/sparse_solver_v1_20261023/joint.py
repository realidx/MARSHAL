"""Joint refinement of small cycles left after pointwise backward elimination."""
import time

import numpy as np
from scipy.optimize import root

from training.strategic_slices.equilibrium import _JointResidual

VERSION='reduced-inertia-active-joint-continuation-v1'


def solve(engine,seconds=60,max_evaluations=400):
    start=time.monotonic();tree=engine.tree;tree.deadline=start+seconds
    ok,front,alternatives=engine.iterate(seconds=min(seconds*.25,15.))
    if ok:return True,dict(backend=VERSION,front=front,status='BR_candidate')
    events=[]
    for alt in sorted(alternatives,key=lambda a:a['score']):
        for i,p in alt['final'].items():tree.policy[i]=p.copy()
        histories=alt['history'];cells=set()
        for i in engine.active:
            for c,ids in enumerate(tree.information_groups[i]):
                if (i,c) in engine.red.fixed:continue
                if any(not np.allclose(h[i][:,ids[0]],histories[-1][i][:,ids[0]],atol=1e-10,rtol=0)
                       for h in histories[:-1]):cells.add((i,c))
        cells.update(engine.local_screen()['failed'])
        supports={}
        for i,c in cells:
            ids=tree.information_groups[i][c]
            support=set()
            for h in histories:support.update(int(a) for a in np.flatnonzero(h[i][:,ids[0]]>1e-9))
            supports[i,c]=tuple(sorted(support))
        for i in engine.active:tree.policy[i]=np.mean([h[i] for h in histories],axis=0)
        for attempt in range(6):
            if time.monotonic()-start>=seconds:return None,dict(backend=VERSION,front=front,status='timeout',events=events)
            tree._check()
            if not cells:break
            residual=_JointResidual(tree,cells,action_supports=supports)
            method='hybr' if len(residual.x0)<=256 else 'krylov'
            options=(dict(xtol=1e-11,maxfev=max_evaluations*len(residual.x0)) if method=='hybr'
                     else dict(fatol=1e-12,maxiter=max_evaluations,line_search='armijo'))
            result=root(residual.residual,residual.x0,method=method,options=options)
            tree.policy=residual.normalized_policy(result.x)
            # Tiny numerical remnants are candidate-only; independent audits
            # decide actual support and native private-information deviations.
            for i,c in cells:
                ids=tree.information_groups[i][c];p=tree.policy[i][:,ids[0]].copy()
                p[p<1e-9]=0.
                if p.sum()>0:tree.policy[i][:,ids]=(p/p.sum())[:,None]
            own_before=engine.local_screen()
            for _ in range(3):
                if not engine.repair_responses():break
            local=engine.local_screen()
            events.append(dict(initialization=alt['initialization'],synchronous=alt['synchronous'],
                attempt=attempt,cells=len(cells),variables=len(result.x),optimizer_success=bool(result.success),
                numerical_residual=float(np.max(np.abs(residual.residual(result.x)))),
                own_before_tie_projection=own_before['worst'],
                local_gain=local['worst'],tie_failures=local['ties'],failed=len(local['failed'])))
            if not local['failed']:
                return True,dict(backend=VERSION,front=front,status='joint_local_candidate',events=events)
            additions=set(local['failed'])
            grew=False
            for key in additions:
                complete=tuple(range(len(tree.entries[key[0]].actions)))
                if supports.get(key)!=complete:grew=True
                supports[key]=complete
            new=additions-cells;cells.update(additions)
            if not new and not grew:break
    return None,dict(backend=VERSION,front=front,status='joint_unavailable',events=events)
