"""Compact P1-P3 and add audited scoring/belief contrasts. CPU construction only."""
from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib,json
import numpy as np
from training.b_sft.build_b3_external import ROOT,fixture as response_base,local_policy_audit
from training.b_sft.prepare_no_catalogue_probe import expand_support,view
from training.b_sft.social_private_teacher import PrivateEpisode,audit_native
from training.b_sft.debug.audit_readable_pretraining import reconstruct,independent_final_actions,VALUES
from training.b_sft.social_bp_curriculum import acceptable,digest
from training.b_sft.social_p_qualitative import robust_actions,WIDE_ENVELOPES,WORDS
from training.b_sft.build_bp_pilot import topology,split_for
from training.b_sft.bp_semantics import semantic_id
from training.b_sft.social_named_probe import request
from training.b_sft.social_bp_training import native_completion,reward
from training.b_sft.decision_policy import VERSION
OUT=ROOT/'examples/social_bp/p123_core_linear_v1'
SOURCE=ROOT/'examples/social_bp/response_only_v1/tasks.jsonl'
PREVIOUS=ROOT/'examples/social_bp/b12_linear_contrasts_v1/bp_candidate_tasks.jsonl'
NAMES={v:k for k,v in VALUES.items()}
RETAIN={
 '3299f57c17dcc4fb9a43':('P1','net_loss_alternative'),
 '2374975af1661a83f77a':('P1','proposal_residual_ties'),
 '0566a4242632991ce905':('P1','private_result_use'),
 '0f940ebe225b6ce0690f':('P1','third_player_commitment'),
 '6b465e62d66bf6896f49':('P2','two_unknown_slots'),
 'acec6ac799d1e691767e':('P2','private_result_other_unknown')}

def read(p):return [json.loads(s) for s in p.read_text().splitlines()]
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def scoring_neutral(x):
 if isinstance(x,dict):return {k:True if k=='binary' else scoring_neutral(v) for k,v in x.items()}
 if isinstance(x,list):return [scoring_neutral(v) for v in x]
 return x

def contrast_checks(tasks):
 index={(t['kernel'],t['p123_case'],t['completion_mode']):t for t in tasks};result=[]
 def record(kind,a,b):
  result.append(dict(kind=kind,left=a['id'],right=b['id'],
    left_scoring=a['completion_mode'],right_scoring=b['completion_mode'],
    left_status='ambiguous_information' if a.get('diagnostic_only') else 'labelled',
    right_status='ambiguous_information' if b.get('diagnostic_only') else 'labelled',
    acceptable_actions_change=a['teacher']['acceptable_actions']!=b['teacher']['acceptable_actions']))
 for t in tasks:
  if t['completion_mode']=='binary' and t['p123_case']!='weight_tie':
   other=index[t['kernel'],t['p123_case'],'linear']
   assert scoring_neutral(t['input'])==scoring_neutral(other['input'])
   record('scoring_only',t,other)
 for mode in ('binary','linear'):
  for cases in [('weight_low','weight_high'),('weight_low','weight_middle'),('joint_positive','joint_negative')]:
   a,b=[index['P2',case,mode] for case in cases];inputs=[deepcopy(t['input']) for t in (a,b)]
   for inp in inputs:
    for r in inp['supplied_belief']['joint_distribution']:r.pop('probability')
   assert inputs[0]==inputs[1]
   record('joint_correlation_only' if cases[0].startswith('joint') else 'belief_weights_only',a,b)
  for cases in [('very_likely_avoid','almost_certain_want'),('likely_avoid','very_likely_avoid')]:
   a,b=[index['P3',case,mode] for case in cases];inputs=[deepcopy(t['input']) for t in (a,b)]
   for inp in inputs:inp['qualitative'].pop('assessments')
   assert inputs[0]==inputs[1];record('qualitative_assessment_only',a,b)
 return result
def mode(raw,scoring):
 for g in raw['game']['goals']:g['binary']=scoring=='binary' or (scoring=='mixed' and g['goal_id']==0)
 return raw

