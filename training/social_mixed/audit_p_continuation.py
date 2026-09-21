"""Evidence audit of P continuation scope, without altering certified labels."""
from collections import Counter, defaultdict
import json
import numpy as np
from training.social_mixed.reasoning_bank import load, PATH, sha, stable
from training.social_mixed.history_free_requests import request


def audit():
    rows=[]; groups=defaultdict(list)
    for split in ('train','validation'):
        tasks={t['canonical_id']:t for t in load(split) if t['paired_view']=='Pplus'}
        for c in load(split,'cases.jsonl'):
            t=tasks[c['canonical_id']];i=t['input'];lab=c['labels']
            terminal=all(x['terminal'] for x in lab['immediate_transitions'])
            native_ok=None
            if terminal:
                pay=[]
                for child in lab['immediate_transitions']:
                    commitments=child['commitments']; completion=[]
                    for goal in i['game']['goals']:
                        vals=[commitments[a['player_id']][a['action_id']] for a in goal['required_actions']]
                        completion.append(float(all(vals)) if goal.get('binary',True) else sum(vals)/len(vals))
                    pay.append(np.einsum('wpg,g->wp',np.asarray(lab['worlds']),completion))
                native_ok=bool(np.allclose(pay,lab['per_world_payoffs'],atol=1e-9,rtol=0))
                if not native_ok:raise ValueError('Terminal payoff mismatch '+c['canonical_id'])
            private_events=[x for x in i['imposed_setup']+i['voluntary_history'] if x.get('action')=='INVESTIGATE']
            row=dict(canonical_id=c['canonical_id'],split=split,p_pool_status=t['p_pool_status'],
                p_train_eligible=t['p_train_eligible'],all_actions_terminal=terminal,
                terminal_payoffs_recomputed=native_ok,deleted_history_events=len(i['voluntary_history']),
                deleted_setup_events=len(i['imposed_setup']),deleted_investigation_events=len(private_events),
                deleted_private_results=len(i['private_results']),
                continuation_status='no_future_policy_needed' if terminal else 'requires_history_independence_certificate',
                visible_prompt_sha256=sha(stable(request(t,variant=0)).encode()))
            rows.append(row);groups[row['visible_prompt_sha256']].append((c,t))
    collisions=[]
    for signature,items in groups.items():
        for j,(a,ta) in enumerate(items):
            for b,tb in items[j+1:]:
                maps=[]
                for c in (a,b):
                    l=c['labels'];maps.append({stable(w):np.asarray(l['per_world_payoffs'])[:,k,:] for k,w in enumerate(l['worlds'])})
                common=maps[0].keys() & maps[1].keys()
                different=any(not np.allclose(maps[0][w],maps[1][w],atol=1e-9,rtol=0) for w in common)
                collisions.append(dict(left=a['canonical_id'],right=b['canonical_id'],same_rendered_P=True,
                    payoff_tables_differ_on_common_worlds=different,
                    action_states_differ=ta['p_supervision']['action_states']!=tb['p_supervision']['action_states']))
    summary=dict(cases=len(rows),source_manifest_sha256=sha((PATH/'manifest.json').read_bytes()),
        roles=dict(Counter(r['split']+':'+r['p_pool_status']+':'+r['continuation_status'] for r in rows)),
        terminal_payoff_checks=sum(r['terminal_payoffs_recomputed'] is True for r in rows),
        nonterminal_cases=sum(not r['all_actions_terminal'] for r in rows),
        nonterminal_with_deleted_investigation=sum(not r['all_actions_terminal'] and r['deleted_investigation_events']>0 for r in rows),
        identical_prompt_pairs=len(collisions),different_payoff_pairs=sum(r['payoff_tables_differ_on_common_worlds'] for r in collisions),
        different_label_pairs=sum(r['action_states_differ'] for r in collisions),
        caveat='Absence of a collision is not a sufficiency certificate. No eligibility changes; C/D multistep continuation remains uncertified.')
    return rows,collisions,summary

if __name__=='__main__':
    rows,pairs,summary=audit()
    for name,data in [('p_continuation_audit.jsonl',rows),('p_continuation_pairs.jsonl',pairs)]:
        (PATH/name).write_text(''.join(json.dumps(r)+'\n' for r in data))
    (PATH/'p_continuation_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
