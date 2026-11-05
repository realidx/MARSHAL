"""Descriptive comparison for parent curation, not an800 selector or D run."""
from new import qs_action_profile_20261104 as m
import argparse
from collections import Counter,defaultdict
import gzip
import json
from pathlib import Path

from new.A2H2_structure_20261026 import canonical_geometry


PROPS=('positive_S','relative_Q_changed','distribution_changed','current_loss','future_loss',
       'zero_S_Q_changed','zero_S_distribution_changed','own_equivalent_policy_only',
       'no_common_own_optimal','no_common_protocol_optimal','social_omission_loss')


def summarize_case(key,arm,rows,result,job):
    c=Counter();on=Counter();skeletons={p:set()for p in PROPS};channels=defaultdict(Counter)
    examples={};stage=defaultdict(Counter)
    for row in rows:
        if row['counterfactual_mass']<=0:continue
        items=row['S_items'];c['contexts']+=1;c['items']+=len(items);c['reference_mass']+=row['reference_mass']
        pos=any(x['S']>m.EPS for x in items)
        flags=dict(positive_S=pos,
            relative_Q_changed=any(x['relative_Q_change_Linf']>m.EPS for x in items),
            distribution_changed=any(x['policy_total_variation']>m.EPS for x in items),
            current_loss=any(x['own_current_loss']>m.EPS for x in items),
            future_loss=any(x['own_future_loss']>m.EPS for x in items),
            zero_S_Q_changed=not pos and any(x['relative_Q_change_Linf']>m.EPS for x in items),
            zero_S_distribution_changed=not pos and any(x['policy_total_variation']>m.EPS for x in items),
            own_equivalent_policy_only=any(x['policy_total_variation']>m.EPS and x['S']<=m.EPS
                and x['relative_Q_change_Linf']<=m.EPS and set(a for a,p in enumerate(x['omitted_action_probabilities'])if p>m.EPS)<=set(row['optimal'])
                and (x.get('response_secondary_loss')or 0)<=m.EPS for x in items),
            no_common_own_optimal=any(not x['common_own_optimal']for x in items),
            no_common_protocol_optimal=any(not x['common_protocol_optimal']for x in items),
            social_omission_loss=any((x.get('response_secondary_loss')or 0)>m.EPS for x in items))
        for prop,yes in flags.items():
            c[prop]+=int(yes);c[prop+'_reference_mass']+=row['reference_mass']*yes
            stage[f'{row["phase"]}/turn{row["turn"]}'][prop]+=int(yes)
            if row['reference_mass']>0:on[prop]+=int(yes)
            if yes and 'physical_skeleton'in row:skeletons[prop].add(row['physical_skeleton'])
            if yes and prop in ('positive_S','zero_S_Q_changed','future_loss','social_omission_loss')and prop not in examples:
                examples[prop]=row
        c['action_Q_nonflat']+=row['span']>m.EPS
        c['query_available']+=row['query_gap']is not None
        c['query_strictly_better']+=row['query_gap']is not None and row['query_gap']>m.EPS
        c['response_protocol_matters']+=row['phase']=='response'and len(row['optimal'])<len(row['own_optimal'])
        c['no_omittable_information']+=not items
        for channel in ('private','history'):
            subset=[x for x in items if x['omitted'][0]==channel]
            channels[channel]['eligible_contexts']+=bool(subset)
            channels[channel]['positive_S']+=any(x['S']>m.EPS for x in subset)
            channels[channel]['relative_Q_changed']+=any(x['relative_Q_change_Linf']>m.EPS for x in subset)
            channels[channel]['distribution_changed']+=any(x['policy_total_variation']>m.EPS for x in subset)
        stage[f'{row["phase"]}/turn{row["turn"]}']['contexts']+=1
    g=job['raw']['game'];cat=job['raw']['type_catalogues']
    features=dict(actions=g['n_actions_per_player'],goals=len(g['goals']),binary_goals=sum(x['binary']for x in g['goals']),
        typed_geometry=canonical_geometry(job['raw'],True),
        public_all_want=[p for p,values in cat.items()if len(values)==1 and all(v==1 for v in values[0])])
    return dict(key=key,arm=arm,index=result['index'],original_index=job.get('original_index',result['index']),
        counts=dict(c),on_reference=dict(on),channels={k:dict(v)for k,v in channels.items()},
        stages={k:dict(v)for k,v in stage.items()},structural_features=features,
        physical_skeleton_counts=({k:len(v)for k,v in skeletons.items()}if 'physical_skeleton'in rows[0]else None)),examples