def proposal_fixture(scoring,joint=False,known=None):
 types=[known] if known else [[v,u,0,1] for v in (1,0,-1) for u in ((1,0,-1) if joint else (0,))]
 raw=dict(id='p123-risk-safe',ego=0,own_preferences=[1]*4,history=[],type_catalogues={'0':[[1]*4],'1':types},
  game=dict(n_players=2,n_actions_per_player=[2,2],max_changes=1,menu_enabled=False,round_robin=[1,0],
   goals=[dict(goal_id=g,binary=True,required_actions=[dict(player_id=p,action_id=int(g==3)) for p in (0,1)]) for g in range(4)]))
 return expand_support(mode(raw,scoring))[:2]

def supplied_weights(worlds,kind,value):
 if kind=='single':return np.array([value if w[1][0]==-1 else (1-value)/2 for w in worlds])
 # Same marginal (.2,.05,.75); change correlation, keeping all 9 worlds positive.
 diag={(1,1):.2,(0,0):.05,(-1,-1):.75}
 anti={(1,-1):.2,(0,0):.05,(-1,1):.2,(-1,-1):.55}
 d=diag if value=='positive' else anti
 return np.array([.9*d.get(tuple(w[1][:2]),0)+.1/9 for w in worlds])

def audited_episode(raw,setup,require_terminal=True):
 e=PrivateEpisode(raw,setup,seconds=30,max_nodes=60000)
 native=audit_native(e.tree);policies=local_policy_audit(e.tree)
 pay=independent_final_actions(e)
 independent=pay is not None
 if pay is None:
  if require_terminal:raise ValueError('No belief-independent terminal partner certificate')
  pay=np.array([e.tree.values[c] for c in e.tree.entries[e.index].children])
 else:np.testing.assert_allclose(pay,[e.tree.values[c] for c in e.tree.entries[e.index].children],atol=1e-9,rtol=0)
 return e,pay,dict(native=native,information_set_checks=policies,independent_terminal_payoffs=independent)

def construct(raw,public,setup,kernel,case,scoring,weights=None,claims=None):
 e,pay,audit=audited_episode(raw,setup);own=raw['own_preferences'];entry=e.tree.entries[e.index]
 actions=[a.to_dict() for a in entry.actions];prior=e._weights(0,own,[])
 weights=prior if weights is None else np.asarray(weights,float)
 assert len(weights)==len(e.tree.worlds) and np.all(weights>=0) and abs(weights.sum()-1)<1e-9
 values=np.einsum('awp,w->ap',pay,weights)
 inp=view(e,public,0,own,[],setup,[]);known=[];unknown=[]
 for p in range(raw['game']['n_players']):
  for g in range(len(own)):
   vs={w[p][g] for w in e.tree.worlds}
   if len(vs)==1:known.append(dict(player=p,goal=g,preference=NAMES[next(iter(vs))]))
   else:unknown.append(dict(player=p,goal=g))
 inp.update(task='complete' if kernel=='P1' else 'uncertain',legal_actions=actions,
  supplied_belief=dict(known_preferences=known,unresolved_preferences=unknown,
   support='These known facts completely specify YOUR current belief.' if not unknown else
     'Your CURRENT belief is the stated preference-generation distribution conditioned on these known preferences.'))
 cert=None
 if kernel=='P2':
  inp['supplied_belief'].update(support='This is YOUR supplied exact joint distribution. It replaces the generator prior for this decision.',
   joint_distribution=[dict(probability=str(Fraction(float(p)).limit_denominator(1000000)),
     preferences=[dict(**q,preference=NAMES[w[q['player']][q['goal']]]) for q in unknown]) for w,p in zip(e.tree.worlds,weights)])
 if claims is not None:
  cert=robust_actions(pay,0,e.tree.worlds,claims,own_tolerance=.1,social_tolerance=.1,
                      envelopes=WIDE_ENVELOPES,offer_response=entry.node.pending is not None)
  indices=cert['acceptable']
  inp['qualitative']=dict(description='This is YOUR supplied current assessment. It replaces the generator prior for this decision.',
    assessments=[dict(player=v['player'],goal=v['goal'],preference=NAMES[v['value']],qualifier=WORDS[c['level']][0]) for c in claims for v in c['event']])
 else:indices=acceptable(values,0,actions=actions)
 teacher=dict(acceptable_actions=[actions[i] for i in indices],own_tolerance=.1,social_tolerance=.1,
  policy_sha256=e.tree.certificate['policy_sha256'],p123_audit=dict(**audit,worlds=e.tree.worlds,per_world_payoffs=pay.tolist(),
  supplied_weights=weights.tolist() if claims is None else None,
  value_scope='Terminal partner responses independently checked within each information set; supplied learner belief changes root evaluation, not partner private knowledge.'),
  all_legal_accepted=len(indices)==len(actions))
 if claims is None:teacher['action_values']=values.tolist()
 else:teacher.update(qualitative_certificate=cert,audit_envelopes=WIDE_ENVELOPES,claims=claims,
                     per_world_payoffs=pay.tolist(),worlds=e.tree.worlds)
 family=topology(raw)
 t=dict(task='P',skill=inp['task'],pool=inp['task'],stage=0 if kernel=='P1' else 1,input=inp,teacher=teacher,
  family=family,split='train',source='p123-core-v1:'+case,training_ready=False,objective_version=VERSION,
  mechanism='p123-core-linear-v1',output_arm='action_tools',name_variant=int(family[-1],16)%2,
  short_teaching=True,kernel=kernel,p123_case=case,completion_mode=scoring,
  contrast_group='p123:'+case,answer_signature=stable(teacher['acceptable_actions']))
 t['id']=digest((t['mechanism'],kernel,inp));t['native_task_id']=t['id'];t['semantic_id']=semantic_id(t)
 if claims is not None:t['qualitative_level']=claims[0]['level']
 return t

