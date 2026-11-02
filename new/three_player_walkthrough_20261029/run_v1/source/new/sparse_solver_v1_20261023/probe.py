"""Structural feasibility before choosing a sparse equilibrium backend."""
import argparse
import time

from new.sparse_solver_v1_20261023.common import snapshot, parents, write
from new.sparse_solver_v1_20261023.reduction import Reduction
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow


def build(parent, seconds=30):
    rules = StrategicRules(parent['raw'])
    return BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
        lookahead_rr=3, max_nodes=100000, seconds=seconds,
        world_weights=world_weights(rules.worlds, parent['raw']['background_prior']))


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--output', required=True, type=__import__('pathlib').Path)
    parser.add_argument('--indices', default='6,9,34,74,95')
    args=parser.parse_args()
    indices=list(map(int,args.indices.split(',')))
    snapshot(args.output,dict(indices=indices,horizon='native terminal',
        operation='pointwise backward reduction dimensions only',
        build_seconds=30, model='NOT_USED', solver='NOT_RUN',
        elimination='pointwise own dominance; response ties pointwise others sum; no history merging'))
    pool=parents();results=[]
    for index in indices:
        start=time.monotonic();tree=build(pool[index]);red=Reduction(tree)
        row=dict(index=index,nodes=len(tree.entries),worlds=tree.w,
            elapsed_seconds=time.monotonic()-start,**red.dimensions())
        results.append(row);write(args.output/'results.json',results)
        print(row,flush=True)


if __name__=='__main__':main()
