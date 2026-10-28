"""Independent reload audit for the uniformly bounded research references."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path
import time

import numpy as np

from .common import ROOT,parents,sha,snapshot,write
from new.decision_window_v1_20261022.window import DecisionWindow
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.equilibrium import certify_policy


def check(parent,result,run):
    index=parent['index'];rules=StrategicRules(parent['raw'])
    tree=DecisionWindow(rules,rules.initial(),rules.worlds,
        world_weights=world_weights(rules.worlds,parent['raw']['background_prior']),max_nodes=100000,seconds=30)
    path=run/'cases'/str(index)/'reference.npz';assert sha(path)==result['reference_sha256']
    with np.load(path) as data:flat=data['probabilities']
    offset=0
    for p in tree.policy:
        if p is not None:p[:]=flat[offset:offset+p.size].reshape(p.shape);offset+=p.size
    assert offset==len(flat);tree.deadline=time.monotonic()+60
    result=certify_policy(tree,epsilon=1e-8);assert result is not None,tree.equilibrium_audit
    return dict(index=index,status='independently_reloaded_bounded',
        reference_sha256=sha(path),certificate=result['certificate'],native_audit=tree.audit_native(),
        original_terminal_oracle=False)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();meta=json.loads((args.run/'pipeline_snapshot.json').read_text())
    assert all(sha(ROOT/p)==h for p,h in meta['source_hashes'].items())
    chosen=[r for r in json.loads((args.run/'results.json').read_text()) if r['status']=='certified_bounded']
    snapshot(args.output,dict(operation='independent bounded reload; no solve/repair',
        run=str(args.run),pipeline_snapshot_sha256=sha(args.run/'pipeline_snapshot.json'),
        results_sha256=sha(args.run/'results.json'),indices=[r['index'] for r in chosen],
        workers=args.workers,epsilon=1e-8,audit_seconds=60,
        horizon_source_sha256=sha(ROOT/'new/decision_window_v1_20261022/window.py')))
    rows=[];pool=parents()
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(check,pool[r['index']],r,args.run) for r in chosen]
        for f in as_completed(futures):
            rows.append(f.result());rows.sort(key=lambda r:r['index']);write(args.output/'results.json',rows)
    write(args.output/'COMPLETE.json',dict(verified=len(rows),passed=True,source_hashes_matched=True,
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json'),
        results_sha256=sha(args.output/'results.json')))
    print(dict(verified=len(rows),passed=True),flush=True)


if __name__=='__main__':main()
