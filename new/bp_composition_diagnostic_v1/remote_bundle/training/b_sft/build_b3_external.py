"""Short genuine external-evidence B3 lessons with paired binary/linear rules."""
from copy import copy,deepcopy
from collections import Counter
from fractions import Fraction
import hashlib,json
from pathlib import Path
import numpy as np
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.build_bp_pilot import make_task,topology
from training.b_sft.bp_semantics import semantic_id
from training.b_sft.decision_policy import VERSION as OBJECTIVE_VERSION
from training.b_sft.social_named_probe import request
from training.b_sft.social_bp_training import native_completion,reward
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/social_bp/b3_external_linear_v1'
VALUES=(1,0,-1);NAMES=('want','neutral','avoid')


def fixture(goals,binary):
 own=[1]*goals
 types=[[v,1] for v in VALUES] if goals==2 else [[v,u,1] for v in VALUES for u in VALUES]
 raw=dict(id='b3-external',ego=0,own_preferences=own,history=[],type_catalogues={'0':[own],'1':types},
  game=dict(n_players=2,n_actions_per_player=[1,2],max_changes=1,menu_enabled=False,
    round_robin=[0,1,0,1],goals=[dict(goal_id=g,binary=binary,
      required_actions=[dict(player_id=0,action_id=0),dict(player_id=1,action_id=min(g,1))]) for g in range(goals)]))
 return expand_support(raw)[:2]


def label(weights,worlds,goal):
 mass={name:float(sum(p for p,w in zip(weights,worlds) if w[1][goal]==v)) for name,v in zip(NAMES,VALUES)}
 possible=[v for v in NAMES if mass[v]>1e-12];leaders=[v for v in possible if mass[v]>=max(mass.values())-1e-9]
 return dict(possible_preferences=possible,favored=leaders[0] if len(leaders)==1 else 'undetermined'),mass


def local_policy_audit(tree):
 """Check fixed-profile action ranks at every actor information set.

 Counterfactual reach omits that actor's own action probabilities. Independent
 of response() and optimal_indices(); continuation values were payoff-audited.
 """
 count=0
 for player in range(tree.n):
  reach=[None]*len(tree.entries);reach[0]=tree.world_weights.copy()
  for i,e in enumerate(tree.entries):
   for ai,c in enumerate(e.children):reach[c]=reach[i] if e.actor==player else reach[i]*tree.policy[i][ai]
  for i,e in enumerate(tree.entries):
   if e.actor!=player:continue
   av=np.array([tree.values[c] for c in e.children])
   for ids in tree.information_groups[i]:
    w=reach[i][ids];w=tree.world_weights[ids] if w.sum()==0 else w;w=w/w.sum()
    means=np.einsum('awp,w->ap',av[:,ids],w);own=means[:,player]
    selected=np.flatnonzero(own>=max(own)-1e-9)
    if e.node.pending is not None:
     other=means.sum(axis=1)-own;selected=selected[other[selected]>=max(other[selected])-1e-9]
    expected=np.zeros(len(e.actions));expected[selected]=1/len(selected)
    np.testing.assert_allclose(tree.policy[i][:,ids],np.repeat(expected[:,None],len(ids),axis=1),atol=1e-9,rtol=0)
    count+=1
 return count


CASES=[
 dict(name='direct_followup',goals=2,query=0,first=dict(action='OFFER',partner_id=0,proposer_action=[0,0],partner_action=[1]),
      second=dict(action='OFFER',partner_id=1,proposer_action=[1],partner_action=[1,0])),
 dict(name='joint_exclusion',goals=3,query=0,first=dict(action='OFFER',partner_id=0,proposer_action=[1,0],partner_action=[0]),
      second=dict(action='OFFER',partner_id=1,proposer_action=[1],partner_action=[1,1])),
 dict(name='joint_favored',goals=3,query=1,first=dict(action='OFFER',partner_id=0,proposer_action=[0,1],partner_action=[0]),
      second=dict(action='OFFER',partner_id=1,proposer_action=[1],partner_action=[0,1]))]


