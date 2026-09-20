"""Resumeable native-information audit. Never condition on supplied oracle beliefs."""
from copy import copy, deepcopy
import json
import hashlib
import numpy as np
from training.social_mixed.prepare_paired_bank import SOURCE, OUT
from training.social_mixed.prepare_distribution_curriculum import root_episode, stable
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.prepare_no_catalogue_probe import view
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.preference_contract import B_MARGIN


def rebuild(t):
    inp=t['input']; player=inp['observer']
    raw,own=reconstruct(inp); raw['background_prior']=inp['background_prior']
    root,audit=root_episode(stable([raw,inp['imposed_setup']]))
    e=copy(root);e.weights=root.weights.copy()
    interventions=[]
    for action in inp['voluntary_history']:
        entry=e.tree.entries[e.index]
        if action.get('action')=='INVESTIGATE' and entry.actor==player:
            # Match prepare_reasoning_v4.query_followups: own query is an intervention.
            index=next(i for i,a in enumerate(entry.actions) if a.to_dict()==action)
            e.index=entry.children[index];interventions.append(action)
        else:
            e.observe(action)
    facts=[(r['player'],r['goal'],{'want':1,'neutral':0,'avoid':-1}[r['preference']]) for r in inp['private_results']]
    entry=e.tree.entries[e.index]
    if entry.actor is None:return dict(status='terminal_no_action_point')
    if entry.actor!=player:return dict(status='other_player_action_point',actor=entry.actor)
    native=view(e,inp['public_preferences'],player,own,facts,inp['imposed_setup'],inp['voluntary_history'])
    repairs=[]
    old_state=deepcopy(inp['current_state'])
    if old_state.get('goals')!=native['current_state'].get('goals'):
        # Only stale duplicate flags are repairable; dependency changes are not.
        old_goals=deepcopy(old_state['goals']);new_goals=native['current_state']['goals']
        if len(old_goals)==len(new_goals):
            for old,new in zip(old_goals,new_goals):old['binary']=new['binary']
            if old_goals==new_goals:
                repairs.append(dict(field='current_state.goals',before=old_state['goals'],after=new_goals))
                old_state['goals']=new_goals
    if native['current_state']!=old_state or native['pending_offer']!=inp['pending_offer']:
        return dict(status='native_state_mismatch')
    weights=e._weights(player,own,facts)
    actions=[a.to_dict() for a in entry.actions]
    values=np.einsum('awp,w->ap',np.array([e.tree.values[c] for c in entry.children]),weights)
    indices=acceptable(values,player,actions=actions)
    if not indices or len(indices)==len(actions):return dict(status='no_action_discrimination')
    x=deepcopy(t)
    native.update(background_prior=inp['background_prior'],favored_margin=inp.get('favored_margin',B_MARGIN),legal_actions=actions,belief_source='history',supplied_belief=dict(known_preferences=[],unresolved_preferences=[],support='Infer from visible information.'))
    x.update(task='P',input=native,kernel=t['kernel'] if t['task']=='P' else 'P2',skill='history_planning',pool='planning')
    x['teacher']=dict(acceptable_actions=[actions[i] for i in indices],action_values=values.tolist(),posterior=weights.tolist(),worlds=e.tree.worlds,policy_sha256=e.tree.certificate['policy_sha256'],all_legal_accepted=False)
    return dict(status='reconstructed',task=x,native_audit=audit,state_repairs=repairs,own_query_interventions=interventions,original_acceptable_actions=t['teacher'].get('acceptable_actions'))


def main():
    OUT.mkdir(exist_ok=True)
    path=OUT/'reconstruction.jsonl'
    previous={r['source_sha256']:r for r in map(json.loads,path.read_text().splitlines())} if path.exists() else {}
    retry={'native_state_mismatch','query_history_requires_intervention_audit'}
    done={sha for sha,r in previous.items() if r['status'] not in retry or r.get('reconstruction_revision')==2}
    with path.open('a') as out:
        for split in ('train','validation'):
            for t in map(json.loads,(SOURCE/f'bp_{split}.jsonl').read_text().splitlines()):
                if t.get('b_bridge') or t.get('oracle_pair_of') or t['input'].get('belief_source')=='history':continue
                sha=hashlib.sha256(stable(t).encode()).hexdigest()
                if sha in done:continue
                try:r=rebuild(t)
                except (ValueError,AssertionError,RuntimeError) as exc:r=dict(status='reconstruction_failed',error=type(exc).__name__+': '+str(exc))
                r.update(id=t['id'],split=split,source_sha256=sha,reconstruction_revision=2)
                out.write(json.dumps(r)+'\n');out.flush()
                print(split,t['id'],r['status'],flush=True)
if __name__=='__main__':main()
