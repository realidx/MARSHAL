"""Separate capacity diagnostic; NEVER replace/modify the frozen100 parents."""
import argparse
from copy import deepcopy
from itertools import product
from pathlib import Path
import time

import numpy as np

from .common import parents,sha,snapshot,write
from .engine import ReducedEngine
from .run import repair_offpath
from new.strategic_game_v1_20261021.rules import StrategicRules
from training.b_sft.preference_contract import world_weights
from training.strategic_slices.bounded import BoundedPrivateWindow
from training.strategic_slices.common import save_reference


def variant(raw,target):
    raw=deepcopy(raw);supports=[]
    for p in range(raw['game']['n_players']):
        supports.append([sorted({r[g] for r in raw['type_catalogues'][str(p)]})
                         for g in range(len(raw['game']['goals']))])
    current=sum(len(s)>1 for row in supports for s in row);changed=[]
    for p,row in enumerate(supports):
        for g,s in enumerate(row):
            if current>=target:break
            if len(s)==1:row[g]=[-1,0,1];current+=1;changed.append((p,g))
    raw['type_catalogues']={str(p):[list(row) for row in product(*sup)] for p,sup in enumerate(supports)}
    return raw,changed


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();pool=parents()
    indices=[next(p['index'] for p in pool if p['configuration']==dict(players=3,goals=g,hidden=1)) for g in (3,4)]
    snapshot(args.output,dict(operation='separate capacity diagnostic; not frozen100 replacements',
        indices=indices,target_hidden_cells=[2,3],selection='first native three-player parent per goal count; first public cells lexicographically',
        changed='expand selected public preference support to independent avoid/neutral/want; no formal pool edit',
        horizon='native terminal',build_seconds=30,solve_seconds=30,audit_seconds=60,
        max_nodes=400000,epsilon=1e-8,repair_passes=4,backend='reduced inertia only'))
    rows=[]
    for index in indices:
        for hidden in (2,3):
            raw,changed=variant(pool[index]['raw'],hidden)
            path=args.output/'cases'/f'{index}-hidden{hidden}';path.mkdir(parents=True)
            write(path/'raw.json',raw)
            row=dict(original_index=index,hidden=hidden,changed_cells=changed,
                raw_sha256=sha(path/'raw.json'),formal_pool_changed=False)
            start=time.monotonic()
            try:
                r=StrategicRules(raw);tree=BoundedPrivateWindow(r,r.initial(),r.worlds,
                    lookahead_rr=3,max_nodes=400000,seconds=30,
                    world_weights=world_weights(r.worlds,raw['background_prior']))
                engine=ReducedEngine(tree);tree.deadline=time.monotonic()+30
                ok,info,_=engine.iterate(seconds=30);row.update(nodes=len(tree.entries),worlds=tree.w,
                    reduced_nodes=len(engine.nodes),solver=info,status='candidate_unavailable')
                if ok:
                    checked,diagnostic=repair_offpath(tree,4)
                    row['native_diagnostics']=diagnostic
                    if checked is not None:
                        row.update(status='certified_native_terminal',certificate=checked['certificate'],native_audit=tree.audit_native())
                        save_reference(path/'reference.npz',tree);row['reference_sha256']=sha(path/'reference.npz')
            except Exception as exc:row.update(status='error',error=f'{type(exc).__name__}: {exc}')
            row['elapsed_seconds']=time.monotonic()-start
            rows.append(row);write(path/'result.json',row);write(args.output/'results.json',rows)
            print({k:row[k] for k in ('original_index','hidden','status','elapsed_seconds')},flush=True)


if __name__=='__main__':main()
