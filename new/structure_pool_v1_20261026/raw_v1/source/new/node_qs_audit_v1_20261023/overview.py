"""Distinguish forced moves, current-action S and continuation-only effects."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path

import numpy as np

from .run import snapshot
from new.sparse_solver_v1_20261023.common import write,sha


def inspect_case(path):
    scopes={s:defaultdict(float) for s in ('counterfactual','on_reference')}
    witnesses={}
    with gzip.open(path/'labels.jsonl.gz','rt') as stream:
        for line in stream:
            r=json.loads(line)
            if r['counterfactual_mass']==0:continue
            active=['counterfactual']+(['on_reference'] if r['reference_mass']>0 else [])
            flags=dict(contexts=1,forced=len(r['actions'])==1,
                nonforced=len(r['actions'])>1,
                nonforced_zero_own_span=len(r['actions'])>1 and r['span']<=1e-8,
                nonforced_zero_own_span_with_social_rule=len(r['actions'])>1 and r['span']<=1e-8 and len(r['optimal'])<len(r['own_optimal']),
                proposal_nonforced=r['phase']=='proposal' and len(r['actions'])>1,
                proposal_nonforced_zero_span=r['phase']=='proposal' and len(r['actions'])>1 and r['span']<=1e-8)
            for channel in ('private','history'):
                items=[x for x in r['S_items'] if x['omitted'][0]==channel]
                positive=[x for x in items if x['S']>1e-8]
                immediate=[]
                for item in positive:
                    regret=max(0.,max(r['Q'])-float(np.array(item['omitted_action_probabilities'])@r['Q']))
                    assert regret<=item['S']+1e-7
                    immediate.append(regret)
                    if regret>1e-8:
                        name=channel+'_entry_action'
                        if name not in witnesses or regret>witnesses[name]['entry_action_regret']:
                            witnesses[name]=dict(node=r['node'],cell=r['cell'],S=item['S'],entry_action_regret=regret,
                                reference_mass=r['reference_mass'],omitted=item['omitted'],Q=r['Q'],
                                masked_action_probabilities=item['omitted_action_probabilities'])
                flags[channel+'_eligible']=bool(items)
                flags[channel+'_S_positive']=bool(positive)
                flags[channel+'_entry_action_positive']=any(x>1e-8 for x in immediate)
                flags[channel+'_continuation_only']=bool(positive) and not any(x>1e-8 for x in immediate)
                flags[channel+'_S_positive_mass']=r['reference_mass']*bool(positive)
                flags[channel+'_entry_action_positive_mass']=r['reference_mass']*any(x>1e-8 for x in immediate)
            for s in active:
                for k,value in flags.items():scopes[s][k]+=value
                scopes[s]['expected_reference_decisions']+=r['reference_mass']
                scopes[s]['reference_mass_weighted_uniform_action_regret']+=r['reference_mass']*(max(r['Q'])-float(np.mean(r['Q'])))
    return dict(scopes={s:dict(v) for s,v in scopes.items()},witnesses=witnesses)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    snapshot(args.output,dict(operation='Extra label interpretation; unchanged underlying labels',
        input_run=str(args.run),input_snapshot_sha256=sha(args.run/'pipeline_snapshot.json'),
        input_results_sha256=sha(args.run/'results.json'),
        entry_action_regret='max Q - omitted root action probabilities dot full-information Q',
        S='same full continuation omission loss; entry_action_regret is additional diagnostic',
        positive_threshold=1e-8,forced='one legal action, separated from own-payoff ties',
        model_D='NOT_MEASURED'),{})
    rows=json.loads((args.run/'results.json').read_text());cases=[]
    for r in rows:
        if r['status']!='measured':continue
        detail=inspect_case(args.run/'cases'/str(r['index']))
        cases.append(dict(index=r['index'],players=r['players'],**detail))
    report={}
    for size in ('all',2,3):
        selected=cases if size=='all' else [r for r in cases if r['players']==size]
        report[str(size)]={}
        for scope in ('counterfactual','on_reference'):
            totals=defaultdict(float)
            for r in selected:
                for k,v in r['scopes'][scope].items():totals[k]+=v
            keys=['private_S_positive','history_S_positive','private_entry_action_positive','history_entry_action_positive']
            report[str(size)][scope]=dict(totals=dict(totals),
                parents={k:[r['index'] for r in selected if r['scopes'][scope][k]>0] for k in keys})
    write(args.output/'OVERVIEW.json',dict(report=report,cases=cases))
    write(args.output/'COMPLETE.json',dict(overview_sha256=sha(args.output/'OVERVIEW.json'),
        snapshot_sha256=sha(args.output/'pipeline_snapshot.json')))
    print(dict(games=len(cases),done=True))


if __name__=='__main__':main()
