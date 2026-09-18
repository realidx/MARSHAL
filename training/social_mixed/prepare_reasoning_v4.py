"""Build a candidate reasoning curriculum from development sources only.

Existing releases and final evaluations are immutable. Teacher failures are logged.
"""
from collections import Counter
from copy import copy, deepcopy
import hashlib
import json
from pathlib import Path
import numpy as np
from training.social_mixed.core import ROOT, seed_for
from training.social_mixed.structure_coverage import geometry_id, audit
from training.social_mixed.prepare_distribution_curriculum import root_episode, stable, annotate
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.prepare_no_catalogue_probe import view
from training.b_sft.preference_contract import belief, VERSION, B_MARGIN
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.social_private_teacher import observed_slots

SOURCE=ROOT/'examples/social_mixed/data_binary_linear_v3'
OUT=ROOT/'examples/social_mixed/data_reasoning_v4_candidate'
VALUES={'want':1,'neutral':0,'avoid':-1}

def read(path):return [json.loads(l) for l in path.read_text().splitlines()]
def digest(x):return hashlib.sha256(stable(x).encode()).hexdigest()[:20]

def task_at(base,e,setup,events,facts,kind,q=(1,0),previous=None):
    own=e.raw['own_preferences'];inp=view(e,base['input']['public_preferences'],0,own,facts,setup,events)
    inp.update(background_prior=base['input']['background_prior'],favored_margin=B_MARGIN)
    t=deepcopy(base);t.update(input=inp,task=kind,source='reasoning-v4:'+base['id'],origin_id=base['id'],
        reasoning_source_id=base['id'],structure_family=geometry_id(inp['game']),teacher={},diagnostic_only=False,training_ready=True)
    t.pop('p4_case',None)
    if kind=='B':
        b=e.belief(*q,observer=0,own=own,private_results=facts);gold=belief(b['preference_weights'])
        inp.update(queries=[dict(player=q[0],goal=q[1])],task='formation')
        t.update(kernel='B1',skill='formation',pool='formation')
        if previous is not None:
            inp.update(previous_belief=previous,old_history=events[:-1],new_history=events[-1:])
            t.update(kernel='B3',skill='maintain' if previous==gold else 'update',pool='maintain' if previous==gold else 'update')
            inp['task']=t['skill']
        t['teacher']=dict(gold=gold,preference_weights=b['preference_weights'],favored_margin=B_MARGIN)
    else:
        entry=e.tree.entries[e.index]
        if entry.actor!=0:return None
        weights=e._weights(0,own,facts)
        actions=[a.to_dict() for a in entry.actions]
        pay=np.array([e.tree.values[c] for c in entry.children]);values=np.einsum('awp,w->ap',pay,weights)
        indices=acceptable(values,0,actions=actions)
        if not indices or len(indices)==len(actions):return None
        inp.update(legal_actions=actions,belief_source='history',supplied_belief=dict(known_preferences=[],unresolved_preferences=[],support='Infer from visible history.'))
        t.update(kernel='P4' if facts else 'P2',skill='result_use' if facts else 'history_planning',pool='planning')
        if facts:t['p4_case']='answer_use'
        prior=e.tree.world_weights*np.array([w[0]==tuple(own) and all(w[p][g]==v for p,g,v in facts) for w in e.tree.worlds]);prior/=prior.sum()
        prior_values=np.einsum('awp,w->ap',pay,prior)
        prior_indices=acceptable(prior_values,0,actions=actions)
        t['teacher']=dict(history_changes_acceptable=set(indices)!=set(prior_indices),prior_acceptable_actions=[actions[j] for j in prior_indices],acceptable_actions=[actions[j] for j in indices],action_values=values.tolist(),posterior=weights.tolist(),worlds=e.tree.worlds,all_legal_accepted=False)
    t['teacher'].update(policy_sha256=e.tree.certificate['policy_sha256'],objective_version=base['objective_version'])
    t['contrast_group']='reasoning-v4:'+digest([base['id'],kind,setup])
    t['id']=digest([t['contrast_group'],inp]);t['native_task_id']=t['id'];t['answer_signature']=stable(t['teacher'].get('gold',t['teacher'].get('acceptable_actions')))
    t['training_pack_version']=VERSION;t['contract_version']=VERSION
    t=annotate(t)
    t['b3_case']=t['contrast_group'];t['p123_case']=t['contrast_group']
    return t