def build():
 bank=list(map(json.loads,(ROOT/'examples/social_bp/data_two_a100_v1/tasks.jsonl').read_text().splitlines()))
 held={t['family'] for t in bank if t['split']!='train'}
 train_families={t['family'] for t in bank if t['split']=='train'}
 cache={};tasks=[];requests=[];checks=[];unavailable=[]
 for case in CASES:
  for binary in (True,False):
   raw,public=fixture(case['goals'],binary);family=topology(raw);assert family not in held
   key=(case['goals'],binary);setup=[dict(action='PASS')]
   if key not in cache:
    root=PrivateEpisode(raw,setup,seconds=30,max_nodes=60000)
    cache[key]=(root,audit_native(root.tree),local_policy_audit(root.tree))
   root,native,info_checks=cache[key]
   for response in ('ACCEPT','REJECT'):
    e=copy(root);e.events=[];events=[case['first'],dict(response='ACCEPT'),case['second'],dict(response=response)]
    initial=e._weights(0,raw['own_preferences'],[]);manual=initial.copy();trace=[];valid=True
    for index,action in enumerate(events):
     entry=e.tree.entries[e.index];ai=[a.to_dict() for a in entry.actions].index(action)
     before=manual.copy();lik=e.tree.policy[e.index][ai].copy();manual*=lik
     if manual.sum()<=0:
      unavailable.append(dict(case=case['name'],binary=binary,response=response,event=index,reason='zero likelihood under selected policy'))
      valid=False;break
     manual/=manual.sum()
     if index==3:
      previous,previous_mass=label(before,e.tree.worlds,case['query']);ablation=initial*lik
      assert ablation.sum()>0;ablation/=ablation.sum();ablation_gold,ablation_mass=label(ablation,e.tree.worlds,case['query'])
     before_gold,_=label(before,e.tree.worlds,case['query'])
     e.observe(action);actual=e._weights(0,raw['own_preferences'],[])
     np.testing.assert_allclose(manual,actual,atol=1e-9,rtol=0)
     gold,mass=label(actual,e.tree.worlds,case['query'])
     trace.append(dict(actor=entry.actor,external=entry.actor!=0,action=action,
                       joint_changed=not np.allclose(before,actual,atol=1e-9,rtol=0),
                       marginal_gold_changed=before_gold!=gold,gold=gold,marginal=mass,
                       joint_posterior=[str(Fraction(float(p)).limit_denominator(1000000)) for p in actual]))
    if not valid:continue
    assert trace[0]['external'] and trace[0]['joint_changed'] and trace[-1]['external']
    assert all(not t['joint_changed'] for t in trace if not t['external'])
    t=make_task(e,public,setup,events,'B',2,family,q=(1,case['query']),previous=previous,
                source='b3-external-v1:'+case['name']+(':'+('binary' if binary else 'linear')))
    assert family in train_families
    t['split']='train'  # Inherit the established family split, including bridge overrides.
    t.update(training_ready=False,objective_version=OBJECTIVE_VERSION,kernel='B3',
             completion_mode='binary' if binary else 'linear',b3_case=case['name'],
             b3_role='external_update' if gold!=previous else 'external_maintenance_control',
             previous_task_id=None)
    t['semantic_id']=semantic_id(t)
    t['teacher']['b3_audit']=dict(native=native,information_set_checks=info_checks,trace=trace,
      first_evidence_ablation=dict(gold=ablation_gold,marginal=ablation_mass,label_changes=ablation_gold!=gold,
        scope='Diagnostic: keep the selected policy and final public history fixed, reset observer world weights to initial prior before multiplying only the last-action likelihood. Not an alternate legal game rollout.'),
      genuine_external_events=sum(t['external'] for t in trace),
      both_external_events_change_joint=trace[0]['joint_changed'] and trace[-1]['joint_changed'])
    assert reward(t,native_completion(t))['reward']==1
    req=request(t,'action_tools',t['name_variant']);assert req['max_tokens']==1024
    if not binary:
     assert 'LINEAR' in req['messages'][1]['content'] and 'fraction' in req['messages'][1]['content']
    tasks.append(t);requests.append(dict(task_id=t['id'],condition='b3-external-v1',request=req))
    checks.append(dict(id=t['id'],case=case['name'],binary=binary,response=response,
      role=t['b3_role'],previous=previous,gold=gold,prior_mass=previous_mass,posterior=mass,
      ablation_label_changes=ablation_gold!=gold,both_external_events_change_joint=trace[0]['joint_changed'] and trace[-1]['joint_changed']))
 return tasks,requests,checks,unavailable


def main():
 tasks,requests,checks,unavailable=build();OUT.mkdir(parents=True,exist_ok=True);files={}
 for name,rows in [('tasks.jsonl',tasks),('requests.jsonl',requests)]:
  data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode();(OUT/name).write_bytes(data);files[name]=hashlib.sha256(data).hexdigest()
 previous=ROOT/'examples/social_bp/response_only_v1/kernels_v1/b2_b3/core_v1/bp_candidate_tasks.jsonl'
 candidate=list(map(json.loads,previous.read_text().splitlines()))+tasks
 assert len(candidate)==291 and len({t['id'] for t in candidate})==291
 data=''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in candidate).encode()
 (OUT/'bp_candidate_tasks.jsonl').write_bytes(data);files['bp_candidate_tasks.jsonl']=hashlib.sha256(data).hexdigest()
 assert len({t['id'] for t in tasks})==len(tasks)
 assert len({t['semantic_id'] for t in tasks})==len(tasks)
 manifest=dict(version='b3-external-linear-v1',tasks=len(tasks),completion_counts=dict(Counter(t['completion_mode'] for t in tasks)),
  role_counts=dict(Counter(t['b3_role'] for t in tasks)),checks=checks,unavailable=unavailable,files=files,
  training_ready=False,model_tested=False,merged=False,split='train',test_used=False,candidate_tasks=291,candidate_B_train=40,
  search_note='Teaching-only fixture exploration found cycles for several alternative own-preference settings and rejected single-player goals as illegal; no such cases labelled. This does not filter outcome self-play.')
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 cards=['# 新B3：完整题面与审核标签','']
 for t,r in zip(tasks,requests):
  cards += [f"## {t['b3_case']} / {t['completion_mode']} / {t['input']['voluntary_history'][-1]['response']}",'',
            '### 模型题面','',r['request']['messages'][1]['content'],'','### 本地审核，不发送给模型','',
            json.dumps(dict(gold=t['teacher']['gold'],audit=t['teacher']['b3_audit']),ensure_ascii=False),'']
 (OUT/'cards.md').write_text('\n'.join(cards)+'\n')
 print(json.dumps({k:v for k,v in manifest.items() if k not in ('files','checks')},ensure_ascii=False))
 print(json.dumps(checks,ensure_ascii=False))

if __name__=='__main__':main()
