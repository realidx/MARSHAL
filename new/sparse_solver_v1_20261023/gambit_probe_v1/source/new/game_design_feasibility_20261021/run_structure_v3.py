"""Broader two-player goal topology, original query menu, fresh fixed seeds."""
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import sys

from new.game_design_feasibility_20261021.run import write
from new.game_design_feasibility_20261021.run_resource_v2 import one,OPTIONS,ROOT


def main():
    out=Path('new/game_design_feasibility_20261021/sweep_structure_v3')
    out.mkdir(parents=True,exist_ok=False)
    parent=Path('new/game_design_feasibility_20261021/sweep_resource_v2/pipeline_snapshot.json')
    previous=json.loads(parent.read_text())
    configs=[dict(players=2,actions=[2,2],goals=g,hidden=2,rounds=2,
        query_limit=1,offer_limit=1,query_targets='all') for g in (3,4)]
    jobs=[(i,c,2026102202+s,out) for i,(c,s) in enumerate((c,s) for c in configs for s in range(2))]
    files=list(previous['sources'])+['new/game_design_feasibility_20261021/run_structure_v3.py']
    hashes={p:sha256((ROOT/p).read_bytes()).hexdigest() for p in files}
    for p in hashes:
        dst=out/'source'/p;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/p,dst)
    snapshot=dict(version='parameterized-native-feasibility-structure-v3',status='launched-not-completed',
        parent='parameterized-native-feasibility-resource-v2',actual_argv=sys.argv,
        changes=['Two commitments per player','3/4 goals to broaden structural families',
                 'New fixed seeds 2026102202/2026102203','Original all-target investigation menu retained'],
        options=OPTIONS,workers=2,jobs=len(jobs),configurations=configs,seeds=[2026102202,2026102203],
        sources=hashes,parent_run_sha256=sha256(parent.read_bytes()).hexdigest(),
        environment=previous['environment'],
        current_thread_environment={k:os.environ.get(k,'NOT_RECORDED') for k in previous['environment']['threads']},
        unchanged_contract='Same unconditioned independent uniform preference generator, budgets, terminal-only solve, independent audit, no seed replacement; no new S/D/model/prompt/training')
    write(out/'pipeline_snapshot.json',snapshot)
    rows=[]
    with ProcessPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(one,j) for j in jobs]):
            row=f.result();rows.append(row)
            print(json.dumps({k:row.get(k) for k in ('index','status','reason','elapsed_seconds')}),flush=True)
    write(out/'results.json',sorted(rows,key=lambda r:r['index']))
    write(out/'COMPLETE.json',dict(completed=len(rows),expected=len(jobs),
        source_identity_verified=all(sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in hashes.items()),
        snapshot_sha256=sha256((out/'pipeline_snapshot.json').read_bytes()).hexdigest()))


if __name__=='__main__':main()
