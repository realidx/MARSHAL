"""Public alternative player update order; same objective and full certificate."""
import argparse
from pathlib import Path
import time

from .common import parents,sha,snapshot,write
from .engine import ReducedEngine
from .probe import build
from .run import repair_offpath
from training.strategic_slices.common import save_reference


class OrderedEngine(ReducedEngine):
    def __init__(self,tree,order):
        super().__init__(tree)
        if sorted(order)!=list(range(tree.n)):raise ValueError('Player permutation required')
        self.order=order

    def response(self,player):
        return super().response(self.order[player])


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--index',type=int,default=25);parser.add_argument('--seconds',type=float,default=60)
    parser.add_argument('--random-starts',type=int,default=0)
    args=parser.parse_args();parent=parents()[args.index]
    order=list(reversed(range(parent['configuration']['players'])))
    snapshot(args.output,dict(backend='reduced-inertia-reverse-order-v1',index=args.index,
        order=order,seconds=args.seconds,random_starts=args.random_starts,
        initialization='uniform/first/last, then dirichlet seeds 0..N-1',
        synchronous_also_tried=True,epsilon=1e-8,cycle_round_decimals=12,
        horizon='native terminal',repair_passes=8,build_seconds=30,audit_seconds=60))
    start=time.monotonic();row=dict(index=args.index,parent_id=parent['id'],order=order)
    try:
        tree=build(parent);engine=OrderedEngine(tree,order);engine.random_starts=args.random_starts
        tree.deadline=time.monotonic()+args.seconds+5
        ok,info,_=engine.iterate(seconds=args.seconds);row['solver']=info
        row['status']='candidate_unavailable'
        if ok:
            checked,diagnostic=repair_offpath(tree,8);row['native_diagnostics']=diagnostic
            row['status']='certified_native_terminal' if checked is not None else 'native_rejected'
            if checked is not None:
                row['certificate']=checked['certificate'];row['native_audit']=tree.audit_native()
                path=args.output/'cases'/str(args.index);path.mkdir(parents=True,exist_ok=True)
                save_reference(path/'reference.npz',tree);row['reference_sha256']=sha(path/'reference.npz')
    except Exception as exc:row.update(status='error',error=f'{type(exc).__name__}: {exc}')
    row['elapsed_seconds']=time.monotonic()-start
    write(args.output/'cases'/str(args.index)/'result.json',row);write(args.output/'results.json',[row])
    print({k:row[k] for k in ('index','status','elapsed_seconds')},flush=True)


if __name__=='__main__':main()