def old_audit(t,cache):
 inp=t['input'];raw,own=reconstruct(inp);key=stable([raw,inp['imposed_setup']])
 if key not in cache:cache[key]=audited_episode(raw,inp['imposed_setup'],require_terminal=False)
 e,pay,audit=cache[key];assert not inp['voluntary_history']
 facts=[(f['player'],f['goal'],VALUES[f['preference']]) for f in inp['private_results']]
 choices=e.choices(own,facts);assert choices['actions']==inp['legal_actions']
 if 'qualitative_certificate' in t['teacher']:
  cert=robust_actions(pay,inp['player'],e.tree.worlds,t['teacher']['claims'],own_tolerance=.1,social_tolerance=.1,
   envelopes=t['teacher']['audit_envelopes'],offer_response=e.tree.entries[0].node.pending is not None)
  indices=cert['acceptable'];status=cert['status']
  np.testing.assert_allclose(pay,t['teacher']['per_world_payoffs'],atol=1e-9,rtol=0)
 else:
  np.testing.assert_allclose(choices['values'],t['teacher']['action_values'],atol=1e-9,rtol=0)
  indices=acceptable(choices['values'],inp['player'],actions=choices['actions']);status='certified'
 assert [choices['actions'][i] for i in indices]==t['teacher']['acceptable_actions'],t['id']
 return dict(id=t['id'],**audit,status=status,accepted=len(indices),legal=len(choices['actions']))

