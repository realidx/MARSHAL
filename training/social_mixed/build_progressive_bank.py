"""Native, independently specified small scenes, with original B/O/P interfaces.
Candidate only: no runtime bank replacement, no model-based selection.
"""
from copy import copy,deepcopy
from itertools import product
from pathlib import Path
from collections import Counter
import hashlib,json
import numpy as np
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.prepare_no_catalogue_probe import view,expand_support
from training.b_sft.preference_contract import belief,profile
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.decision_policy import VERSION as OBJECTIVE
from training.b_sft.debug.audit_readable_pretraining import independent_backward,reconstruct
from training.social_mixed.paired_requests import request
from training.social_mixed.reasoning_scoring import score
from training.b_sft.social_bp_training import native_completion

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/social_mixed/progressive_bank_v1'
NAMES={1:'want',0:'neutral',-1:'avoid'}
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def digest(x):return hashlib.sha256(stable(x).encode()).hexdigest()


def certify(pay,actions):
    from training.b_sft.decision_policy import is_offer_response
    own=pay[:,:,0];social=pay[:,:,1:].sum(axis=2) if is_offer_response(actions) else np.zeros_like(own)
    labels=[]
    for i in range(len(actions)):
        positive=all(np.all(own[j]-own[i]<=.1+1e-9) and
                     (np.all(own[i]-own[j]>1e-9) or np.all(social[j]-social[i]<=.1+1e-9)) for j in range(len(actions)))
        negative=any(np.all(own[j]-own[i]>.1+1e-9) or
                     (np.all(np.abs(own[j]-own[i])<=1e-12) and np.all(social[j]-social[i]>.1+1e-9)) for j in range(len(actions)))
        assert not(positive and negative)
        labels.append('positive' if positive else 'negative' if negative else 'masked')
    return labels


