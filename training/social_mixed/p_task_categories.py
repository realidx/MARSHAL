"""Auditable P categories from current actions and certified transitions, not legacy pool names."""
from collections import Counter
import json

VERSION='p-decision-categories-v1'

def classify(task, case):
    i=task['input'];actions=i['legal_actions'];states=task['p_supervision']['action_states']
    if len(actions)!=len(states) or not actions:raise ValueError('P action/label mismatch')
    if not set(states)<= {'positive','negative','masked'}:raise ValueError('Unknown P label')
    query=any(a.get('action')=='INVESTIGATE' for a in actions)
    response=bool(i.get('pending_offer'))
    if response and query:raise ValueError('Response unexpectedly permits investigation')
    transitions=case['labels']['immediate_transitions']
    if len(transitions)!=len(actions):raise ValueError('Transition/action count mismatch')
    return dict(operation='response' if response else 'investigation_choice' if query else 'ordinary_proposal',
        horizon='direct_terminal' if all(x['terminal'] for x in transitions) else 'multistep',
        mode=task['completion_mode'],relevance='relevant' if task['belief_action_relevant'] else 'control',
        # Provenance only: P does not expose the investigation history.
        source_has_private_result=bool(i.get('private_results')),
        source_kernel=task['source_kernel'],positive=states.count('positive'),negative=states.count('negative'),masked=states.count('masked'))

def cell(category):
    return '/'.join(category[k] for k in ('operation','horizon','mode','relevance'))

def inventory(tasks,cases):
    by={c['canonical_id']:c for c in cases};result={}
    for t in tasks:
        if t['paired_view']!='Pplus':continue
        result[t['canonical_id']]=classify(t,by[t['canonical_id']])
    return result

if __name__=='__main__':
    from pathlib import Path
    from training.social_mixed.reasoning_bank import load
    out=Path('new/p_categories_audit_20260923');out.mkdir(exist_ok=True)
    records=[]
    for split in ('train','validation'):
        tasks=load(split);cats=inventory(tasks,load(split,'cases.jsonl'))
        for t in tasks:
            if t['paired_view']=='Pplus':records.append(dict(id=t['id'],canonical_id=t['canonical_id'],split=split,eligible=t['p_train_eligible'],pool_status=t['p_pool_status'],**cats[t['canonical_id']]))
    (out/'tasks.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    summary={split:dict(Counter(cell(r) for r in records if r['split']==split and r['eligible'])) for split in ('train','validation')}
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