def history_lessons(base):
    """Retain native prefixes, exposing inference before the subsequent action."""
    inp=base['input'];raw,own=reconstruct(inp);raw['background_prior']=inp['background_prior']
    setup=inp['imposed_setup'];root,_=root_episode(stable([raw,setup]));e=copy(root);e.weights=root.weights.copy()
    events=[];rows=[]
    # Only public evidence traces; private-result branching is handled separately.
    if inp['private_results']:return []
    q=(inp['queries'][0]['player'],inp['queries'][0]['goal'])
    for action in inp['voluntary_history']:
        if action.get('action')=='INVESTIGATE':break
        previous=belief(e.belief(*q,observer=0,own=own)['preference_weights'])
        e.observe(action);events.append(action)
        b=task_at(base,e,setup,list(events),[],'B',q,previous);rows.append(b)
        p=task_at(base,e,setup,list(events),[],'P')
        if p:
            p['linked_b_id']=b['id'];rows.append(p)
    return rows

def query_followups(base):
    inp=base['input'];raw,own=reconstruct(inp);raw['background_prior']=inp['background_prior'];setup=inp['imposed_setup']
    root,_=root_episode(stable([raw,setup]));rows=[]
    # Query is an intervention by the learner: do not multiply by teacher query likelihood.
    entry=root.tree.entries[0]
    if entry.actor!=0:return []
    for ai,action in enumerate(entry.actions):
        a=action.to_dict()
        if a.get('action')!='INVESTIGATE':continue
        if len({w[a['player']][a['goal']] for w in root.tree.worlds})<2:continue
        for value in (1,0,-1):
            facts=[(a['player'],a['goal'],value)];e=copy(root);e.weights=root.weights.copy();e.index=entry.children[ai]
            try:e._weights(0,own,facts)
            except ValueError:continue
            frontier=[(e,[a])]
            for depth in range(3):
                next_frontier=[]
                for node,events in frontier:
                    ent=node.tree.entries[node.index]
                    if ent.actor is None:continue
                    if ent.actor==0:
                        t=task_at(base,node,setup,events,facts,'P')
                        if t:rows.append(t)
                        continue
                    for act in ent.actions:
                        child=copy(node)
                        try:child.observe(act.to_dict());child._weights(0,own,facts)
                        except ValueError:continue
                        next_frontier.append((child,events+[act.to_dict()]))
                frontier=next_frontier
    return rows

def main():
    OUT.mkdir(exist_ok=True)
    packs={n:read(SOURCE/(n+'.jsonl')) for n in ('bp_train','bp_validation','bp_test','selfplay_train','selfplay_validation')}
    # Select one background per source structure/mode; all original tasks stay in their split.
    candidates=[];seen=set()
    for split in ('train','validation'):
        for t in sorted(packs['bp_'+split],key=lambda t:t['id']):
            if t['background_profile']!='balanced':continue
            if t['kernel'] not in ('B1','B2','B3','P4'):continue
            key=(split,t['kernel']=='P4',geometry_id(t['input']['game']),t['completion_mode'])
            if key in seen:continue
            seen.add(key);candidates.append(t)
    (OUT/'candidate_freeze.json').write_text(json.dumps([dict(id=t['id'],split=t['split'],kernel=t['kernel']) for t in candidates],indent=2))
    added=[];errors=[]
    with (OUT/'build_progress.jsonl').open('w') as log:
        for t in candidates:
            try:
                rows=query_followups(t) if t['kernel']=='P4' else history_lessons(t)
                added.extend(rows);event=dict(id=t['id'],split=t['split'],count=len(rows),status='ok')
            except Exception as exc:
                event=dict(id=t['id'],split=t['split'],status='unavailable',error=repr(exc));errors.append(event)
            log.write(json.dumps(event)+'\n');log.flush();print(json.dumps(event),flush=True)
            root_episode.cache_clear()
    for split in ('train','validation'):
        packs['bp_'+split]+=list({t['id']:t for t in added if t['split']==split}.values())
    for name,rows in packs.items():(OUT/(name+'.jsonl')).write_text(''.join(json.dumps(t)+'\n' for t in rows))
    report=audit(OUT)
    if report['cross_split_families']:raise ValueError('Geometry leakage')
    (OUT/'structure_audit.json').write_text(json.dumps(report,indent=2))
    (OUT/'build_summary.json').write_text(json.dumps(dict(added=dict(Counter((t['split']+'/'+t['kernel']+'/'+t['skill']) for t in added)),errors=errors,training_ready=False),indent=2))

if __name__=='__main__':main()
