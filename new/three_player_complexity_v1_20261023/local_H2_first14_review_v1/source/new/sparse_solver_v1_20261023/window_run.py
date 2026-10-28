"""Apply the repaired solver uniformly to the previously approved finite window.

This is NOT a per-failure terminal fallback. Every one of the same100 parents
uses the same entrance-anchored next-own-proposal boundary and commitment score.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path
import shutil
import time

from .common import ROOT,parents,sha,snapshot,write
from .engine import ReducedEngine
from .run import repair_offpath
from new.decision_window_v1_20261022.window import DecisionWindow
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.common import save_reference


def worker(parent,output):
    index=parent['index'];start=time.monotonic();row=dict(index=index,parent_id=parent['id'])
    path=output/'cases'/str(index);path.mkdir(parents=True)
    try:
        rules=StrategicRules(parent['raw'])
        tree=DecisionWindow(rules,rules.initial(),rules.worlds,
            world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),
            max_nodes=100000,seconds=30)
        engine=ReducedEngine(tree);tree.deadline=time.monotonic()+30
        ok,info,_=engine.iterate(seconds=30);row.update(solver=info,nodes=len(tree.entries),
            worlds=tree.w,horizon=tree.horizon,cutoff_leaves=len(tree.cutoff_leaves))
        row['status']='candidate_unavailable'
        if ok:
            checked,diagnostic=repair_offpath(tree,8);row['native_diagnostics']=diagnostic
            if checked is not None:
                row.update(status='certified_bounded',certificate=checked['certificate'],
                    native_audit=tree.audit_native(),original_terminal_oracle=False)
                save_reference(path/'reference.npz',tree);row['reference_sha256']=sha(path/'reference.npz')
    except Exception as exc:row.update(status='error',error=f'{type(exc).__name__}: {exc}')
    row['elapsed_seconds']=time.monotonic()-start;write(path/'result.json',row)
    print(dict(index=index,status=row['status']),flush=True);return row


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    horizon=ROOT/'new/decision_window_v1_20261022/window.py'
    snapshot(args.output,dict(backend='reduced-inertia-bounded-v1',indices=list(range(100)),
        workers=args.workers,seconds=30,build_seconds=30,audit_seconds=60,max_nodes=100000,
        epsilon=1e-8,repair_passes=8,initialization='uniform/first/last ordered/synchronous',
        all_players_same_solver=True,horizon='1RR plus next focal proposal and complete response; native terminal if earlier',
        boundary='binding commitment utility only; no continuation estimate',
        horizon_source_sha256=sha(horizon),horizon_semantics_parent='strategic-game-design-v2-window',
        original_terminal_oracle=False,Q='NOT_COMPUTED',S='NOT_COMPUTED',D='NOT_MEASURED'))
    saved=args.output/'pipeline_snapshot.json';meta=json.loads(saved.read_text())
    rel=str(horizon.relative_to(ROOT));meta['source_hashes'][rel]=sha(horizon);write(saved,meta)
    dest=args.output/'source'/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(horizon,dest)
    rows=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(worker,parent,args.output) for parent in parents()]
        for f in as_completed(futures):
            rows.append(f.result());rows.sort(key=lambda r:r['index']);write(args.output/'results.json',rows)
    write(args.output/'COMPLETE.json',dict(results=len(rows),
        certified=sum(r['status']=='certified_bounded' for r in rows),
        unavailable=[r['index'] for r in rows if r['status']!='certified_bounded'],
        pipeline_snapshot_sha256=sha(saved),results_sha256=sha(args.output/'results.json')))


if __name__=='__main__':main()
