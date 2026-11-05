"""Separate private answer use from the public/timing effect of INVESTIGATE.

This diagnostic starts BEFORE the answer is obtained. It supplements, and is
NOT renamed as, the current-node per-information-item S in metrics.py.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor,as_completed
import gzip
import json
from pathlib import Path
import time

import numpy as np

from .metrics import forest_response,Observations
from .run import inputs,snapshot
from new.sparse_solver_v1_20261023.common import parents,write,sha
from new.sparse_solver_v1_20261023.probe import build


def check(index,parent,identity,run,output):
    tree=build(parent,seconds=60)
    assert sha(identity['path'])==identity['sha256']
    with np.load(identity['path']) as data:flat=data['probabilities']
    offset=0
    for p in tree.policy:
        if p is not None:p[:]=flat[offset:offset+p.size].reshape(p.shape);offset+=p.size
    assert offset==len(flat);tree.deadline=float('inf')
    with gzip.open(run/'cases'/str(index)/'labels.jsonl.gz','rt') as stream:
        rows=[json.loads(line) for line in stream]
    result=[];observations={p:Observations(tree,p) for p in range(tree.n)}
    for r in rows:
        if r['counterfactual_mass']==0 or (r['query_gap'] or 0)<=1e-8:continue
        focal=r['actor'];i=r['node'];weights=np.zeros(tree.w)
        weights[r['world_ids']]=r['posterior']
        for ai,a in enumerate(r['actions']):
            if a.get('action')!='INVESTIGATE' or r['Q'][ai]<max(r['Q'])-1e-9:continue
            child=tree.entries[i].children[ai];mask=('private',a['player'],a['goal'])
            measured=forest_response(tree,focal,{child:weights},omitted=mask,observations=observations[focal])
            blind=float(weights@measured['values'][child][:,focal]);full=r['Q'][ai]
            gain=full-blind
            assert gain>=-1e-7,(index,i,full,blind)
            result.append(dict(index=index,node=i,cell=r['cell'],focal=focal,query=a,
                reference_mass=r['reference_mass'],counterfactual_mass=r['counterfactual_mass'],
                query_vs_nonquery_gap=r['query_gap'],V_query_with_answer=full,
                V_same_public_query_without_answer=blind,private_answer_access_gain=max(0.,gain),
                public_query_event_and_opponents_held_fixed=True))
    write(output/'cases'/str(index)/'diagnostics.json',result)
    print(dict(index=index,optimal_positive_query_contexts=len(result)),flush=True)
    return dict(index=index,players=parent['configuration']['players'],diagnostics=result)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--workers',type=int,default=2)
    args=parser.parse_args();rows=json.loads((args.run/'results.json').read_text())
    indices=[r['index'] for r in rows if r['status']=='measured' and r['summary']['counterfactual']['query_strictly_better']>0]
    identities=inputs('terminal')
    snapshot(args.output,dict(operation='Private answer acquisition contrast after same public query; NOT current-node S',
        input_run=str(args.run),input_results_sha256=sha(args.run/'results.json'),
        input_snapshot_sha256=sha(args.run/'pipeline_snapshot.json'),indices=indices,workers=args.workers,
        scope='Every own-optimal query at every positive-CF context with query strictly better than all nonqueries',
        own_information='Mask only this newly obtained answer throughout continuation; later new observations allowed',
        opponents='unchanged frozen reference',positive_tolerance=1e-8),{i:identities[i] for i in indices})
    pool=parents();output=[]
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        fs=[executor.submit(check,i,pool[i],identities[i],args.run,args.output) for i in indices]
        for future in as_completed(fs):
            output.append(future.result());output.sort(key=lambda r:r['index']);write(args.output/'results.json',output)
    report={}
    for size in ('all',2,3):
        selected=output if size=='all' else [r for r in output if r['players']==size]
        report[str(size)]={}
        for scope in ('counterfactual','on_reference'):
            ds=[d for r in selected for d in r['diagnostics'] if scope=='counterfactual' or d['reference_mass']>0]
            report[str(size)][scope]=dict(query_contexts=len(ds),
                positive_private_access=sum(d['private_answer_access_gain']>1e-8 for d in ds),
                no_private_access=sum(d['private_answer_access_gain']<=1e-8 for d in ds),
                positive_access_parents=sorted({d['index'] for d in ds if d['private_answer_access_gain']>1e-8}),
                query_positive_parents=sorted({d['index'] for d in ds}),
                max_private_access_gain=max((d['private_answer_access_gain'] for d in ds),default=0.))
    write(args.output/'ANALYSIS.json',report)
    write(args.output/'COMPLETE.json',dict(parents=len(output),analysis_sha256=sha(args.output/'ANALYSIS.json'),
        results_sha256=sha(args.output/'results.json'),snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
