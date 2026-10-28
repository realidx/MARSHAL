"""Aggregate measured games without replacing missing labels by zeros."""
import argparse
from pathlib import Path
import numpy as np
import json

from .run import snapshot
from new.sparse_solver_v1_20261023.common import write, sha


def aggregate(rows,scope):
    stats=[r['summary'][scope] for r in rows]
    sums={k:sum(s[k] for s in stats) for k in stats[0] if isinstance(stats[0][k],int)}
    lists={k:sorted(r['index'] for r in rows if r['summary'][scope][k]>0)
           for k in ('query_strictly_better','private_S_positive','history_S_positive',
                     'optimal_offer_type_dependent','static_dynamic_offer_disjoint','response_social_tie_matters')}
    quantiles={}
    for field in ('proposal_spans','positive_distinct_gaps'):
        data=[v for s in stats for v in s[field]]
        quantiles[field]=dict(zip(['min','p25','median','p75','max'],np.quantile(data,[0,.25,.5,.75,1]).tolist())) if data else None
    return dict(counts=sums,parent_indices=lists,parent_counts={k:len(v) for k,v in lists.items()},
        max_private_S=max(s['max_private_S'] for s in stats),
        max_history_S=max(s['max_history_S'] for s in stats),
        max_query_gap=max((s['max_query_gap'] for s in stats if s['max_query_gap'] is not None),default=None),
        max_BR_vs_ref_Q_difference=max(s['max_BR_vs_ref_Q_difference'] for s in stats),quantiles=quantiles)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    snapshot(args.output,dict(operation='Aggregate all measured games and expose missing coverage',
        input_run=str(args.run),input_snapshot_sha256=sha(args.run/'pipeline_snapshot.json'),
        input_results_sha256=sha(args.run/'results.json'),positive_threshold=1e-8),{})
    rows=json.loads((args.run/'results.json').read_text());good=[r for r in rows if r['status']=='measured']
    result=dict(measured=len(good),errors=[r['index'] for r in rows if r['status']!='measured'])
    for size in ('all',2,3):
        selected=good if size=='all' else [r for r in good if r['players']==size]
        result[str(size)]=dict(games=len(selected),all_information_cells=sum(r['summary']['all_cells'] for r in selected),
            zero_counterfactual_cells=sum(r['summary']['zero_CF_cells'] for r in selected),
            counterfactual=aggregate(selected,'counterfactual'),on_reference=aggregate(selected,'on_reference'))
    result['root_query_positive_parents']=[]
    for r in good:
        path=args.run/'cases'/str(r['index'])/'examples.json'
        # Root-specific count is computed from full labels, not capped examples.
        import gzip
        with gzip.open(args.run/'cases'/str(r['index'])/'labels.jsonl.gz','rt') as stream:
            roots=[json.loads(line) for line in stream if '"node":0,' in line]
        if any((x['query_gap'] or 0)>1e-8 for x in roots):result['root_query_positive_parents'].append(r['index'])
    write(args.output/'ANALYSIS.json',result)
    write(args.output/'COMPLETE.json',dict(analysis_sha256=sha(args.output/'ANALYSIS.json'),
        snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
