"""Reload references; no search, repair, initialization or certificate reuse."""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import json
from pathlib import Path
import time

import numpy as np

from .common import parents,sha,snapshot,write
from .probe import build
from training.strategic_slices.equilibrium import certify_policy


def check(parent,result,path):
    start=time.monotonic();index=parent['index']
    tree=build(parent);reference=path/'cases'/str(index)/'reference.npz'
    assert sha(reference)==result['reference_sha256']
    with np.load(reference) as data:flat=data['probabilities']
    offset=0
    for p in tree.policy:
        if p is not None:p[:]=flat[offset:offset+p.size].reshape(p.shape);offset+=p.size
    assert offset==len(flat)
    tree.deadline=time.monotonic()+60
    certificate=certify_policy(tree,epsilon=1e-8)
    assert certificate is not None,tree.equilibrium_audit
    native=tree.audit_native();assert native['cutoff_leaves']==0
    return dict(index=index,status='independently_reloaded_native_terminal',
        source_result_sha256=sha(path/'cases'/str(index)/'result.json'),
        reference_sha256=sha(reference),certificate=certificate['certificate'],native_audit=native,
        elapsed_seconds=time.monotonic()-start)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args()
    original=json.loads((args.run/'pipeline_snapshot.json').read_text())
    assert all(sha(path)==digest for path,digest in original['source_hashes'].items()),'Source identity changed'
    results=json.loads((args.run/'results.json').read_text())
    chosen=[r for r in results if r['status']=='certified_native_terminal']
    snapshot(args.output,dict(operation='independent full native reload audit; no solve or repair',
        run=str(args.run),pipeline_snapshot_sha256=sha(args.run/'pipeline_snapshot.json'),
        results_sha256=sha(args.run/'results.json'),workers=args.workers,
        certified_indices=[r['index'] for r in chosen],epsilon=1e-8,audit_seconds=60))
    pool=parents();rows=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures=[executor.submit(check,pool[r['index']],r,args.run) for r in chosen]
        for f in as_completed(futures):
            rows.append(f.result());rows.sort(key=lambda r:r['index']);write(args.output/'results.json',rows)
    write(args.output/'COMPLETE.json',dict(verified=len(rows),passed=True,
        source_hashes_matched=True,pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json'),
        results_sha256=sha(args.output/'results.json')))
    print({'verified':len(rows),'passed':True},flush=True)


if __name__=='__main__':main()