def build():
 bank=read(SOURCE);assign={r['id']:r for r in read(SOURCE.parent/'kernels_v1/assignments.jsonl')}
 target=[t for t in bank if assign[t['id']]['kernel'] in ('P1','P2','P3')]
 cache={};audits=[old_audit(t,cache) for t in target if t['split']=='train' and not assign[t['id']]['deferred']]
 held_families={t['family'] for t in bank if t['split']!='train'};train_families={t['family'] for t in bank if t['split']=='train'}
 tasks=[];diagnostics=[]
 def add(t):
  assert t['family'] not in held_families
  assert t['family'] in train_families or split_for(t['family'])=='train'
  if not t['teacher']['acceptable_actions'] or t['teacher']['all_legal_accepted']:
   t['diagnostic_only']=True;diagnostics.append(t)
  else:
   assert reward(t,native_completion(t))['reward']==1;tasks.append(t)
 # Direct response execution: own gain/loss, response-only helpful/harmful ties, net compensation.
 for case,ownq,otherq,pa in [('own_gain',1,-1,[1,0]),('own_loss',-1,1,[1,0]),
       ('helpful_tie',0,1,[1,0]),('harmful_tie',0,-1,[1,0]),('net_compensation',-1,1,[0,1])]:
  for scoring in ('binary','linear'):
   raw,_=response_base(2,True);raw['own_preferences']=[ownq,1]
   raw['type_catalogues']={'0':[[ownq,1]],'1':[[otherq,1]]};raw['game']['round_robin']=[0,1]
   raw,public,_=expand_support(mode(raw,scoring));setup=[dict(action='PASS'),dict(action='OFFER',partner_id=0,proposer_action=pa,partner_action=[1])]
   add(construct(raw,public,setup,'P1','response_'+case,scoring))
 # Known types; offers with equal own payoffs must not be filtered by others' payoffs.
 for name,known in [('want',[1,0,0,1]),('avoid',[-1,0,0,1])]:
  for scoring in ('binary','linear','mixed'):
   raw,public=proposal_fixture(scoring,known=known)
   add(construct(raw,public,[dict(action='PASS')],'P1','proposal_known_'+name,scoring))
 # Exact belief: same game/support; thresholds and residual ties.
 for scoring in ('binary','linear'):
  for name,prob in [('low',.1),('middle',.5),('high',.9),('tie',2/3 if scoring=='binary' else 1/3)]:
   raw,public=proposal_fixture(scoring);e=PrivateEpisode(raw,[dict(action='PASS')])
   add(construct(raw,public,[dict(action='PASS')],'P2','weight_'+name,scoring,supplied_weights(e.tree.worlds,'single',prob)))
 raw,public=proposal_fixture('mixed');e=PrivateEpisode(raw,[dict(action='PASS')])
 add(construct(raw,public,[dict(action='PASS')],'P2','weight_middle','mixed',supplied_weights(e.tree.worlds,'single',.5)))
 for scoring in ('binary','linear'):
  for correlation in ('positive','negative'):
   raw,public=proposal_fixture(scoring,joint=True);e=PrivateEpisode(raw,[dict(action='PASS')])
   add(construct(raw,public,[dict(action='PASS')],'P2','joint_'+correlation,scoring,supplied_weights(e.tree.worlds,'joint',correlation)))
 # Certify full qualitative envelopes, including deliberately ambiguous diagnostics.
 for scoring in ('binary','linear','mixed'):
  levels=[('likely',-1),('very_likely',-1),('almost_certain',1),('unlikely',-1),('possible',-1)] if scoring!='mixed' else [('very_likely',-1)]
  for level,value in levels:
   raw,public=proposal_fixture(scoring)
   add(construct(raw,public,[dict(action='PASS')],'P3',level+'_'+NAMES[value],scoring,
      claims=[dict(event=[dict(player=1,goal=0,value=value)],level=level)]))
 # Reserve whole old training bank except explicitly reviewed representatives.
 old_core=[t for t in target if t['id'] in RETAIN];assert len(old_core)==len(RETAIN)
 return bank,assign,target,old_core,tasks,diagnostics,audits

