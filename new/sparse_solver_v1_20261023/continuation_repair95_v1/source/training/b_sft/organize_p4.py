"""Information acquisition/use contrasts under private investigation, CPU only."""
from collections import Counter,defaultdict
from copy import copy,deepcopy
import hashlib,json
import numpy as np
from training.b_sft.organize_p123 import ROOT,read,stable,old_audit,scoring_neutral
from training.b_sft.build_b3_external import local_policy_audit
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.prepare_no_catalogue_probe import expand_support
from training.b_sft.social_private_teacher import PrivateEpisode,observed_slots,audit_native,Investigate
from training.b_sft.social_bp_curriculum import acceptable
from training.b_sft.build_bp_pilot import make_task,topology,split_for
from training.b_sft.bp_semantics import semantic_id
from training.b_sft.decision_policy import VERSION
from training.b_sft.social_named_probe import request
from training.b_sft.social_bp_training import native_completion,reward
SOURCE=ROOT/'examples/social_bp/response_only_v1/tasks.jsonl'
PREVIOUS=ROOT/'examples/social_bp/p123_core_linear_v1/bp_candidate_tasks.jsonl'
OUT=ROOT/'examples/social_bp/p4_information_core_v1'
BASE_ID='ad530e27a311e2561910'
COST_ID='8d30b78d278f01c76b37'
ALTERNATIVE_ID='57bd4e9035700c4f8d05'


def fixture(bank,case,scoring):
 source=BASE_ID if case in ('acquisition','deadline','target_selection') else COST_ID if case=='opportunity_cost' else ALTERNATIVE_ID
 raw,_=reconstruct(bank[source]['input']);raw=deepcopy(raw)
 setup=deepcopy(bank[source]['input']['imposed_setup'])
 for g in raw['game']['goals']:g['binary']=scoring=='binary'
 if case=='deadline':raw['game']['round_robin']=[1,0]
 if case=='target_selection':
  raw['game']['n_actions_per_player']=[3,3]
  raw['game']['goals'].append(dict(goal_id=5,binary=scoring=='binary',required_actions=[dict(player_id=p,action_id=2) for p in (0,1)]))
  raw['own_preferences'].append(1);raw['type_catalogues']['0']=[raw['own_preferences']]
  raw['type_catalogues']['1']=[row+[v] for row in raw['type_catalogues']['1'] for v in (1,0,-1)]
  setup=[dict(action='OFFER',partner_id=0,proposer_action=[0,0,1],partner_action=[0,0,1]),dict(response='ACCEPT')]
 raw,public,_=expand_support(raw)
 return raw,public,setup,source


def query_report(e):
 c=e.choices(e.raw['own_preferences']);q=[i for i,a in enumerate(c['actions']) if a.get('action')=='INVESTIGATE']
 ordinary=[i for i in range(len(c['actions'])) if i not in q]
 bestq=max(c['values'][i][0] for i in q);besto=max(c['values'][i][0] for i in ordinary);gap=bestq-besto
 indices=acceptable(c['values'],0,actions=c['actions'])
 accepted_query=any(i in q for i in indices);accepted_ordinary=any(i in ordinary for i in indices)
 return dict(best_query_own=bestq,best_ordinary_own=besto,own_query_margin=gap,
  exact_relation='better' if gap>1e-9 else 'worse' if gap < -1e-9 else 'tied',
  rewarded_relation='query_only' if not accepted_ordinary else 'ordinary_only' if not accepted_query else 'both',
  query_values=[dict(action=c['actions'][i],own_value=c['values'][i][0],accepted=i in indices) for i in q])


