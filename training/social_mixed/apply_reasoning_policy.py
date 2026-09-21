"""Activate audited P supervision while preserving every native O/B parent."""
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path
from training.social_mixed.reasoning_bank import PATH, ROOT, sha, stable


def apply():
    manifest=json.loads((PATH/'manifest.json').read_text())
    payload=(PATH/'qualitative_case_audit.jsonl').read_bytes()
    audit_summary=json.loads((PATH/'qualitative_case_audit_summary.json').read_text())
    if sha(payload)!=audit_summary['audit_sha256']:raise ValueError('Audit checksum changed')
    audits={r['canonical_id']:r for r in map(json.loads,payload.splitlines())}
    cases=list(map(json.loads,(PATH/'cases.jsonl').read_text().splitlines()))
    by={c['canonical_id']:c for c in cases}
    bindings={cid:sha(stable({k:c['labels'][k] for k in ('worlds','posterior','per_world_payoffs','action_values','acceptable_actions','query_candidates')}).encode()) for cid,c in by.items()}
    binding_path=PATH/'policy_audit_bindings.json'
    if binding_path.exists() and json.loads(binding_path.read_text())!=bindings:
        raise ValueError('Audited value/belief labels changed: rerun the semantic audit before applying policy')
    binding_path.write_text(json.dumps(bindings,indent=2)+'\n')
    tasks=list(map(json.loads,(PATH/'tasks.jsonl').read_text().splitlines()))
    relations=list(map(json.loads,(PATH/'relations.jsonl').read_text().splitlines()))
    selected={cid for cid,r in audits.items() if r['text_envelope']['original_positive_labels_all_robust']}
    changes={};pairs=[]
    for r in relations:
        if not r['fixed_continuation_payoffs_match'] or not {r['left'],r['right']}<=selected:continue
        a,b=(audits[r[k]] for k in ('left','right'))
        if not set(a['text_envelope']['universally_acceptable_indices']).isdisjoint(b['text_envelope']['universally_acceptable_indices']):continue
        diff=[(x,y) for x,y in zip(a['qualitative_beliefs'],b['qualitative_beliefs']) if x!=y]
        if len(diff)!=1:continue
        x,y=diff[0]
        if (x['player'],x['goal'])!=(y['player'],y['goal']):continue
        key=(x['player'],x['goal'])
        if any(cid in changes and changes[cid]!=key for cid in (r['left'],r['right'])):continue
        for cid in (r['left'],r['right']):changes[cid]=key
        pairs.append(dict(left=r['left'],right=r['right'],split=r['split'],query=dict(player=key[0],goal=key[1])))
    if not any(p['split']=='validation' for p in pairs):raise ValueError('No validation B-to-action pair')
    for cid,key in changes.items():
        c=by[cid];c['labels']['query']=deepcopy(next(q for q in c['labels']['query_candidates'] if (q['player'],q['goal'])==key))
        c['b_query_selection']='isolated qualitative belief change with disjoint robust actions; no model outcomes'
    for t in tasks:
        cid=t['canonical_id'];c=by[cid];a=audits[cid]['text_envelope'];q=c['labels']['query']
        relevant=q['action_relevant_under_fixed_continuation'] or cid in changes
        t['belief_action_relevant']=relevant
        positive=set(a['universally_acceptable_indices']);negative=set(a['always_rejected_indices'])
        approved=cid in selected
        t['p_train_eligible']=approved and bool(positive and negative)
        t['p_pool_status']='trainable' if t['p_train_eligible'] else 'evaluation_only_no_negative' if approved else 'quarantined'
        if t['paired_view']=='Pplus':
            states=['positive' if j in positive else 'negative' if j in negative else 'masked' for j in range(len(t['input']['legal_actions']))] if approved else ['masked']*len(t['input']['legal_actions'])
            t['p_supervision']=dict(version='qualitative-tristate-v1',action_states=states,audit_sha256=sha(payload),
                scope=audit_summary['scope'])
        if t['paired_view']=='B':
            t['input']['queries']=[dict(player=q['player'],goal=q['goal'])]
            t['teacher']['gold']=deepcopy(q['gold']);t['teacher']['preference_weights']=deepcopy(q['preference_weights'])
            t['answer_signature']=stable(q['gold'])
    for r in relations:
        qa,qb=(by[r[k]]['labels']['query'] for k in ('left','right'))
        r['same_B_query']=all(qa[k]==qb[k] for k in ('player','goal'))
        r['semantic_B_changed']=qa['gold']!=qb['gold']
        r['isolated_B_action_pair']=any(p['left']==r['left'] and p['right']==r['right'] for p in pairs)
    for name,rows in [('tasks.jsonl',tasks),('cases.jsonl',cases),('relations.jsonl',relations)]:
        data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode()
        (PATH/name).write_bytes(data);manifest['files'][name]=dict(sha256=sha(data),rows=len(rows))
    plan=dict(version='audited-roles-v1',native_O_B_cases=len(cases),P_approved_cases=len(selected),
        P_training_cases=sum(t['p_train_eligible'] for t in tasks if t['paired_view']=='Pplus'),
        P_role_counts=dict(Counter(t['split']+':'+t['p_pool_status'] for t in tasks if t['paired_view']=='Pplus')),
        isolated_B_action_pairs=pairs,all_original_parent_packages_preserved=True,
        all_source_kernel_mode_strata_preserved_for_O_B=True,
        P_source_coverage='Restricted to certified positive/negative tasks; excluded strata are not relabeled as certified P.',
        selection='Offline label audit, fixed before model runs; no model-performance filtering')
    data=(json.dumps(plan,indent=2)+'\n').encode();(PATH/'training_plan.json').write_bytes(data)
    manifest['training_plan_sha256']=sha(data)
    manifest['policy_audit_bindings_sha256']=sha(binding_path.read_bytes())
    manifest['active_recipe']='audited-tristate-v1'
    manifest['formal_training_ready']=False
    manifest['remaining_acceptance']=['exact tokenizer context','Q0 semantic mixed-group probe','GPU actor/behavior probabilities, resume and short learning/retention']
    manifest['action_relevant_queries']=dict(Counter(c['split'] for c in cases if c['labels']['query']['action_relevant_under_fixed_continuation']))
    for f in list(manifest['label_sources'])+['training/social_mixed/apply_reasoning_policy.py','training/social_mixed/reasoning_scoring.py','training/social_mixed/reasoning_training.py','training/social_mixed/reasoning_validation.py']:
        manifest['label_sources'][f]=sha((ROOT/f).read_bytes())
    (PATH/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({k:v for k,v in plan.items() if k!='isolated_B_action_pairs'},indent=2))
    return plan

if __name__=='__main__':apply()
