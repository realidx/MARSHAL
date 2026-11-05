"""Compute immutable baseline summaries while the last candidate finishes."""
from new import candidate_qs_review_20261104_v2 as method
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
import time

base=method.base
m=base.m


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();args.output=args.output.resolve()
    root=m.ROOT/'new/candidate_qs_profiles_20261104_runs'
    inputs={name:dict(pipeline_snapshot=m.sha(root/name/'pipeline_snapshot.json'),
        inventory=m.sha(root/name/'INVENTORY.json'))for name in ['pilot_v3','remaining_v3']}
    m.VERSION='candidate-qs-parent-review-v3'
    m.REG=m.ROOT/'examples/strategic_slices/versions/candidate_qs_parent_review_v3_20261104/SNAPSHOT.json'
    # Use the ordinary immutable registration writer; v2's extra mathematical
    # diagnostic is recorded explicitly in this version's resolved config.
    method.original_snapshot(args.output,dict(operation='Descriptive review; process immutable baseline before awaiting final candidate',
        input_provenance=inputs,original_baseline='99 hash-verified original profiles, read once',
        candidate_sources='pilot_v3 three + remaining_v3 eighty; read only after COMPLETE and verify all hashes',
        private_group_bound='sum(w maxQ)-max(sum(wQ)); restores full information after current action; diagnostic only',
        comparisons='Matched original-index intersection and complete mask pairs only; descriptive not causal',
        missing='Original25; H2 46/76; A2H2 10/49/76; structure4/11; H3 unrun',
        workers=1,threads=1,criteria='NOT_FIXED',new_parents='NOT_GENERATED',selection800='NOT_RUN',D='NOT_MEASURED'),{})
    original=m.parents();original_cases=[];prior=m.ROOT/'new/qs_action_profile_20261104_runs'
    for name in ['pilot_v1','remaining_v1']:
        run=prior/name;complete=json.loads((run/'COMPLETE.json').read_text());assert not complete['errors']
        for result in json.loads((run/'results.json').read_text()):
            path=run/'cases'/str(result['index'])/'labels.jsonl.gz';assert m.sha(path)==result['labels_sha256']
            with gzip.open(path,'rt')as stream:rows=[r for line in stream if (r:=json.loads(line))['counterfactual_mass']>0]
            arm=f'original{result["players"]}P';job=dict(original[result['index']],original_index=result['index'])
            case,_=method.summarize_case(f'{arm}-{result["index"]}',arm,rows,result,job);original_cases.append(case)
    assert len(original_cases)==99
    m.write(args.output/'BASELINE_PARENTS.json',original_cases)
    print('Immutable original99 baseline summaries complete',flush=True)
    selected=[];sources={};input_final={};inventory=None
    for name in ['pilot_v3','remaining_v3']:
        run=root/name
        while not(run/'COMPLETE.json').exists():time.sleep(5)
        complete=json.loads((run/'COMPLETE.json').read_text());assert not complete['errors']
        assert m.sha(run/'results.json')==complete['results_sha256']
        assert m.sha(run/'pipeline_snapshot.json')==complete['pipeline_snapshot_sha256']
        input_final[name]=dict(COMPLETE=m.sha(run/'COMPLETE.json'),results=m.sha(run/'results.json'))
        inv=json.loads((run/'INVENTORY.json').read_text());inventory=inv if inventory is None else inventory
        for result in json.loads((run/'results.json').read_text()):
            key=result['key'];assert key not in sources
            sources[key]=run/'cases'/key/'labels.jsonl.gz';assert m.sha(sources[key])==result['labels_sha256'];selected.append(result)
    assert len(selected)==83
    tasks={t['key']:t for t in inventory['all_candidates']};cases=[];examples={}
    for result in sorted(selected,key=lambda x:x['key']):
        key=result['key']
        with gzip.open(sources[key],'rt')as stream:rows=list(map(json.loads,stream))
        case,local=method.summarize_case(key,result['arm'],rows,result,tasks[key]['job']);cases.append(case)
        for prop,row in local.items():
            name=result['arm']+'/'+prop
            if name not in examples:examples[name]=dict(key=key,row=row,raw=tasks[key]['job']['raw'])
    all_cases=original_cases+cases;groups=defaultdict(list)
    for case in all_cases:groups[case['arm']].append(case)
    ids=sorted(set(c['original_index']for c in groups['H2'])&set(c['original_index']for c in groups['A2H2']))
    paired={arm:method.aggregate([c for c in groups[arm]if c['original_index']in ids])for arm in ['original3P','H2','A2H2']}
    structure={tasks[c['key']]['job']['index']:c for c in groups['structure24']}
    pairs=[i for i in range(12)if 2*i in structure and 2*i+1 in structure]
    masks={arm:method.aggregate([structure[2*i+offset]for i in pairs])for arm,offset in [('uniform_mask',0),('shared_goal_mask',1)]}
    review=dict(groups={k:method.aggregate(v)for k,v in groups.items()},matched_original_indices=ids,
        matched_H1_H2_A2H2=paired,complete_structure_pair_ids=pairs,structure_mask_pairing=masks,
        missing=[t['key']for t in inventory['all_candidates']if not t['available']],original_missing=[25],
        H3='33_DECLARED_NOT_BATCH_SOLVED_NO_NEW_PROFILE',no_formal100_or800_selection=True,model_D='NOT_MEASURED')
    m.write(args.output/'REVIEW.json',review);m.write(args.output/'PARENTS.json',all_cases);m.write(args.output/'EXAMPLES.json',examples)
    pilot_match={}
    for key in ['H2-3','A2H2-62','structure24-10']:
        a=gzip.decompress((root/'pilot_v2/cases'/key/'labels.jsonl.gz').read_bytes())
        b=gzip.decompress((root/'pilot_v3/cases'/key/'labels.jsonl.gz').read_bytes());assert a==b;pilot_match[key]=True
    m.write(args.output/'FINAL_INPUT_IDENTITIES.json',input_final)
    m.write(args.output/'COMPLETE.json',dict(candidate_parents=83,original_baseline_parents=99,
        inherited_Q_and_all_omission_S_policies_verified=True,cache_only_pilot_labels_byte_equal=pilot_match,
        unpruned_forest_checks=sum(len(x['unpruned_checks'])for x in selected),
        review_sha256=m.sha(args.output/'REVIEW.json'),parents_sha256=m.sha(args.output/'PARENTS.json'),
        examples_sha256=m.sha(args.output/'EXAMPLES.json'),pipeline_snapshot_sha256=m.sha(args.output/'pipeline_snapshot.json')))
    print('Candidate83 review complete',flush=True)


if __name__=='__main__':main()