def blind_query_result(e,query):
 """Best response with this private answer removed from learner information sets.

 Keep all public histories, physical transitions, quota costs and other players'
 selected policies. Re-optimize every subsequent learner decision, including
 later responses. This is a fixed-partner causal diagnostic, not a re-solved game.
 """
 tree=e.tree;player=0;slot=(query['player'],query['goal']);root=tree.entries[e.index]
 ai=[a.to_dict() for a in root.actions].index(query);start=root.children[ai]
 ids=[];stack=[start]
 while stack:
  i=stack.pop();ids.append(i);stack.extend(tree.entries[i].children)
 reach={start:e._weights(0,e.raw['own_preferences'],[])};values={};checks=0
 for i in sorted(ids):
  ent=tree.entries[i]
  for a,c in enumerate(ent.children):reach[c]=reach[i] if ent.actor==player else reach[i]*tree.policy[i][a]
 for i in sorted(ids,reverse=True):
  ent=tree.entries[i]
  if ent.actor is None:values[i]=ent.payoff;continue
  av=np.array([values[c] for c in ent.children])
  if ent.actor!=player:
   values[i]=np.einsum('aw,awp->wp',tree.policy[i],av);continue
  groups=defaultdict(list)
  slots=[s for s in observed_slots(ent.node,player) if s!=slot]
  for wi,w in enumerate(tree.worlds):groups[(w[player],tuple(w[p][g] for p,g in slots))].append(wi)
  policy=np.zeros((len(ent.actions),tree.w))
  for group in groups.values():
   group=np.array(group);w=reach[i][group]
   if w.sum()==0:w=tree.world_weights[group]
   means=np.einsum('awp,w->ap',av[:,group],w/w.sum());own=means[:,player]
   best=np.flatnonzero(own>=own.max()-1e-9)
   if ent.node.pending is not None:
    others=means.sum(axis=1)-own;best=best[others[best]>=others[best].max()-1e-9]
   policy[np.ix_(best,group)]=1/len(best);checks+=1
  values[i]=np.einsum('aw,awp->wp',policy,av)
 weights=e._weights(0,e.raw['own_preferences'],[])
 informed=np.average(tree.values[start],axis=0,weights=weights)
 blind=np.average(values[start],axis=0,weights=weights)
 assert informed[0]>=blind[0]-1e-9
 return dict(query=query,informed_value=informed.tolist(),result_blind_value=blind.tolist(),
  own_answer_use_gain=float(informed[0]-blind[0]),blinded_information_sets=checks,
  scope='Hide only this result from every subsequent learner decision; same public query, turn/quota cost and fixed partner policies. Learner may still infer from later public actions. No counterfactual equilibrium claim.')


def privacy_report(e,query):
 entry=e.tree.entries[e.index];q=Investigate(query['player'],query['goal']);public=None;count=0
 for world in e.tree.worlds:
  child=e.rules.step(entry.node,q,realized_world=world)
  if public is None:public=child.state.public_state()
  else:assert public==child.state.public_state()
  assert child.worlds==entry.node.worlds
  for p in range(e.tree.n):
   obs=e.rules.observation(child,p,world[p]);results=obs['private_results']
   if p==entry.actor:
    assert len(results)==1 and results[0]['preference']=={1:'want',0:'neutral',-1:'avoid'}[world[q.player][q.goal]]
   else:assert not results
  assert child.state.snapshot_commitments()==entry.node.state.snapshot_commitments()
  assert child.state.turn_index==entry.node.state.turn_index+1
  before=entry.node.state.public_state()['investigation_remaining_by_player'];after=public['investigation_remaining_by_player']
  assert after==[0 if p==entry.actor else value for p,value in enumerate(before)]
  if e.rules.actor(child)==entry.actor:
   assert not any(isinstance(a,Investigate) for a in e.rules.actions(child))
  count+=1
 return dict(worlds_checked=count,public_state_identical_across_answers=True,answer_only_to_investigator=True,
  other_players_quotas_unchanged=True,commitments_unchanged=True,one_opportunity_consumed=True)


def annotate(t,case,scoring,source,role,checks):
 if t is None:raise ValueError('All-legal/no-answer task must remain outside core')
 t.update(training_ready=False,objective_version=VERSION,kernel='P4',p4_case=case,p4_role=role,
  completion_mode=scoring,source_task_id=source,short_teaching=True,split='train',contrast_group='p4:'+case)
 t['semantic_id']=semantic_id(t);t['teacher']['p4_audit']=checks
 if role=='acquisition_decision':
  qr=checks['query_comparison'];t['teacher']['own_query_margin']=qr['own_query_margin']
  t['information_positive']=qr['rewarded_relation']=='query_only'
  t['information_negative_kind']='last_opportunity' if case=='deadline' else 'future_opportunity_remains' if qr['rewarded_relation']=='ordinary_only' else None
 return t


