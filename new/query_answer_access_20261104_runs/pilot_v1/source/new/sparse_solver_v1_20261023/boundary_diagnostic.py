"""Keep raw/normalized/snapped candidates separate; never issue hidden labels."""
import argparse
from pathlib import Path
import time

import numpy as np
from scipy.optimize import root

from .common import parents,snapshot,write
from .engine import ReducedEngine
from .probe import build
from .run import diagnostics
from training.strategic_slices.equilibrium import _JointResidual
from training.strategic_slices.common import save_reference


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();snapshot(args.output,dict(operation='raw vs normalized vs snapped residual diagnostic',
        index=25,horizon='native terminal',epsilon=1e-8,candidate_snap=1e-9,
        front_seconds=15,solve_seconds=60,root_evaluations_per_variable=400,root_xtol=1e-11))
    tree=build(parents()[25]);engine=ReducedEngine(tree);tree.deadline=time.monotonic()+60
    _,front,alternatives=engine.iterate(seconds=15)
    alt=sorted(alternatives,key=lambda a:a['score'])[0];history=alt['history'];cells=set()
    for i,p in alt['final'].items():tree.policy[i]=p.copy()
    for i in engine.active:
        for c,ids in enumerate(tree.information_groups[i]):
            if (i,c) in engine.red.fixed:continue
            if any(not np.allclose(h[i][:,ids[0]],history[-1][i][:,ids[0]],atol=1e-10,rtol=0)
                   for h in history[:-1]):cells.add((i,c))
    cells.update(engine.local_screen()['failed']);supports={}
    for i,c in cells:
        ids=tree.information_groups[i][c];support=set()
        for h in history:support.update(int(a) for a in np.flatnonzero(h[i][:,ids[0]]>1e-9))
        supports[i,c]=tuple(sorted(support))
    for i in engine.active:tree.policy[i]=np.mean([h[i] for h in history],axis=0)
    residual=_JointResidual(tree,cells,action_supports=supports)
    answer=root(residual.residual,residual.x0,method='hybr',
                options=dict(xtol=1e-11,maxfev=400*len(residual.x0)))
    probabilities=np.concatenate([answer.x[start:start+k] for _,_,start,k in residual.offsets])
    row=dict(variables=len(answer.x),raw_residual=float(np.max(np.abs(residual.residual(answer.x)))),
        raw_min_probability=float(probabilities.min()),negative_probability_count=int((probabilities<0).sum()),
        raw_small_positive_probabilities=probabilities[(probabilities>0)&(probabilities<1e-9)].tolist())
    tree.policy=residual.normalized_policy(answer.x)
    _,audit,summary=diagnostics(tree);row['normalized_native']=summary
    save_reference(args.output/'normalized_candidate.npz',tree)
    for i,ids,_,_ in residual.offsets:
        p=tree.policy[i][:,ids[0]].copy();p[p<1e-9]=0.
        if p.sum()>0:tree.policy[i][:,ids]=(p/p.sum())[:,None]
    _,audit,summary=diagnostics(tree);row['snapped_native']=summary
    save_reference(args.output/'snapped_candidate.npz',tree)
    write(args.output/'diagnosis.json',row);print(row,flush=True)


if __name__=='__main__':main()
