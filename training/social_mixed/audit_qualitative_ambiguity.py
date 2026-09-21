"""Search witnesses, not a sufficiency certificate, under fixed continuation."""
import json
from collections import Counter
import numpy as np
from training.social_mixed.reasoning_bank import load, PATH
from training.b_sft.preference_contract import belief
from training.b_sft.social_bp_curriculum import acceptable


def audit():
    tasks={t['canonical_id']:t for s in ('train','validation') for t in load(s) if t['paired_view']=='Pplus'}
    witnesses=[]
    for split in ('train','validation'):
        for c in load(split,'cases.jsonl'):
            lab=c['labels']; t=tasks[c['canonical_id']]; inp=t['input'];actor=inp['player']
            w=np.array(lab['posterior']);worlds=np.array(lab['worlds']);pay=np.array(lab['per_world_payoffs'])
            original=set(acceptable(lab['action_values'],actor,actions=inp['legal_actions']))
            masks=[{name:worlds[:,q['player'],q['goal']]==v for name,v in [('want',1),('neutral',0),('avoid',-1)]} for q in lab['query_candidates']]
            found=None
            for j in np.flatnonzero(w>0):
                for alpha in (.1,.25,.5,.75,.9,.99):
                    candidate=(1-alpha)*w;candidate[j]+=alpha
                    if any(belief({name:float(candidate[mask].sum()) for name,mask in m.items()})!=q['gold']
                           for m,q in zip(masks,lab['query_candidates'])):continue
                    values=np.einsum('awp,w->ap',pay,candidate)
                    new=set(acceptable(values,actor,actions=inp['legal_actions']))
                    if original.isdisjoint(new):
                        state=inp['current_state']
                        found=dict(canonical_id=c['canonical_id'],split=split,
                            final_proposal_turn=state['turn_index']==len(state['round_robin'])-1,
                            pending_offer=bool(inp['pending_offer']),
                            qualitative_beliefs=t['input']['supplied_belief']['semantic_beliefs'],
                            original_weights=w.tolist(),alternative_weights=candidate.tolist(),worlds=lab['worlds'],
                            legal_actions=inp['legal_actions'],original_values=lab['action_values'],alternative_values=values.tolist(),
                            original_acceptable_indices=sorted(original),alternative_acceptable_indices=sorted(new))
                        break
                if found:break
            if found:witnesses.append(found)
    return dict(scope='Finite witness search, preserving every support/favored label and original joint support, fixed per-world continuation payoffs. Not exhaustive; alternative posteriors are not certified reachable by the original history.',
                cases_checked=len(tasks),cases_with_disjoint_action_witness=len(witnesses),
                counts_by_split=dict(Counter(w['split'] for w in witnesses)),
                final_turn_pending_offer_witnesses=sum(w['final_proposal_turn'] and w['pending_offer'] for w in witnesses),
                witnesses=witnesses)

if __name__=='__main__':
    report=audit();(PATH/'qualitative_ambiguity_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='witnesses'},indent=2))