def build():
 source=read(SOURCE);bank={t['id']:t for t in source};old=[t for t in source if t['task']=='P' and t['skill']=='information']
 cache={};audits=[]
 for t in old:
  if t['split']!='train':continue
  audit=old_audit(t,cache);raw,_=reconstruct(t['input']);key=stable([raw,t['input']['imposed_setup']]);e=cache[key][0]
  audit['query_comparison']=query_report(e)
  assert abs(audit['query_comparison']['own_query_margin']-t['teacher']['own_query_margin'])<1e-9
  audits.append(audit)
 held={t['family'] for t in source if t['split']!='train'};train={t['family'] for t in source if t['split']=='train'}
 tasks=[];links=[]
 for case in ('acquisition','deadline','target_selection','opportunity_cost','ordinary_alternative'):
  for scoring in ('binary','linear'):
   raw,public,setup,origin=fixture(bank,case,scoring);family=topology(raw)
   assert family not in held and (family in train or split_for(family)=='train')
   e=PrivateEpisode(raw,setup,seconds=30,max_nodes=60000)
   checks=dict(native=audit_native(e.tree),information_set_checks=local_policy_audit(e.tree),query_comparison=query_report(e))
   positive=checks['query_comparison']['rewarded_relation']=='query_only'
   query=dict(action='INVESTIGATE',player=1,goal=0)
   checks['privacy']=privacy_report(e,query)
   checks['answer_use_ablation']=blind_query_result(e,query)
   if positive:
    assert checks['answer_use_ablation']['own_answer_use_gain']>.1
   if case=='target_selection':
    checks['irrelevant_answer_ablation']=blind_query_result(e,dict(action='INVESTIGATE',player=1,goal=5))
    assert abs(checks['irrelevant_answer_ablation']['own_answer_use_gain'])<1e-9
   t=make_task(e,public,setup,[],'P',2,family,pool='information',source='p4-core-v1:'+case)
   t=annotate(t,case,scoring,origin,'acquisition_decision',checks);tasks.append(t)
   if case=='acquisition':
    branch=copy(e);branch.events=[];prior=branch.weights.copy();branch.observe(query)
    np.testing.assert_allclose(branch.weights,prior,atol=1e-9,rtol=0)
    assert branch.tree.entries[branch.index].actor==0
    result_tasks=[];avg=np.zeros(e.tree.n)
    for value in (1,0,-1):
     facts=[(1,0,value)];weights=branch._weights(0,raw['own_preferences'],facts)
     c=branch.choices(raw['own_preferences'],facts)
     probability=float(sum(p for p,w in zip(prior,branch.tree.worlds) if w[1][0]==value))
     conditional=np.average(branch.tree.values[branch.index],axis=0,weights=weights);avg+=probability*conditional
     child=make_task(branch,public,setup,[query],'P',1,family,facts=facts,pool='result_use',source='p4-core-v1:answer-use',include_uninformative=True)
     child=annotate(child,'answer_use',scoring,origin,'result_use',dict(parent_task_id=t['id'],
        result_value=value,result_probability=probability,conditional_policy_value=conditional.tolist(),
        public_posterior_unchanged_by_answer=True,selection_policy_sha256=e.tree.certificate['policy_sha256']))
     child['p4_parent_task_id']=t['id'];tasks.append(child);result_tasks.append(child)
    np.testing.assert_allclose(avg,checks['answer_use_ablation']['informed_value'],atol=1e-9,rtol=0)
    common=set.intersection(*[{stable(a) for a in s['teacher']['acceptable_actions']} for s in result_tasks])
    assert not common,'One fixed action can pass every result-use branch'
    links.append(dict(parent=t['id'],children=[c['id'] for c in result_tasks],scoring=scoring,
      result_values=[1,0,-1],same_public_state=True,all_outcomes_have_positive_probability=True,
      no_single_action_passes_all_results=True,conditional_values_reconstruct_query_value=True))
 return source,old,tasks,audits,links


