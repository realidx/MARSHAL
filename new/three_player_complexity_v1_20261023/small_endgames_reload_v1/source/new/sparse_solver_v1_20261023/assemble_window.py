"""Explicit provenance-preserving assembly and independent100-reference audit."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path
import shutil

from .common import ROOT,parents,sha,snapshot,write,POOL_SHA
from .window_verify import check


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--primary',required=True,type=Path)
    parser.add_argument('--retries',type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--workers',type=int,default=2);args=parser.parse_args()
    origins=[args.primary]+([args.retries] if args.retries else [])
    source_runs=[];chosen={}
    for run in origins:
        meta=json.loads((run/'pipeline_snapshot.json').read_text())
        assert meta['data']['sha256']==POOL_SHA
        assert all(sha(ROOT/path)==digest for path,digest in meta['source_hashes'].items())
        assert meta['resolved_config']['horizon_source_sha256']==sha(ROOT/'new/decision_window_v1_20261022/window.py')
        source_runs.append(dict(path=str(run),pipeline_snapshot_sha256=sha(run/'pipeline_snapshot.json'),
            results_sha256=sha(run/'results.json')))
        for row in json.loads((run/'results.json').read_text()):
            if row['status']=='certified_bounded' and row['index'] not in chosen:
                chosen[row['index']]=(row,run)
    assert set(chosen)==set(range(100)),f'Missing bounded references: {set(range(100))-set(chosen)}'
    snapshot(args.output,dict(operation='explicit bounded reference collection and independent reload',
        sources=source_runs,selection='primary success first, retries only for primary missing; no replacement parents',
        indices=list(range(100)),workers=args.workers,epsilon=1e-8,build_seconds=30,audit_seconds=60,
        horizon='same v2 next-own-proposal boundary for all100',
        horizon_source_sha256=sha(ROOT/'new/decision_window_v1_20261022/window.py'),
        original_terminal_oracle=False,training_ready=False,Q='NOT_COMPUTED',S='NOT_COMPUTED',D='NOT_MEASURED'))
    pool=parents();index=[];rows=[]
    for i in range(100):
        result,run=chosen[i];assert result['parent_id']==pool[i]['id']
        origin=run/'cases'/str(i)/'reference.npz';assert sha(origin)==result['reference_sha256']
        dest=args.output/'cases'/str(i)/'reference.npz';dest.parent.mkdir(parents=True);shutil.copyfile(origin,dest)
        reference=dict(index=i,parent_id=result['parent_id'],status='certified_bounded',
            reference=str(dest.relative_to(args.output)),reference_sha256=sha(dest),
            source_run=str(run),source_pipeline_snapshot_sha256=sha(run/'pipeline_snapshot.json'),
            source_result_sha256=sha(run/'cases'/str(i)/'result.json'),
            candidate_solver=result.get('backend',result.get('solver',{}).get('status','recorded_in_source_result')),
            certificate=result['certificate'],horizon=result['horizon'],original_terminal_oracle=False)
        index.append(reference);write(dest.parent/'result.json',reference)
    write(args.output/'REFERENCE_INDEX.json',index)
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(check,pool[i],chosen[i][0],args.output) for i in range(100)]
        for f in as_completed(futures):
            rows.append(f.result());rows.sort(key=lambda r:r['index']);write(args.output/'INDEPENDENT_AUDIT.json',rows)
    write(args.output/'COMPLETE.json',dict(references=100,independently_verified=len(rows),passed=True,
        pool_sha256=POOL_SHA,original_terminal_oracle=False,Q_S_D_measured=False,training_ready=False,
        pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json'),
        reference_index_sha256=sha(args.output/'REFERENCE_INDEX.json'),
        independent_audit_sha256=sha(args.output/'INDEPENDENT_AUDIT.json')))
    print(dict(references=100,independently_verified=len(rows),passed=True),flush=True)


if __name__=='__main__':main()
