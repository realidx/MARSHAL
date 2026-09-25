"""Re-solve legacy validation structures from exogenous initial conditions.
Output is a development candidate pool, NOT a frozen held-out benchmark.
"""
import json
from pathlib import Path
from copy import deepcopy
from collections import Counter
import numpy as np
from new.diagnostic_v7.initial_state import InitialEpisode, materialize_start, request
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.prepare_no_catalogue_probe import view
from training.b_sft.preference_contract import belief, profile
from training.b_sft.social_private_teacher import audit_native
from training.b_sft.social_bp_curriculum import acceptable

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def build():
    source=ROOT/'examples/social_mixed/paired_bank_v2/tasks.jsonl'
    rows=[json.loads(l) for l in source.read_text().splitlines()]
    candidates=[];rejected=[]
    for b in rows:
        if b['split']!='validation' or b['paired_view']!='B':continue
        try:
            old=b['input'];raw,own=reconstruct(old)
            raw['background_prior']=old.get('background_prior',profile('balanced'))
            setup=old['imposed_setup']
            cut=next((n for n,e in enumerate(setup) if e.get('action')=='INVESTIGATE'),len(setup))
            # Private observations remain AFTER the new initial state; no hidden query is erased.
            raw,initial=materialize_start(raw,setup[:cut])
            events=deepcopy(setup[cut:]+old['voluntary_history'])
            facts=[(f['player'],f['goal'],{'want':1,'neutral':0,'avoid':-1}[f['preference']]) for f in old['private_results']]
            episode=InitialEpisode(raw,initial,seconds=10,max_nodes=30000,max_sweeps=128)
            for event in events:episode.observe(event)
            node=episode.tree.entries[episode.index]
            if node.actor!=old['observer']:raise ValueError('Focal player not the decision maker')
            q=old['queries'][0]
            marginal=episode.belief(q['player'],q['goal'],observer=old['observer'],own=own,private_results=facts)['preference_weights']
            inp=view(episode,old['public_preferences'],old['observer'],own,facts,[],events)
            inp.update(initial_turn_index=initial.get('turn_index',0),initial_commitments=initial['commitments'],background_prior=raw['background_prior'],favored_margin=.1,queries=[q])
            actions=[a.to_dict() for a in node.actions]
            weights=episode._weights(old['observer'],own,facts)
            pay=np.array([episode.tree.values[c] for c in node.children])
            values=np.einsum('awp,w->ap',pay,weights)
            teacher=dict(gold=belief(marginal),preference_weights=marginal,
                         acceptable_actions=[actions[i] for i in acceptable(values,old['observer'],actions=actions)],
                         action_values=values.tolist(),per_world_payoffs=pay.tolist(),
                         worlds=episode.tree.worlds,posterior=weights.tolist(),
                         policy_sha256=episode.tree.certificate['policy_sha256'])
            inp['legal_actions']=actions
            inp['supplied_belief']=dict(known_preferences=old['public_preferences'],unresolved_preferences=[q],support='Infer from the visible information.')
            base=dict(id='initial-'+b['id'],input=inp,teacher=teacher,task='B',skill='formation',condition='B')
            b_request=request(base,initial)
            o=deepcopy(base);o.update(task='P',condition='P_infer',skill='history_planning')
            o_request=request(o,initial)
            candidates.append(dict(id=base['id'],source_parent=b['canonical_id'],source_b_id=b['id'],
                initial_state=initial,raw=raw,task=base,requests=dict(B=b_request,O=o_request),
                native_audit=audit_native(episode.tree),
                label_changed=teacher['gold']!=b['teacher']['gold'],
                role='development_candidate_not_heldout',
                history_events=len(events)))
        except (ValueError,AssertionError,RuntimeError,TimeoutError) as exc:
            rejected.append(dict(source_b_id=b['id'],reason=type(exc).__name__+': '+str(exc)))
    (HERE/'candidates.json').write_text(json.dumps(candidates,indent=2)+'\n')
    summary=dict(status='CANDIDATE_POOL_ONLY',accepted=len(candidates),rejected=len(rejected),
        rejection_reasons=dict(Counter(r['reason'] for r in rejected)),
        labels=dict(Counter(str(r['task']['teacher']['gold']) for r in candidates)),
        history_lengths=dict(Counter(r['history_events'] for r in candidates)),
        label_changes=sum(r['label_changed'] for r in candidates),details=rejected,
        remaining=['Held-out generation/leakage audit','Private-feedback reconstruction',
                   'Complete B-to-P unknown coverage and history-free P certification','Balanced selection and runner'])
    (HERE/'rebuild_audit.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='details'},indent=2))

if __name__=='__main__':build()
