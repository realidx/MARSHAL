"""Close the cause audit and inspect the existing response social tie objective."""
from collections import Counter
import gzip
import json
from pathlib import Path
import shutil

from new import diagnose_H2_sparse_S_20261024 as d

d.VERSION='H2-sparse-S-social-audit-v3'
d.REG=d.ROOT/'examples/strategic_slices/versions/H2_sparse_S_social_audit_v3_20261024/SNAPSHOT.json'


def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    first=d.ROOT/'new/H2_sparse_S_causes_v1_20261024/probe_v1'
    second=d.ROOT/'new/H2_sparse_S_causes_full31_v2_20261024/probe_remaining25_v1'
    labels=d.ROOT/'new/H2_sparse_S_causes_v1_20261024/labels_v1'
    inputs={}
    for name,root in [('six',first),('remaining25',second),('labels',labels)]:
        for file in ('pipeline_snapshot.json','COMPLETE.json'):
            inputs[f'{name}:{file}']=d.identity(root/file)
    inputs['six_results']=d.identity(first/'RESULTS.json');inputs['remaining_results']=d.identity(second/'RESULTS.json')
    inputs['label_audit']=d.identity(labels/'LABEL_AUDIT.json')
    rows=json.loads((first/'RESULTS.json').read_text())+json.loads((second/'RESULTS.json').read_text())
    rows.sort(key=lambda r:r['index']);assert len(rows)==len({r['index']for r in rows})==31
    assert all(r['status']=='COMPLETED'for r in rows)
    results,jobs,source_inputs=d.inputs_and_results();inputs.update(source_inputs)
    d.snapshot(args.output,dict(operation='All31 sparse-S cause report and separate response tie-information audit',
        game_and_labels='UNCHANGED',S='Own-utility main S preserved; social current-action diagnostic is separate',
        current_social_regret='Max Q_others among own-optimal responses minus omitted-policy expected Q_others',
        admission='Response only, at least2 own-optimal actions, primary current regret<=1e-8, secondary regret>1e-8',
        terminal_validation='Last proposal turn response has no future decisions; compare current regret with stored actual secondary loss',
        remaining_policy_scope='Earlier current-action regret uses the existing full-information continuation Q matrix; not an alternate equilibrium',
        numeric_epsilon=1e-8,source_report_script=d.identity(__file__)),inputs)
    control=Counter();composites={mode:Counter()for mode in ('all_entry_history','all_entry_allowed')}
    for row in rows:
        control.update(row['counts'])
        for mode,count in row['composites'].items():composites[mode].update(count)
    lp=[c for r in rows for c in r['LP_checks']]
    assert all(c['LP_matches']for c in lp)
    social_counts=Counter();social_parents=set();terminal_parents=set();evidence=[];own_keys=set();social_keys=set();on_own=set();on_social=set()
    own_parents=set()
    for result in results:
        last_turn=len(jobs[result['index']]['raw']['game']['round_robin'])-1
        for row in d.read_rows(result):
            key=(result['index'],row['node'],row['cell'])
            if d.single_positive(row):
                own_keys.add(key);own_parents.add(result['original_index'])
                if row['reference_mass']>0:on_own.add(key)
            if row['phase']!='response'or len(row['own_optimal'])<2:continue
            hits=[]
            for item in row['S_items']:
                p=item.get('omitted_action_probabilities')
                if p is None:continue
                primary=max(row['Q'])-sum(a*b for a,b in zip(p,row['Q']))
                secondary=max(row['Q_others'][a]for a in row['own_optimal'])-sum(a*b for a,b in zip(p,row['Q_others']))
                if primary<=d.EPS and secondary>d.EPS:
                    assert sum(p[a]for a in row['optimal'])<1-1e-10
                    if row['turn']==last_turn:
                        assert item['S']<=d.EPS
                        assert abs(item['response_secondary_loss']-secondary)<1e-7
                    hits.append(dict(omitted=item['omitted'],policy=p,current_primary_regret=primary,current_secondary_regret=secondary))
            if not hits:continue
            social_keys.add(key);social_parents.add(result['original_index'])
            social_counts['contexts']+=1;social_counts['main_own_S_zero']+=not d.single_positive(row)
            social_counts['on_reference']+=row['reference_mass']>0
            if row['reference_mass']>0:on_social.add(key)
            if row['turn']==last_turn:
                social_counts['terminal_contexts']+=1;social_counts['terminal_on_reference']+=row['reference_mass']>0
                terminal_parents.add(result['original_index'])
            evidence.append(dict(original_index=result['original_index'],study_index=result['index'],
                node=row['node'],cell=row['cell'],turn=row['turn'],actor=row['actor'],terminal=row['turn']==last_turn,
                reference_mass=row['reference_mass'],own_type=row['own_type'],private_answers=row['private_answers'],
                actions=row['actions'],Q=row['Q'],Q_others=row['Q_others'],optimal=row['optimal'],
                own_S=max(row['S_private'],row['S_history']),items=hits))
    audit=json.loads((labels/'LABEL_AUDIT.json').read_text())
    primary={r['original_index']for r in audit['per_game']if r['private_positive']or r['history_positive']}
    joint={r['original_index']for r in rows if r['composites']['all_entry_allowed'].get('positive_contexts',0)>0}
    report=dict(measured=31,missing_original_indices=[46,76],control_bounds=control,composites=composites,
        main_S_positive_parents=sorted(primary),joint_diagnostic_positive_parents=sorted(joint),
        previously_zero_main_S_but_joint_positive=sorted(joint-primary),
        zero_joint_diagnostic_parents=sorted(r['original_index']for r in rows if r['original_index']not in joint),
        LP_checks=len(lp),recorded_ambiguous_zero_private_LP_checks=sum(c['mode']=='recorded_ambiguous_zero_private_S'for c in lp),
        all_LP_matches=True,future_observation_invariants=sum(r['future_observation_invariants']for r in rows),
        response_tie_information=dict(counts=social_counts,parents=sorted(social_parents),terminal_parents=sorted(terminal_parents),
            union_with_main_S_contexts=len(own_keys|social_keys),union_on_reference=len(on_own|on_social),
            union_parent_count=len(own_parents|social_parents),definition='Separate current oracle-response tie diagnostic, not a new scalar S or reward'),
        label_audit=dict(counts=audit['counts'],private_group_counts=audit['private_group_counts'],minimum_S_above_EPS=audit['minimum_S_above_EPS']),
        conclusions=['Own-S sparsity has real payoff-control and common-optimum causes; numeric cutoff does not erase meaningful positives',
            'Redundant entry-time evidence hides some single-item information value; uniformly stronger omission still leaves21 parents with no own-utility information loss',
            'Main own-utility S does not measure information needed for the mandated response social tie rule; report this channel separately',
            'D and model self-play exposure remain unmeasured; no parent selection, reward, game or prompt change'])
    d.write(args.output/'CAUSES.json',report);d.write(args.output/'SOCIAL_TIE_EVIDENCE.json',evidence)
    d.write(args.output/'COMBINED_PROBES.json',rows)
    d.write(args.output/'COMPLETE.json',dict(causes_sha256=d.sha(args.output/'CAUSES.json'),
        social_tie_sha256=d.sha(args.output/'SOCIAL_TIE_EVIDENCE.json'),combined_sha256=d.sha(args.output/'COMBINED_PROBES.json'),
        snapshot_sha256=d.sha(args.output/'pipeline_snapshot.json')))
    print(json.dumps({k:v for k,v in report.items()if k not in ('conclusions','label_audit')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
