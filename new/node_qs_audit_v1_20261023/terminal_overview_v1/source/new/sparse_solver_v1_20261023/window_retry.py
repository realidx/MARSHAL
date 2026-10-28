"""Same bounded game/certificate; public player-order candidate retries."""
import argparse
from itertools import permutations
from pathlib import Path
import time

import numpy as np

from .common import ROOT,parents,sha,snapshot,write
from .orders import OrderedEngine
from .run import repair_offpath
from .joint import solve as joint_solve
from new.decision_window_v1_20261022.window import DecisionWindow
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.common import save_reference


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--indices',default='46,60');args=parser.parse_args()
    indices=list(map(int,args.indices.split(',')))
    snapshot(args.output,dict(operation='bounded candidate retries; same game and certificate',
        indices=indices,orders='all player permutations in lexicographic order',
        seconds_per_order=15,seconds_joint=60,epsilon=1e-8,build_seconds=30,audit_seconds=60,
        repair_passes=8,horizon='same v2 next-own-proposal',
        horizon_source_sha256=sha(ROOT/'new/decision_window_v1_20261022/window.py')))
    rows=[];pool=parents()
    for index in indices:
        start=time.monotonic();parent=pool[index];rules=StrategicRules(parent['raw'])
        tree=DecisionWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),max_nodes=100000,seconds=30)
        row=dict(index=index,parent_id=parent['id'],status='candidate_unavailable',attempts=[])
        try:
            for order in permutations(range(tree.n)):
                for p in tree.policy:
                    if p is not None:p[:]=1./len(p)
                engine=OrderedEngine(tree,list(order));tree.deadline=time.monotonic()+15
                ok,info,_=engine.iterate(seconds=15)
                row['attempts'].append(dict(order=list(order),stage='inertia',search=info))
                if not ok:continue
                checked,diagnostic=repair_offpath(tree,8)
                if checked is not None:break
            else:
                for p in tree.policy:
                    if p is not None:p[:]=1./len(p)
                engine=OrderedEngine(tree,list(range(tree.n)))
                ok,info=joint_solve(engine,seconds=60)
                row['attempts'].append(dict(stage='joint',search=info))
                checked,diagnostic=repair_offpath(tree,8) if ok else (None,[])
            if checked is not None:
                row.update(status='certified_bounded',certificate=checked['certificate'],
                    native_audit=tree.audit_native(),horizon=tree.horizon,nodes=len(tree.entries),
                    worlds=tree.w,original_terminal_oracle=False,native_diagnostics=diagnostic)
                path=args.output/'cases'/str(index);path.mkdir(parents=True,exist_ok=True)
                save_reference(path/'reference.npz',tree);row['reference_sha256']=sha(path/'reference.npz')
        except Exception as exc:row.update(status='error',error=f'{type(exc).__name__}: {exc}')
        row['elapsed_seconds']=time.monotonic()-start
        rows.append(row);write(args.output/'cases'/str(index)/'result.json',row);write(args.output/'results.json',rows)
        print(dict(index=index,status=row['status']),flush=True)


if __name__=='__main__':main()