def main():
 source,old,all_tasks,audits,links=build();OUT.mkdir(parents=True,exist_ok=True);files={}
 tasks=[t for t in all_tasks if not t.get('diagnostic_only')]
 diagnostics=[t for t in all_tasks if t.get('diagnostic_only')]
 old_train=[t for t in old if t['split']=='train'];old_sem={semantic_id(t):t['id'] for t in old_train}
 lineage=[dict(id=t['id'],role=t['p4_role'],case=t['p4_case'],mode=t['completion_mode'],
   old_semantic_match=old_sem.get(t['semantic_id'])) for t in tasks]
 previous=read(PREVIOUS);removed={t['id'] for t in old_train};candidate=[t for t in previous if t['id'] not in removed]+tasks
 assert len({t['id'] for t in candidate})==len(candidate)
 assert len({semantic_id(t) for t in tasks})==len(tasks)
 other_sem={semantic_id(t) for t in previous if t['id'] not in removed};assert not other_sem&{t['semantic_id'] for t in tasks}
 def write(name,rows):
  data=''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows).encode();(OUT/name).write_bytes(data)
  files[name]=dict(count=len(rows),sha256=hashlib.sha256(data).hexdigest())
 requests=[dict(task_id=t['id'],role=t['p4_role'],request=request(t,'action_tools',t['name_variant'])) for t in tasks]
 for r in requests:assert r['request']['max_tokens']==1024
 write('train_tasks.jsonl',tasks);write('requests.jsonl',requests);write('reserve_tasks.jsonl',old_train)
 write('diagnostic_tasks.jsonl',diagnostics)
 write('heldout_tasks.jsonl',[t for t in old if t['split']!='train']);write('audit.jsonl',audits);write('lineage.jsonl',lineage)
 reused={r['old_semantic_match']:r['id'] for r in lineage if r['old_semantic_match']}
 write('selection.jsonl',[dict(id=t['id'],split=t['split'],
  role='heldout_unchanged' if t['split']!='train' else 'core_semantics_reused' if t['id'] in reused else 'reserve',
  replacement_id=reused.get(t['id'])) for t in old])
 write('acquisition_use_links.jsonl',links);write('bp_candidate_tasks.jsonl',candidate)
 pairs=[]
 for case in ('acquisition','deadline','target_selection','opportunity_cost','ordinary_alternative'):
  pair=[t for t in tasks if t['p4_case']==case]
  assert len(pair)==2 and scoring_neutral(pair[0]['input'])==scoring_neutral(pair[1]['input'])
  pairs.append(dict(case=case,ids=[t['id'] for t in pair],only_scoring_changes=True,
   exact_relations=[t['teacher']['p4_audit']['query_comparison']['exact_relation'] for t in pair],
   accepted_actions_change=pair[0]['teacher']['acceptable_actions']!=pair[1]['teacher']['acceptable_actions']))
 write('scoring_contrasts.jsonl',pairs)
 roots=[t for t in tasks if t['p4_role']=='acquisition_decision']
 manifest=dict(version='p4-information-core-v1',core_tasks=len(tasks),root_decisions=len(roots),result_use=len(tasks)-len(roots),diagnostics=len(diagnostics),
  completion_counts=dict(Counter(t['completion_mode'] for t in tasks)),
  exact_relations=dict(Counter(t['teacher']['p4_audit']['query_comparison']['exact_relation'] for t in roots)),
  rewarded_relations=dict(Counter(t['teacher']['p4_audit']['query_comparison']['rewarded_relation'] for t in roots)),
  original_train=len(old_train),old_semantics_reused=sum(bool(r['old_semantic_match']) for r in lineage),
  old_train_relations=dict(Counter(a['query_comparison']['exact_relation'] for a in audits)),
  candidate_tasks=len(candidate),source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),files=files,
  training_ready=False,model_tested=False,merged=False,B_P123_unchanged=True,heldout_unchanged=True,
  limitations='New result-use branches share their acquisition parent strategy. Single relevant opponent; two unknown goals target contrast. No three-player target-selection claim. Solver failures do not filter outcome self-play.')
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 cards=['# P4 信息获取与利用：题面和审核','']
 for t in all_tasks:
  r=dict(request=request(t,'action_tools',t['name_variant']))
  value=t['teacher']['p4_audit'].get('result_value','')
  cards += [f'## {t["p4_case"]} / {t["completion_mode"]} / {value}',f'ID: {t["id"]}','',
    '仅诊断：全部合法动作得分，不进入训练请求。' if t.get('diagnostic_only') else '核心候选；尚未实测模型。','',
    r['request']['messages'][1]['content'],'','审核答案（不发送给模型）：'+json.dumps(t['teacher']['acceptable_actions'],ensure_ascii=False),
    '审核依据：'+json.dumps(t['teacher']['p4_audit'],ensure_ascii=False),'']
 (OUT/'cards.md').write_text('\n'.join(cards)+'\n')
 print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False))
if __name__=='__main__':main()
