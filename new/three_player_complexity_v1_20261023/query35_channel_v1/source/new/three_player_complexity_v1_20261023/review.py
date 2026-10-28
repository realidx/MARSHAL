"""Independent LP checks on positive small-example S; no training selection."""
import argparse
import gzip
import json
from pathlib import Path
import numpy as np

from .common import snapshot,identity,write,sha
from .worker import tree_for,load
from new.node_qs_audit_v1_20261023.metrics import Observations
from new.node_qs_audit_v1_20261023.witness import sequence_lp
from training.strategic_slices.equilibrium import _reach


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--runs',nargs='+',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    snapshot(args.output,dict(operation='Independent LP/current-action check on max-S witnesses of prespecified small diagnostics',
        runs=[str(p) for p in args.runs],selection='one largest private/history S per measured job; not pool inclusion',
        social_constraints='LP relaxes response-secondary constraints for conservative bounds'),
        {str(i):identity(p/'results.json') for i,p in enumerate(args.runs)})
    checks=[];summaries=[]
    for run in args.runs:
        results=json.loads((run/'results.json').read_text())
        for result in results:
            if result.get('labels')!='MEASURED':continue
            folder=run/Path(result['result_path']).parent;request=json.loads((folder/'request.json').read_text())
            tree=tree_for(request['job'],request['config']);load(tree,folder/'reference.npz');tree.deadline=float('inf')
            with gzip.open(folder/'labels.jsonl.gz','rt') as stream:rows=list(map(json.loads,stream))
            summaries.append(dict(run=str(run),index=result['index'],original_index=result['original_index'],
                arm=result['arm'],nodes=result['nodes'],worlds=result['worlds'],summary=result['summary']))
            for channel in ('private','history'):
                possible=[(item['S'],r,item) for r in rows for item in r['S_items']
                    if item['omitted'][0]==channel and item['S']>1e-8]
                if not possible:continue
                _,chosen,item=max(possible,key=lambda x:(x[0],x[1]['reference_mass'],-x[1]['node']))
                focal=chosen['actor'];mask=tuple(item['omitted']);obs=Observations(tree,focal)
                key=obs.key(chosen['node'],chosen['world_ids'][0],mask)
                members=[r for r in rows if r['actor']==focal and
                    any(tuple(x['omitted'])==mask for x in r['S_items']) and obs.key(r['node'],r['world_ids'][0],mask)==key]
                reach=_reach(tree,focal);roots={}
                for r in members:roots.setdefault(r['node'],np.zeros(tree.w))[r['world_ids']]=reach[r['node']][r['world_ids']]
                lp=sequence_lp(tree,focal,roots,omitted=mask,observations=obs,
                    target=(chosen['node'],set(chosen['world_ids'])))
                total=sum(m.sum() for m in roots.values())
                own_measured=sum(r['counterfactual_mass']*next(x['V_omitted'] for x in r['S_items']
                    if tuple(x['omitted'])==mask) for r in members)/total
                assert abs(lp['V_omitted_LP']-own_measured)<1e-7
                full=max(chosen['Q']);lower=max(0.,full-lp['target_own_value_max']);upper=max(0.,full-lp['target_own_value_min'])
                assert lower-1e-7<=item['S']<=upper+1e-7
                checks.append(dict(run=str(run),index=result['index'],original_index=result['original_index'],arm=result['arm'],
                    node=chosen['node'],cell=chosen['cell'],channel=channel,S=item['S'],
                    entry_action_regret=item['entry_action_regret'],S_conservative_interval=[lower,upper],
                    LP_matches=True,**lp))
    write(args.output/'REVIEW.json',dict(checks=checks,summaries=summaries,
        scope='Local and reused full-parent evidence only; no all33 expansion efficacy or model-D claim'))
    write(args.output/'COMPLETE.json',dict(witnesses=len(checks),all_LP_checks_passed=True,
        positive_conservative_lower_bounds=sum(c['S_conservative_interval'][0]>1e-8 for c in checks),
        review_sha256=sha(args.output/'REVIEW.json'),pipeline_snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(dict(witnesses=len(checks),all_passed=True))


if __name__=='__main__':main()
