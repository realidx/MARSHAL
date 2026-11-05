"""Hash-checked union of the disjoint original100 profile executions."""
from new import qs_action_profile_20261104 as m
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve()
    base=m.ROOT/'new/qs_action_profile_20261104_runs'
    runs=[base/'pilot_v1',base/'remaining_v1'];identities={};results=[];provenance={}
    requested=[]
    for run in runs:
        complete=json.loads((run/'COMPLETE.json').read_text())
        assert not complete['errors']
        assert complete['results_sha256']==m.sha(run/'results.json')
        assert complete['pipeline_snapshot_sha256']==m.sha(run/'pipeline_snapshot.json')
        snap=json.loads((run/'pipeline_snapshot.json').read_text())
        requested+=snap['resolved_config']['requested']
        for row in json.loads((run/'results.json').read_text()):
            i=row['index'];assert i not in identities and row['status']=='measured'
            path=run/'cases'/str(i)/'labels.jsonl.gz'
            assert m.sha(path)==row['labels_sha256']
            identities[i]=path;results.append(row)
            provenance[str(i)]=dict(path=str(path.relative_to(m.ROOT)),sha256=row['labels_sha256'])
    assert sorted(requested)==list(range(100))
    assert sorted(identities)==[i for i in range(100)if i!=25]
    m.VERSION='qs-action-profile-summary-v1'
    m.REG=m.ROOT/'examples/strategic_slices/versions/qs_action_profile_summary_v1_20261104/SNAPSHOT.json'
    m.snapshot(args.output,dict(operation='Aggregate completed disjoint two runs; no game/reference/label/model change',
        inputs={str(run.relative_to(m.ROOT)):dict(COMPLETE=m.sha(run/'COMPLETE.json'),snapshot=m.sha(run/'pipeline_snapshot.json'))for run in runs},
        label_files=provenance,requested_parents=100,measured_parents=99,missing=[25],
        numeric_positive_tolerance=m.EPS,workers=1,threads=1,examples='First in original parent/node/cell/item order per condition, not model difficulty ranking',
        all_source_slices='NOT_SELECTED',D='NOT_MEASURED'),{})
    totals=Counter();strata=defaultdict(Counter);parents_by_property=defaultdict(list);examples={}
    for result in sorted(results,key=lambda r:r['index']):
        i=result['index']; parent=Counter();on_reference=Counter()
        with gzip.open(identities[i],'rt')as stream:
            for line in stream:
                row=json.loads(line)
                if row['counterfactual_mass']<=0:
                    parent['zero_CF_contexts']+=1;continue
                items=row['S_items'];parent['contexts']+=1;parent['items']+=len(items)
                flags=dict(positive_S=any(x['S']>m.EPS for x in items),
                    changed_distribution=any(x['policy_total_variation']>m.EPS for x in items),
                    changed_relative_Q=any(x['relative_Q_change_Linf']>m.EPS for x in items),
                    any_current_loss=any(x['own_current_loss']>m.EPS for x in items),
                    any_future_loss=any(x['own_future_loss']>m.EPS for x in items),
                    only_future_S=any(x['S']>m.EPS and x['own_current_loss']<=m.EPS for x in items),
                    zero_S_changed_Q=bool(items)and all(x['S']<=m.EPS for x in items)and any(x['relative_Q_change_Linf']>m.EPS for x in items),
                    zero_S_changed_distribution=bool(items)and all(x['S']<=m.EPS for x in items)and any(x['policy_total_variation']>m.EPS for x in items))
                for k,v in flags.items():
                    parent[k+'_contexts']+=int(v)
                    strata[f"players{result['players']}/{row['phase']}"][k+'_contexts']+=int(v)
                    if row['reference_mass']>0:on_reference[k+'_contexts']+=int(v)
                strata[f"players{result['players']}/{row['phase']}"]['contexts']+=1
                if row['reference_mass']>0:on_reference['contexts']+=1
                for item in items:
                    conditions=dict(zero_S_policy_switch=item['S']<=m.EPS and item['policy_total_variation']>m.EPS,
                        zero_S_Q_change_same_policy=item['S']<=m.EPS and item['relative_Q_change_Linf']>m.EPS and item['policy_total_variation']<=m.EPS,
                        positive_future_loss=item['own_future_loss']>m.EPS,
                        response_social_loss=(item.get('response_secondary_loss')or 0)>m.EPS)
                    for key,value in conditions.items():
                        if value and key not in examples:
                            examples[key]=dict(parent=i,node=row['node'],cell=row['cell'],phase=row['phase'],
                                reference_mass=row['reference_mass'],actions=row['actions'],Q=row['Q'],Q_others=row['Q_others'],
                                full_policy=row['canonical_full_action_probabilities'],item=item)
        for key,value in parent.items():
            if key.endswith('_contexts')and key!='zero_CF_contexts'and value>0:parents_by_property[key].append(i)
        totals.update(parent)
        m.write(args.output/'parent_summaries'/f'{i}.json',dict(index=i,players=result['players'],summary=dict(parent),on_reference=dict(on_reference)))
    m.write(args.output/'SUMMARY.json',dict(requested_parents=100,measured_parents=99,missing=[25],totals=dict(totals),
        strata={k:dict(v)for k,v in strata.items()},parents_by_property=dict(parents_by_property),
        source_contexts_are_not_independent_slices=True,model_D='NOT_MEASURED',candidate800='NOT_SELECTED'))
    m.write(args.output/'EXAMPLES.json',examples)
    m.write(args.output/'COMPLETE.json',dict(parent_labels_verified=99,missing=[25],all_old_Q_S_and_saved_omitted_policies_match=True,
        summary_sha256=m.sha(args.output/'SUMMARY.json'),examples_sha256=m.sha(args.output/'EXAMPLES.json'),
        pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
