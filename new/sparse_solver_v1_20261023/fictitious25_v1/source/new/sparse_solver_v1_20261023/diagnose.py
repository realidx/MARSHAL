"""Inspect a saved native candidate without changing its off-path beliefs."""
import argparse
from pathlib import Path
import time

import numpy as np

from .common import parents,sha,snapshot,write
from .probe import build
from .run import diagnostics
from training.strategic_slices.equilibrium import _reach,_means


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--reference',required=True,type=Path);parser.add_argument('--index',required=True,type=int)
    args=parser.parse_args();snapshot(args.output,dict(operation='saved native candidate diagnostic',
        reference=str(args.reference),reference_sha256=sha(args.reference),index=args.index,
        horizon='native terminal',acceptance='unchanged'))
    tree=build(parents()[args.index]);tree.deadline=time.monotonic()+60
    with np.load(args.reference) as data:flat=data['probabilities']
    offset=0
    for p in tree.policy:
        if p is not None:p[:]=flat[offset:offset+p.size].reshape(p.shape);offset+=p.size
    assert offset==len(flat)
    _,audit,summary=diagnostics(tree)
    values=tree.evaluate();reaches={p:_reach(tree,p) for p in range(tree.n)}
    failures=audit['local_policy_audit']['own_failures']+audit['local_policy_audit']['failures']
    rows=[]
    for f in failures:
        i,c,p=f['index'],f['cell'],f['player'];e=tree.entries[i];ids=tree.information_groups[i][c]
        means=_means(tree,values,reaches[p],i,ids)
        rows.append(dict(f,index=i,history=[v.to_dict() for v in e.node.state.transcript],
            actions=[a.to_dict() for a in e.actions],private_type=list(tree.worlds[ids[0]][p]),
            probabilities=tree.policy[i][:,ids[0]].tolist(),Q=means.tolist(),
            counterfactual_mass=float(reaches[p][i][ids].sum())))
    write(args.output/'diagnosis.json',dict(summary=summary,failures=rows))
    print(summary,flush=True)


if __name__=='__main__':main()