def aggregate(cases):
    total=Counter();parents=Counter();families={p:set()for p in PROPS};top={}
    for case in cases:
        total.update(case['counts'])
        for prop in PROPS:
            yes=case['counts'][prop]>0;parents[prop]+=yes
            if yes:families[prop].add(case['structural_features']['typed_geometry'])
    for prop in ('positive_S','relative_Q_changed','distribution_changed'):
        ranked=sorted(cases,key=lambda x:(-x['counts'][prop],x['key']))
        n=total[prop]
        top[prop]=dict(parents=[dict(key=x['key'],contexts=x['counts'][prop],
            physical_skeletons=None if x['physical_skeleton_counts']is None else x['physical_skeleton_counts'][prop])for x in ranked[:2]],
            top2_context_share=sum(x['counts'][prop]for x in ranked[:2])/n if n else None,
            equal_parent_positive_fraction=sum(x['counts'][prop]/x['counts']['contexts']for x in cases)/len(cases)if cases else None,
            reference_occupancy=total[prop+'_reference_mass']/total['reference_mass']if total['reference_mass']else None)
    return dict(measured_parents=len(cases),counts=dict(total),positive_parents=dict(parents),
        typed_geometry_families=len({x['structural_features']['typed_geometry']for x in cases}),
        positive_typed_geometry_families={k:len(v)for k,v in families.items()},concentration=top)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve();base=m.ROOT/'new/candidate_qs_profiles_20261104_runs'
    run_names=['pilot_v3','remaining_v3'];inputs={};selected=[];sources={};inventory=None
    for name in run_names:
        run=base/name;complete=json.loads((run/'COMPLETE.json').read_text());assert not complete['errors']
        assert m.sha(run/'results.json')==complete['results_sha256']
        assert m.sha(run/'pipeline_snapshot.json')==complete['pipeline_snapshot_sha256']
        inputs[name]=dict(snapshot=m.sha(run/'pipeline_snapshot.json'),complete=m.sha(run/'COMPLETE.json'))
        inv=json.loads((run/'INVENTORY.json').read_text());inventory=inv if inventory is None else inventory
        for result in json.loads((run/'results.json').read_text()):
            assert result['key']not in sources;sources[result['key']]=run/'cases'/result['key']/'labels.jsonl.gz'
            assert m.sha(sources[result['key']])==result['labels_sha256'];selected.append(result)
    assert len(selected)==83
    m.VERSION='candidate-qs-parent-review-v1'
    m.REG=m.ROOT/'examples/strategic_slices/versions/candidate_qs_parent_review_v1_20261104/SNAPSHOT.json'
    m.snapshot(args.output,dict(operation='Read-only parent-label distribution and matched-source review',
        inputs=inputs,requested_candidates=90,measured=83,declared_H3_33='NOT_COMPLETELY_SOLVED_NOT_INCLUDED',
        descriptors='Raw context counts, equal-parent/reference occupancy and geometry/physical concentration kept separate',
        comparisons='Common original-index intersections only; structure masks only complete pairs; descriptive not causal',
        criteria='NOT_FIXED',new_parents='NOT_GENERATED',selection800='NOT_RUN',D='NOT_MEASURED',workers=1,threads=1),{})
    tasks={t['key']:t for t in inventory['all_candidates']};cases=[];examples={}
    for result in sorted(selected,key=lambda x:x['key']):
        key=result['key']
        with gzip.open(sources[key],'rt')as stream:rows=list(map(json.loads,stream))
        case,local=summarize_case(key,result['arm'],rows,result,tasks[key]['job']);cases.append(case)
        for prop,row in local.items():
            name=result['arm']+'/'+prop
            if name not in examples:examples[name]=dict(key=key,row=row,raw=tasks[key]['job']['raw'])
    # Existing original100 profiles are immutable baseline, not regenerated.
    original=m.parents();original_cases=[]
    prior=m.ROOT/'new/qs_action_profile_20261104_runs'
    for name in ['pilot_v1','remaining_v1']:
        run=prior/name;complete=json.loads((run/'COMPLETE.json').read_text());assert not complete['errors']
        for result in json.loads((run/'results.json').read_text()):
            path=run/'cases'/str(result['index'])/'labels.jsonl.gz';assert m.sha(path)==result['labels_sha256']
            with gzip.open(path,'rt')as stream:rows=[json.loads(line)for line in stream]
            arm=f'original{result["players"]}P';job=dict(original[result['index']],original_index=result['index'])
            case,_=summarize_case(f'{arm}-{result["index"]}',arm,rows,result,job);original_cases.append(case)
    all_cases=original_cases+cases;groups=defaultdict(list)
    for c in all_cases:groups[c['arm']].append(c)
    paired_ids=sorted(set(c['original_index']for c in groups['H2'])&set(c['original_index']for c in groups['A2H2']))
    paired={arm:aggregate([c for c in groups[arm]if c['original_index']in paired_ids])for arm in ['original3P','H2','A2H2']}
    structure_by={tasks[c['key']]['job']['index']:c for c in groups['structure24']}
    pairs=[i for i in range(12)if 2*i in structure_by and 2*i+1 in structure_by]
    mask_pairs={arm:aggregate([structure_by[2*i+offset]for i in pairs])for arm,offset in [('uniform_mask',0),('shared_goal_mask',1)]}
    review=dict(groups={k:aggregate(v)for k,v in groups.items()},
        matched_original_indices=paired_ids,matched_H1_H2_A2H2=paired,
        complete_structure_pair_ids=pairs,structure_mask_pairing=mask_pairs,
        missing=[t['key']for t in inventory['all_candidates']if not t['available']],
        original_missing=[25],H3='33_DECLARED_NOT_BATCH_SOLVED_NO_NEW_PROFILE',
        no_formal100_or800_selection=True,model_D='NOT_MEASURED')
    m.write(args.output/'REVIEW.json',review);m.write(args.output/'PARENTS.json',all_cases);m.write(args.output/'EXAMPLES.json',examples)
    # The cache-only v3 must not alter any pilot label, even its float text.
    pilot_match={}
    for key in ['H2-3','A2H2-62','structure24-10']:
        a=gzip.decompress((base/'pilot_v2/cases'/key/'labels.jsonl.gz').read_bytes())
        b=gzip.decompress((base/'pilot_v3/cases'/key/'labels.jsonl.gz').read_bytes())
        assert a==b;pilot_match[key]=True
    m.write(args.output/'COMPLETE.json',dict(candidate_parents=83,original_baseline_parents=99,
        inherited_Q_and_all_omission_S_policies_verified=True,cache_only_pilot_labels_byte_equal=pilot_match,
        unpruned_forest_checks=sum(len(x['unpruned_checks'])for x in selected),
        review_sha256=m.sha(args.output/'REVIEW.json'),parents_sha256=m.sha(args.output/'PARENTS.json'),
        examples_sha256=m.sha(args.output/'EXAMPLES.json'),pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))


if __name__=='__main__':main()
