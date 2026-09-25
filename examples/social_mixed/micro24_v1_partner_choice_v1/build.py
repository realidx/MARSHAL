"""Small exact-terminal three-player additions; no LLM-generated labels."""
import json,hashlib
from copy import deepcopy
from pathlib import Path
import numpy as np
from training.b_sft.shared_teacher import native
from training.b_sft.decision_policy import optimal_indices
from training.b_sft.social_named_probe import present,action_call
from training.b_sft.social_bp_training import reward
from training.social_mixed.prompt_clarification import request as o_request
from training.social_mixed.history_free_requests import request as p_request
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).parent
names={1:'want',0:'neutral',-1:'avoid'}
base=next(json.loads(l) for l in (ROOT/'examples/social_mixed/paired_bank_v2/tasks.jsonl').read_text().splitlines() if json.loads(l)['id']=='e5f61bb093b9a74ba1af-O')['canonical_action_task']
records=[];audit=[]
for topology in ('shared_self','distinct_self'):
 for preferred in (1,2):
  g=deepcopy(base['input']['game']);g['round_robin']=[1,2,0];g['n_actions_per_player']=[1 if topology=='shared_self' else 2,1,1]
  g['goals']=[dict(goal_id=i,binary=True,required_actions=[dict(player_id=0,action_id=0 if topology=='shared_self' else i),dict(player_id=i+1,action_id=0)]) for i in range(2)]
  # Both peers want at least one goal, but only the selected peer accepts
  # the goal that its own commitment can complete.
  peer=[1,-1] if preferred==1 else [-1,1];prefs=[[1,1],peer[:],peer[:]]
  raw=dict(game=g,ego=0,own_preferences=prefs[0],type_catalogues={str(p):[v] for p,v in enumerate(prefs)})
  rules,worlds,_=native(raw);node=rules.initial()
  for _ in range(2):node=rules._apply(node,next(a for a in rules.actions(node) if a.to_dict()=={'action':'PASS'}))
  def terminal(n):
   if n.state.is_terminal:return np.array([np.dot(v,n.state.goal_satisfaction()) for v in prefs],dtype=float)
   acts=rules.actions(n);values=np.array([terminal(rules._apply(n,a)) for a in acts]);idx=optimal_indices(values,rules.actor(n),acts)
   return values[idx].mean(axis=0)
  acts=rules.actions(node);values=np.array([terminal(rules._apply(node,a)) for a in acts]);gold=[acts[i].to_dict() for i in optimal_indices(values,0,acts)]
  assert {a.get('partner_id') for a in gold}=={preferred}
  assert {a.to_dict().get('partner_id') for a in acts if a.to_dict().get('action')=='OFFER'}=={1,2}
  # Each partner is productive under ACCEPT; rejection, not an irrelevant
  # third player, makes one partner unsuitable in each condition.
  for p in (1,2):
   productive=[]
   for offer in acts:
    if offer.to_dict().get('partner_id')!=p:continue
    pending=rules._apply(node,offer)
    accept=next(a for a in rules.actions(pending) if a.to_dict()=={'response':'ACCEPT'})
    productive.append(terminal(rules._apply(pending,accept))[0])
   assert max(productive)>0
  t=deepcopy(base);inp=t['input'];inp.update(game=g,player=0,observer=0,own_preferences={f"goal_{i}":names[v] for i,v in enumerate(prefs[0])},private_results=[],pending_offer=None,imposed_setup=[{'action':'PASS'},{'action':'PASS'}],voluntary_history=[],legal_actions=[a.to_dict() for a in acts],belief_source='history')
  known=[dict(player=p,goal=i,preference=names[v]) for p,row in enumerate(prefs) for i,v in enumerate(row)]
  inp['public_preferences']=known
  inp['supplied_belief']=dict(known_preferences=[],unresolved_preferences=[],support='Use the visible public preferences.')
  inp['current_state']=dict(n_players=3,n_actions_per_player=g['n_actions_per_player'],max_changes=1,forbidden_actions=None,goals=g['goals'],commitments=[[0]*n for n in g['n_actions_per_player']],round_robin=g['round_robin'],turn_index=2,current_proposer=0,transcript=[e.to_dict() for e in node.state.transcript],investigation_remaining_by_player=[1,1,1],investigation_budget_scope='one use per player per game')
  inp['goal_descriptions']=[dict(goal=f'goal_{i}',requires=[f'player_{x["player_id"]}.action_{x["action_id"]}' for x in goal['required_actions']]) for i,goal in enumerate(g['goals'])]
  case=f'partner-choice-{topology}-peer{preferred}'
  # Remove inherited source identity/labels: these are new synthetic native cases.
  t={k:t[k] for k in ['task','skill','input','name_variant','prompt_clarification'] if k in t}
  t.update(id=case,task='P',skill='complete',split='train',source='native-terminal-partner-choice-v1',origin_id=case,family='partner-choice-'+topology,objective_version='response-only-altruism-v1',training_ready=True)
  t['teacher']=dict(acceptable_actions=gold,action_values=values.tolist(),worlds=[prefs],posterior=[1.],all_legal_accepted=False)
  for view in ('O','P'):
   task=deepcopy(t);task['id']=case+'-'+view
   if view=='O':req=o_request(task,'action_tools',task.get('name_variant',0))
   else:
    task['input']['supplied_belief']=dict(known_preferences=[],unresolved_preferences=[],support="Correct qualitative beliefs",semantic_beliefs=[dict(player=p,goal=i,possible_preferences=[names[v]],favored=names[v]) for p,row in enumerate(prefs) for i,v in enumerate(row)])
    req=p_request(task,task.get('name_variant',0))
    text=req['messages'][1]['content'];assert 'EVENTS IN ORDER' not in text and 'joint distribution' not in text
   checks=[];v=present(t,t.get('name_variant',0))
   for native_a,shown in zip(t['input']['legal_actions'],v['legal_actions']):
    name,args=action_call(shown);c=dict(raw_message=dict(content='Native audit; not a model sample.',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='stop')
    s=reward(task,c);assert s['correct']==(native_a in gold)
    checks.append(dict(action=native_a,correct=s['correct']))
   records.append(dict(id=task['id'],task=task,request=req,kind=view,scorer='training.b_sft.social_bp_training.reward',evidence=dict(kind=view,source_cohort='new_native',historical_model_calls=0),status='cpu_certified_not_model_probed'))
   audit.append(dict(id=task['id'],preferred_partner=preferred,topology=topology,all_action_checks=checks))
for top in ('shared_self','distinct_self'):
 a,b=[r for r in records if r['kind']=='O' and top in r['id']]
 assert not {json.dumps(x,sort_keys=True) for x in a['task']['teacher']['acceptable_actions']} & {json.dumps(x,sort_keys=True) for x in b['task']['teacher']['acceptable_actions']}
for name,rows in [('tasks.jsonl',records),('audit.jsonl',audit)]:
 (OUT/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
(OUT/'manifest.json').write_text(json.dumps(dict(tasks=8,physical_structures=2,preference_conditions_per_structure=2,views=['O','P'],teacher='native final-turn enumeration; exact responder terminal utility and response-only tie break',model_probe_completed=False,sha256={n:hashlib.sha256((OUT/n).read_bytes()).hexdigest() for n in ['tasks.jsonl','audit.jsonl']}),indent=2)+'\n')
print('8 views; all native legal actions rescored; partner-flip checks passed')