def build():
    OUT.mkdir(exist_ok=True);tasks={};relations=[];roots=[];errors=[]
    # Fixed geometric families; all priors/history/revelation variants share a split.
    for geometry,mode,own0 in product(('separate','shared'),('binary','linear'),(1,-1)):
        goals=[dict(goal_id=0,binary=mode=='binary',required_actions=[dict(player_id=0,action_id=0),dict(player_id=1,action_id=0)]),
               dict(goal_id=1,binary=mode=='binary',required_actions=[dict(player_id=0,action_id=1 if geometry=='separate' else 0),dict(player_id=1,action_id=1)])]
        family=digest([geometry,mode,own0])
        # Whole geometry held out, never renamed copies across splits.
        split='validation' if geometry=='shared' else 'train'
        for prior in ('balanced','avoid_heavy'):
            for route,order,setup in [('revealed',[0,1,1,0],[dict(action='INVESTIGATE',player=1,goal=0),dict(action='PASS'),dict(action='PASS')]),
                                      ('single_choice',[0,1],[dict(action='PASS')]),('two_choice',[1,0],[]),
                                      ('query_update',[1,0,0,1],[dict(action='PASS')])]:
                raw=dict(id=family,game=dict(n_players=2,n_actions_per_player=[2,2],goals=goals,round_robin=order,max_changes=1,seed=0,forbidden_actions=None),
                    ego=0,own_preferences=[own0,1],type_catalogues={'0':[[own0,1]],'1':[[v,1] for v in (1,0,-1)]},history=[],background_prior=profile(prior))
                raw,public,_=expand_support(raw)
                try:
                    ep=PrivateEpisode(raw,setup,seconds=20,max_nodes=30000,max_sweeps=128)
                    native=audit_native(ep.tree);independent=independent_backward(ep.tree)
                    # Verify unknown-world support reconstructed from public facts.
                    initial=view(ep,public,0,raw['own_preferences'],[],setup,[])
                    rebuilt,_=reconstruct(initial)
                    assert rebuilt['type_catalogues']==raw['type_catalogues']
                except Exception as exc:
                    errors.append(dict(family=family,route=route,prior=prior,error=repr(exc)));continue
                roots.append(dict(family=family,route=route,prior=prior,policy=ep.tree.certificate['policy_sha256'],native=native,independent=independent))
                def emit(node,events,facts,parent=None):
                    entry=node.tree.entries[node.index]
                    if entry.actor!=0:return None
                    weights=node._weights(0,raw['own_preferences'],facts)
                    inp=view(node,public,0,raw['own_preferences'],facts,setup,events)
                    actions=[a.to_dict() for a in entry.actions]
                    pay=np.asarray([node.tree.values[ch] for ch in entry.children]);values=np.einsum('awp,w->ap',pay,weights)
                    good=acceptable(values,0,actions=actions)
                    if not good or len(good)==len(actions):return None
                    inp.update(background_prior=profile(prior),favored_margin=.1,legal_actions=actions,belief_source='history',supplied_belief=dict(known_preferences=[],unresolved_preferences=[],support='Infer from visible information.'))
                    mass=node.belief(1,0,observer=0,own=raw['own_preferences'],private_results=facts)['preference_weights']
                    gold=belief(mass)
                    stage='direct_evidence' if facts else ('single_choice_identifying' if len(gold['possible_preferences'])==1 else 'single_choice_uncertain') if route=='single_choice' else 'continued_choice'
                    canonical=digest(inp);key=canonical[:20]
                    base=dict(id=key,task='P',input=inp,teacher=dict(acceptable_actions=[actions[j] for j in good],action_values=values.tolist(),posterior=weights.tolist(),worlds=node.tree.worlds,policy_sha256=node.tree.certificate['policy_sha256'],all_legal_accepted=False),
                       skill='result_use' if facts else 'history_planning',pool='planning',kernel='P4' if facts else 'P2',source_kernel='P4' if facts else 'P2',family=family,package_id=family,canonical_id=canonical,split=split,completion_mode=mode,objective_version=OBJECTIVE,training_ready=False,name_variant=0,prompt_clarification='required-commitments-v1',source='progressive-native-v1',generation_route=route,learning_stage=stage,belief_action_relevant=False)
                    relevant=not bool(set.intersection(*[set(acceptable(pay[:,w,:],0,actions=actions)) for w in range(len(weights)) if weights[w]>0]))
                    base['belief_action_relevant']=relevant
                    supported=np.flatnonzero(weights>0);labels=certify(pay[:,supported,:],actions)
                    remaining=len(inp['game']['round_robin'])-inp['current_state']['turn_index']
                    base['planning_stage']=('known' if len(supported)==1 else 'uncertain')+('_terminal' if remaining<=1 else '_multistep')
                    eligible='positive' in labels and 'negative' in labels
                    for v in ('O','B','Pplus'):
                        t=deepcopy(base);t.update(id=key+'-'+v,paired_view=v,canonical_action_task=deepcopy(base),p_train_eligible=eligible,p_pool_status='certified' if eligible else 'insufficient_robust_contrast')
                        if v=='B':
                            t.update(task='B',skill='formation',pool='formation',kernel='B1')
                            t['input'].update(task='formation',queries=[dict(player=1,goal=0)])
                            t['teacher']=dict(gold=gold,preference_weights=mass,policy_sha256=node.tree.certificate['policy_sha256'])
                        if v=='Pplus':
                            beliefs=[]
                            for g in range(2):
                                m={NAMES[x]:float(sum(weights[w] for w,world in enumerate(node.tree.worlds) if world[1][g]==x)) for x in (1,0,-1)}
                                beliefs.append(dict(player=1,goal=g,**belief(m)))
                            t['input']['supplied_belief']=dict(known_preferences=[],unresolved_preferences=[],support="Use the supplied qualitative beliefs.",semantic_beliefs=beliefs)
                            t.update(p_information_contract='history-free-qualitative-v1',source_input_is_audit_only=True,p_supervision=dict(action_states=labels,certification='whole_supported_simplex_sufficient_bounds',limitation='Fixed continuation may depend on source history; not general planner certification.'))
                        req=request(t)
                        if v=='Pplus':assert 'EVENTS IN ORDER' not in req['messages'][-1]['content'] and 'joint_distribution' not in req['messages'][-1]['content']
                        if v in ('B','O'):assert score(t,native_completion(t))['correct']
                        if v=='Pplus':
                            assert all(j in good for j,label in enumerate(labels) if label=='positive')
                            assert all(j not in good for j,label in enumerate(labels) if label=='negative')
                        tasks[t['id']]=t
                    if parent and parent!=canonical:
                        before=tasks[parent[:20]+'-B']['teacher']['gold']
                        relations.append(dict(left=parent,right=canonical,family=family,split=split,relation='maintain' if before==gold else 'update'))
                    return canonical
                if route=='query_update':
                    parent=emit(ep,[],[])
                    entry=ep.tree.entries[ep.index]
                    for j,act in enumerate(entry.actions):
                        a=act.to_dict()
                        if a!=dict(action='INVESTIGATE',player=1,goal=0):continue
                        child=copy(ep);child.weights=ep.weights.copy();child.index=entry.children[j]
                        for value in (1,0,-1):emit(child,[a],[(1,0,value)],parent)
                elif route=='revealed':
                    for value in (1,0,-1):emit(ep,[],[(1,0,value)])
                else:
                    # All ordinary first offers with nonzero likelihood; no outcome-based selection.
                    entry=ep.tree.entries[ep.index]
                    for act in entry.actions:
                        a=act.to_dict()
                        if a.get('action')!='OFFER':continue
                        node=copy(ep);node.weights=ep.weights.copy()
                        try:node.observe(a)
                        except ValueError:continue
                        parent=emit(node,[a],[])
                        response_entry=node.tree.entries[node.index]
                        for response in response_entry.actions:
                            child=copy(node);child.weights=node.weights.copy()
                            try:child.observe(response.to_dict())
                            except ValueError:continue
                            emit(child,[a,response.to_dict()],[],parent)
    rows=list(tasks.values())
    for filename,records in [('tasks.jsonl',rows),('relations.jsonl',relations),('root_audits.jsonl',roots),('errors.jsonl',errors)]:
        (OUT/filename).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
    for split in ('train','validation'):
        common=[t for t in rows if t['split']==split and t['p_train_eligible']]
        (OUT/f'common_{split}.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in common))
    summary=dict(status='candidate_not_runtime_bank',parents=len(rows)//3,tasks=len(rows),errors=len(errors),roots=len(roots),
       counts=dict(Counter(t['split']+'/'+t['learning_stage'] for t in rows if t['paired_view']=='B')),
       eligible_common_parents=sum(t['p_train_eligible'] for t in rows if t['paired_view']=='Pplus'),relations=len(relations),
       relation_types=dict(Counter(r['relation'] for r in relations)),
       planning_stages=dict(Counter(t['split']+'/'+t['planning_stage'] for t in rows if t['paired_view']=='Pplus' and t['p_train_eligible'])),
       excluded_root_reasons=dict(Counter(r['error'] for r in errors)),
       empirical_difficulty_verified=False,training_started=False)
    (OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2))
    if not rows:raise RuntimeError('No certified candidate scenes')

if __name__=='__main__':build()
