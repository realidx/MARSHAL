"""Audit stored P world support against model-visible categorical supports.

Does not re-solve continuation policies or change training eligibility.
"""
from collections import Counter
from itertools import product
import json
from pathlib import Path
from training.social_mixed.reasoning_bank import load, PATH, sha
from training.social_mixed.history_free_requests import request

VALUES={'want':1,'neutral':0,'avoid':-1}


def audit_case(case, task):
    inp=task['input']; lab=case['labels']; n=inp['game']['n_players']; g=len(inp['game']['goals'])
    supports={(inp['player'],j):[VALUES[inp['own_preferences'][f'goal_{j}']]] for j in range(g)}
    for b in inp['supplied_belief']['semantic_beliefs']:
        supports[b['player'],b['goal']]=[VALUES[v] for v in b['possible_preferences']]
    assert len(supports)==n*g
    visible={tuple(tuple(v[p*g:(p+1)*g]) for p in range(n))
             for v in product(*(supports[p,j] for p in range(n) for j in range(g)))}
    teacher={tuple(map(tuple,w)) for w in lab['worlds']}
    admitted=teacher & visible
    # Original reconstruct() rejects these globally, but P omits generation conditions.
    rule_filtered={w for w in visible if all(1 in row for row in w)
                   and all(any(w[p][j]!=0 for p in range(n)) for j in range(g))}
    public={(x['player'],x['goal']):VALUES[x['preference']] for x in inp['public_preferences']}
    public_filtered={w for w in rule_filtered if all(w[p][j]==v for (p,j),v in public.items())}
    weights=lab['posterior']
    assert len(weights)==len(lab['worlds'])
    outside_mass=sum(float(v) for w,v in zip(lab['worlds'],weights) if tuple(map(tuple,w)) not in visible)
    missing=visible-teacher
    return dict(canonical_id=case['canonical_id'],split=case['split'],p_pool_status=task['p_pool_status'],
        p_train_eligible=task['p_train_eligible'],visible_worlds=len(visible),teacher_worlds=len(teacher),
        lp_support_worlds=len(admitted),missing_visible_worlds=len(missing),
        missing_explained_by_unrendered_generation_rules=len(visible-rule_filtered),
        missing_after_generation_rules=len(rule_filtered-teacher),
        missing_after_generation_and_source_public_facts=len(public_filtered-teacher),
        source_public_facts_implied_by_visible_support=all(all(v==x for v in supports[p,j]) for (p,j),x in public.items()),
        source_posterior_outside_visible_mass=outside_mass,
        source_zero_mass_worlds_retained=sum(v==0 and tuple(map(tuple,w)) in admitted for w,v in zip(lab['worlds'],weights)),
        all_actions_immediately_terminal=all(x['terminal'] for x in lab['immediate_transitions']),
        missing_world_example=[list(row) for row in min(missing)] if missing else None,
        actual_request_sha256=sha(json.dumps(request(task),sort_keys=True).encode()),
        constraint_provenance=dict(own_preferences='visible',marginal_support_and_favored='visible supplied belief',
            global_want_and_non_neutral_rules='source generation conditions, omitted from P rendering',
            source_public_facts='deleted source facts; checked for implication by visible supports',
            voluntary_history_and_private_results='source posterior and fixed continuation; not direct LP support filters'),
        conclusion='visible_support_not_covered' if missing else 'visible_support_covered_fixed_payoffs_only')


def main():
    rows=[]
    for split in ('train','validation'):
        tasks={t['canonical_id']:t for t in load(split) if t['paired_view']=='Pplus'}
        rows.extend(audit_case(c,tasks[c['canonical_id']]) for c in load(split,'cases.jsonl'))
    summary=dict(source_manifest_sha256=sha((PATH/'manifest.json').read_bytes()),
        audit_code_sha256=sha(Path(__file__).read_bytes()),cases=len(rows),support_missing_cases=sum(bool(r['missing_visible_worlds']) for r in rows),
        missing_after_generation_rules=sum(bool(r['missing_after_generation_rules']) for r in rows),
        public_facts_not_implied=sum(not r['source_public_facts_implied_by_visible_support'] for r in rows),
        posterior_outside_visible_cases=sum(r['source_posterior_outside_visible_mass']>1e-9 for r in rows),
        zero_posterior_worlds_retained_cases=sum(r['source_zero_mass_worlds_retained']>0 for r in rows),
        affected_roles=dict(Counter(r['split']+':'+r['p_pool_status'] for r in rows if r['missing_visible_worlds'])),
        affected_train_eligible=sum(r['split']=='train' and r['p_train_eligible'] and bool(r['missing_visible_worlds']) for r in rows),
        limitation='Support coverage only, not new payoff/reward certification. Multi-step continuation may still depend on deleted information. No labels or eligibility changed.')
    (PATH/'p_world_scope_audit.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
    (PATH/'p_world_scope_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
