"""Audit the proposed 394 invariant + 59 robust-positive pool; no training edits."""
import json
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from itertools import combinations
from training.b_sft.social_bp_curriculum import acceptable
from training.social_mixed.reasoning_bank import PATH, load, sha


def audit():
    payload=(PATH/'qualitative_case_audit.jsonl').read_bytes()
    previous=json.loads((PATH/'qualitative_case_audit_summary.json').read_text())
    assert sha(payload)==previous['audit_sha256']
    audits={r['canonical_id']:r for r in map(json.loads,payload.splitlines())}
    cases={c['canonical_id']:c for split in ('train','validation') for c in load(split,'cases.jsonl')}
    tasks={t['canonical_id']:t for split in ('train','validation') for t in load(split) if t['paired_view']=='O'}
    records=[];excluded=[]
    for cid,c in cases.items():
        r=audits[cid];a=r['text_envelope']
        if not a['original_positive_labels_all_robust']:
            excluded.append(cid);continue
        group='invariant' if a['status']=='reward_labels_invariant_in_envelope' else 'robust_positive_partial'
        positive=set(a['universally_acceptable_indices']);negative=set(a['always_rejected_indices'])
        unknown=set(range(len(r['legal_actions'])))-positive-negative
        assert not positive & negative
        assert set(a['original_acceptable_indices'])<=positive
        observations=[set(a['original_acceptable_indices'])]+[set(w['acceptable_indices']) for w in a['witnesses']]
        states=[]
        for j,action in enumerate(r['legal_actions']):
            observed={j in o for o in observations}
            state='positive' if j in positive else 'negative' if j in negative else 'masked'
            states.append(dict(action_index=j,action=action,semantic_supervision=state,
                ambiguity_evidence='accept_and_reject_witnesses' if state=='masked' and observed=={True,False}
                                   else 'not_fully_classified' if state=='masked' else 'LP_bound'))
        lab=c['labels'];q=lab['query'];worlds=np.asarray(lab['worlds']);posterior=np.asarray(lab['posterior'])
        conditional=[]
        for name,value in [('want',1),('neutral',0),('avoid',-1)]:
            weights=posterior*(worlds[:,q['player'],q['goal']]==value)
            if weights.sum()<=1e-12:continue
            values=np.einsum('awp,w->ap',np.asarray(lab['per_world_payoffs']),weights/weights.sum())
            conditional.append(dict(preference=name,acceptable_indices=acceptable(values,tasks[cid]['input']['player'],actions=r['legal_actions'])))
        conditional_disjoint=any(set(a['acceptable_indices']).isdisjoint(b['acceptable_indices']) for a,b in combinations(conditional,2))
        records.append(dict(canonical_id=cid,split=c['split'],family=c['family'],package_id=c['package_id'],
            source_kernel=c['source_kernel'],completion_mode=c['completion_mode'],group=group,
            b_query_action_relevant=c['labels']['query']['action_relevant_under_fixed_continuation'],
            b_query=c['labels']['query'],actions=states,
            query_conditional_acceptable_sets=conditional,query_conditional_disjoint=conditional_disjoint,
            has_positive_and_negative=bool(positive and negative),
            all_immediate_actions_terminal=r['all_immediate_actions_terminal']))
    ids={r['canonical_id'] for r in records};selected={r['canonical_id']:r for r in records}
    assert len(records)==453 and len(excluded)==44
    relations=[r for s in ('train','validation') for r in load(s,'relations.jsonl')]
    matched=[]
    for rel in relations:
        if rel['left'] not in ids or rel['right'] not in ids:continue
        a,b=selected[rel['left']],selected[rel['right']]
        pa={x['action_index'] for x in a['actions'] if x['semantic_supervision']=='positive'}
        pb={x['action_index'] for x in b['actions'] if x['semantic_supervision']=='positive'}
        assert tasks[rel['left']]['input']['legal_actions']==tasks[rel['right']]['input']['legal_actions']
        query=a['b_query'];qkey=(query['player'],query['goal'])
        remaining=[[x for x in audits[rel[k]]['qualitative_beliefs'] if (x['player'],x['goal'])!=qkey] for k in ('left','right')]
        matched.append(dict(**rel,only_queried_semantic_belief_changes=rel['same_B_query'] and rel['semantic_B_changed'] and remaining[0]==remaining[1],robust_acceptable_disjoint=pa.isdisjoint(pb),
            robust_acceptable_same=pa==pb,
            same_rendered_qualitative_beliefs=audits[rel['left']]['qualitative_beliefs']==audits[rel['right']]['qualitative_beliefs']))
    # Strongest existing matched evidence: full payoff-table match, different
    # qualitative beliefs and no common robust-positive action.
    strong=[r for r in matched if r['fixed_continuation_payoffs_match'] and r['robust_acceptable_disjoint']
            and not r['same_rendered_qualitative_beliefs']]
    strongest_query=[r for r in strong if r['same_B_query'] and r['semantic_B_changed']]
    packages=defaultdict(list)
    for c in cases.values():packages[c['package_id']].append(c['canonical_id'])
    partial=[dict(package_id=p,retained=[c for c in cs if c in ids],excluded=[c for c in cs if c not in ids])
             for p,cs in packages.items() if any(c in ids for c in cs) and any(c not in ids for c in cs)]
    split_families=defaultdict(set)
    for r in records:split_families[r['family']].add(r['split'])
    assert all(len(s)==1 for s in split_families.values())
    summaries={}
    for split in ('train','validation'):
        rs=[r for r in records if r['split']==split];partial_rs=[r for r in rs if r['group']=='robust_positive_partial']
        original_strata={(c['source_kernel'],c['completion_mode']) for c in cases.values() if c['split']==split}
        new_strata={(r['source_kernel'],r['completion_mode']) for r in rs}
        links=[r for r in strong if r['split']==split]
        summaries[split]=dict(cases=len(rs),views=3*len(rs),groups=dict(Counter(r['group'] for r in rs)),
            families=len({r['family'] for r in rs}),packages=len({r['package_id'] for r in rs}),
            query_relevant=sum(r['b_query_action_relevant'] for r in rs),
            query_conditioning_changes_acceptable_action=sum(r['query_conditional_disjoint'] for r in rs),
            missing_source_kernel_mode_strata=[list(x) for x in sorted(original_strata-new_strata)],
            partial_action_states=dict(Counter(a['semantic_supervision'] for r in partial_rs for a in r['actions'])),
            partial_without_definite_negative=[r['canonical_id'] for r in partial_rs if not r['has_positive_and_negative']],
            partial_masked_evidence=dict(Counter(a['ambiguity_evidence'] for r in partial_rs for a in r['actions'] if a['semantic_supervision']=='masked')),
            all_cases_with_positive_and_negative=sum(r['has_positive_and_negative'] for r in rs),
            fixed_payoff_robust_disjoint_pairs=len(links),
            cases_in_fixed_payoff_robust_disjoint_pairs=len({r[k] for r in links for k in ('left','right')}),
            same_query_changed_B_pairs=sum(r['split']==split for r in strongest_query),
            only_queried_B_changed_pairs=sum(r['only_queried_semantic_belief_changes'] for r in links),
            cases_in_only_queried_B_changed_pairs=len({r[k] for r in links if r['only_queried_semantic_belief_changes'] for k in ('left','right')}),
            retained_original_must_change_pairs=sum(r['split']==split and r['relation']=='must_change' for r in matched))
    rows_payload=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records).encode()
    (PATH/'candidate_453_cases.jsonl').write_bytes(rows_payload)
    (PATH/'candidate_453_relations.json').write_text(json.dumps(matched,indent=2)+'\n')
    summary=dict(cases=len(records),excluded=len(excluded),groups=dict(Counter(r['group'] for r in records)),
        source_audit_sha256=sha(payload),candidate_cases_sha256=sha(rows_payload),
        auditor_sha256=sha(Path(__file__).read_bytes()),splits=summaries,
        partial_parent_packages=partial,excluded_canonical_ids=excluded,
        family_split_disjoint=True,source_split_preserved=True,
        scope=previous['scope'],
        training_ready=False,
        required_training_changes=['P masked actions must be excluded from semantic group centering/normalization and semantic loss; retain independent protocol/KL.',
          'P validation must report positive/negative/masked rates and scored coverage; masked is neither incorrect nor correct.',
          'Preserve O native labels and B tool schema; only P receives tri-state semantics.',
          'Partial parent packages need explicit handling; preserve retained relations and do not imply complete original parent coverage.',
          'Exposure/zero-signal frequency still requires a model probe; possible positive/negative actions do not guarantee sampled mixed groups.'])
    (PATH/'candidate_453_audit.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('partial_parent_packages','excluded_canonical_ids','scope','required_training_changes')},indent=2))
    return summary,records,matched

if __name__=='__main__':audit()