def main():
 bank,assign,target,old_core,new,diagnostics,audits=build();OUT.mkdir(parents=True,exist_ok=True);files={}
 core=old_core+new;ids={t['id'] for t in old_core}
 deferred=[t for t in target if t['split']=='train' and assign[t['id']]['deferred']]
 reserve=[t for t in target if t['split']=='train' and t['id'] not in ids and not assign[t['id']]['deferred']]
 previous=read(PREVIOUS)
 candidate=[t for t in previous if t['id'] not in assign or assign[t['id']]['kernel'] not in ('P1','P2','P3') or t['split']!='train' or t['id'] in ids or assign[t['id']]['deferred']]+new
 assert len({t['id'] for t in candidate})==len(candidate)
 semantic=[semantic_id(t) for t in core];assert len(set(semantic))==len(semantic),'Duplicate core semantics'
 def write(name,rows):
  payload=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows).encode();(OUT/name).write_bytes(payload)
  files[name]=dict(count=len(rows),sha256=hashlib.sha256(payload).hexdigest())
 requests=[dict(task_id=t['id'],kernel=RETAIN[t['id']][0] if t['id'] in RETAIN else t['kernel'],request=request(t,'action_tools',t['name_variant'])) for t in core]
 for r in requests:assert r['request']['max_tokens']==1024
 write('train_tasks.jsonl',core);write('new_tasks.jsonl',new);write('reserve_tasks.jsonl',reserve)
 write('deferred_train_tasks.jsonl',deferred);write('heldout_tasks.jsonl',[t for t in target if t['split']!='train'])
 write('diagnostic_tasks.jsonl',diagnostics);write('audit.jsonl',audits);write('requests.jsonl',requests);write('bp_candidate_tasks.jsonl',candidate)
 write('contrast_checks.jsonl',contrast_checks(new+diagnostics))
 groups={
  'P1':dict(chain='Action -> terminal commitments -> total own payoff -> response-only social tie rule',
   core=['own_gain_vs_loss','helpful_vs_harmful_response_tie','net_compensation','known_type_proposal_alternatives'],
   retained_extensions=['net_loss_alternative','proposal_residual_ties','private_result_use','third_player_commitment']),
  'P2':dict(chain='Supplied joint probabilities -> conditional partner response -> expected own payoff',
   core=['same_support_weight_change','own_value_ties_without_proposal_altruism','same_marginals_different_joint_correlation'],
   retained_extensions=['two_unknown_slots','private_result_other_unknown']),
  'P3':dict(chain='Qualitative assessment envelope -> worst-case action regret over full feasible distributions',
   core=['confidence_changes_action','confidence_change_leaves_action_stable','no_stable_action_is_diagnostic_only'],
   retained_extensions=[])}
 (OUT/'kernel_contracts.json').write_text(json.dumps(dict(kernels=groups,
   sampling='Assign kernel and contrast-group quotas before surface variants; no implicit row-count weighting.',
   limitations='New proposal contrasts share one four-goal physical scenario; not independent games or a validated difficulty curriculum.'),ensure_ascii=False,indent=2)+'\n')
 selection=[dict(id=t['id'],kernel=assign[t['id']]['kernel'],split=t['split'],role='heldout_unchanged' if t['split']!='train' else 'deferred_unchanged' if assign[t['id']]['deferred'] else 'core' if t['id'] in ids else 'reserve',
  reason=RETAIN[t['id']][1] if t['id'] in RETAIN else 'Preserve heldout/deferred; replace repetitive training variants with controlled core') for t in target]
 write('selection.jsonl',selection)
 counts={k:dict(original_train=sum(t['split']=='train' and assign[t['id']]['kernel']==k for t in target),
  retained=sum(RETAIN[t['id']][0]==k for t in old_core),new=sum(t['kernel']==k for t in new),
  reserve=sum(assign[t['id']]['kernel']==k for t in reserve),deferred=sum(assign[t['id']]['kernel']==k for t in deferred)) for k in ('P1','P2','P3')}
 manifest=dict(version='p123-core-linear-v1',counts=counts,core_tasks=len(core),new_tasks=len(new),
  new_scoring=dict(Counter(t['completion_mode'] for t in new)),diagnostics=len(diagnostics),audited_old_train=len(audits),
  candidate_tasks=len(candidate),candidate_B_train=sum(t['task']=='B' and t['split']=='train' for t in candidate),
  source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),files=files,training_ready=False,model_tested=False,merged=False,
  heldout_unchanged=True,P4_unchanged=True,deferred_unchanged=True)
 (OUT/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 cards=['# P1–P3 核心题面与标签','']
 for t,r in zip(core,requests):
  role=RETAIN[t['id']][1] if t['id'] in RETAIN else t['p123_case']+' / '+t['completion_mode']
  cards += [f'## {r["kernel"]} / {role}',f'ID: {t["id"]}','',r['request']['messages'][1]['content'],'',
    '审核答案（不发送给模型）：'+json.dumps(t['teacher']['acceptable_actions'],ensure_ascii=False),'']
 (OUT/'cards.md').write_text('\n'.join(cards)+'\n')
 print(json.dumps({k:v for k,v in manifest.items() if k!='files'},ensure_ascii=False))
if __name__=='__main__':main()
