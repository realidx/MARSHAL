"""Generate transparent single-unknown feedback variants from existing structures."""
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
from new.diagnostic_v7.initial_state import InitialEpisode,request
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.preference_contract import belief
from training.b_sft.social_private_teacher import audit_native
from training.b_sft.prepare_no_catalogue_probe import view
from training.b_sft.social_bp_curriculum import acceptable

HERE=Path(__file__).resolve().parent

def main():
    candidates=json.loads((HERE/'candidates.json').read_text());generated=[];errors=[]
    for source in candidates:
        old=source['task']['input'];facts=old['private_results']
        if len(facts)!=1:continue
        query={k:facts[0][k] for k in ('player','goal')}
        for fixed in ('neutral','want','avoid'):
            try:
                inp=deepcopy(old);known={(f['player'],f['goal']) for f in inp['public_preferences']}
                # Resolve all other hidden slots explicitly in public facts, not secretly in teacher.
                for p in range(inp['game']['n_players']):
                    for g in range(len(inp['game']['goals'])):
                        if (p,g) not in known and (p,g)!=(query['player'],query['goal']):
                            inp['public_preferences'].append(dict(player=p,goal=g,preference=fixed))
                raw,own=reconstruct(inp);raw['background_prior']=inp['background_prior']
                ep=InitialEpisode(raw,source['initial_state'],seconds=10,max_nodes=30000,max_sweeps=128)
                for event in inp['voluntary_history']:ep.observe(event)
                private=[(f['player'],f['goal'],{'want':1,'neutral':0,'avoid':-1}[f['preference']]) for f in facts]
                node=ep.tree.entries[ep.index];actor=inp['observer']
                marginal=ep.belief(query['player'],query['goal'],observer=actor,own=own,private_results=private)['preference_weights']
                i=view(ep,inp['public_preferences'],actor,own,private,[],inp['voluntary_history'])
                i.update(initial_commitments=source['initial_state']['commitments'],initial_turn_index=source['initial_state'].get('turn_index',0),
                    background_prior=raw['background_prior'],favored_margin=.1,queries=[query])
                acts=[a.to_dict() for a in node.actions];weights=ep._weights(actor,own,private)
                pay=np.array([ep.tree.values[x] for x in node.children]);values=np.einsum('awp,w->ap',pay,weights)
                t=dict(gold=belief(marginal),preference_weights=marginal,worlds=ep.tree.worlds,posterior=weights.tolist(),
                    per_world_payoffs=pay.tolist(),action_values=values.tolist(),policy_sha256=ep.tree.certificate['policy_sha256'],
                    acceptable_actions=[acts[j] for j in acceptable(values,actor,actions=acts)])
                i.update(legal_actions=acts,supplied_belief=dict(known_preferences=i['public_preferences'],unresolved_preferences=[query],support='Infer from visible information.'))
                task=dict(id=source['id']+'-feedback-'+fixed,task='B',condition='B',skill='formation',input=i,teacher=t)
                o=deepcopy(task);o.update(task='P',condition='P_infer',skill='history_planning')
                c=dict(source,id=task['id'],raw=raw,task=task,requests=dict(B=request(task,source['initial_state']),O=request(o,source['initial_state'])),
                    native_audit=audit_native(ep.tree),derivation='Other unknowns publicly fixed; query targets actual delivered private feedback',fixed_other_preference=fixed)
                generated.append(c)
            except (ValueError,AssertionError,RuntimeError) as e:errors.append(dict(id=source['id'],fixed=fixed,error=str(e)))
    (HERE/'feedback_candidates.json').write_text(json.dumps(generated,indent=2)+'\n')
    (HERE/'feedback_audit.json').write_text(json.dumps(dict(generated=len(generated),rejected=errors),indent=2)+'\n')
    print('Feedback variants:',len(generated),'excluded:',len(errors))

if __name__=='__main__':main()
