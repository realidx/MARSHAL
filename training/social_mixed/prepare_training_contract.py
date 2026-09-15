"""Conservative, model-result-independent audit under the reviewed plain prompt."""
from collections import Counter,defaultdict
from copy import deepcopy
from itertools import product
from pathlib import Path
import hashlib,json
import numpy as np
from training.b_sft.social_named_probe import request, present
from training.b_sft.decision_policy import VERSION as POLICY
ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'examples/social_mixed/data_plain_v1'
SOURCE=ROOT/'examples/social_bp/p4_information_core_v1/bp_candidate_tasks.jsonl'
VALUES={'want':1,'neutral':0,'avoid':-1}
def read(p):return [json.loads(x) for x in p.read_text().splitlines()]
def stable(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def sha(b):return hashlib.sha256(b).hexdigest()
def worlds(t):
 i=t['input'];g=i['game'];n=g['n_players'];ng=len(g['goals']);fixed={}
 facts=list(i['public_preferences'])+list(i['private_results'])
 facts += [dict(player=i['player'],goal=int(k.split('_')[1]),preference=v) for k,v in i['own_preferences'].items()]
 if t['task']=='P':facts+=i['supplied_belief']['known_preferences']
 for f in facts:
  key=f['player'],f['goal'];v=VALUES[f['preference']]
  if key in fixed:assert fixed[key]==v
  fixed[key]=v
 unknown=[(p,g) for p in range(n) for g in range(ng) if (p,g) not in fixed]
 if len(unknown)>8:raise ValueError('world_enumeration_limit')
 rows=[]
 for vals in product((1,0,-1),repeat=len(unknown)):
  f=dict(fixed);f.update(zip(unknown,vals));w=[[f[p,g] for g in range(ng)] for p in range(n)]
  if not all(1 in row for row in w) or not all(any(w[p][g]!=0 for p in range(n)) for g in range(ng)):continue
  if t['task']=='B' and 'previous_belief' in i:
   q=i['queries'][0]
   if w[q['player']][q['goal']] not in [VALUES[x] for x in i['previous_belief']['possible_preferences']]:continue
  rows.append(w)
 if not rows:raise ValueError('no_consistent_world')
 return rows

def payoff(i,bits,w):
 sats=[]
 for g in i['game']['goals']:
  met=sum(bits[a['player_id']][a['action_id']] for a in g['required_actions']);total=len(g['required_actions'])
  sats.append(float(met==total) if g.get('binary',True) else met/total)
 return np.asarray(w)@np.asarray(sats)
def apply(bits,offer,actor):
 b=deepcopy(bits);b[actor]=offer['proposer_action'][:];b[offer['partner_id']]=offer['partner_action'][:];return b
def best(values,actor,response):
 own=values[:,actor];ids=np.flatnonzero(np.isclose(own,own.max(),atol=1e-9,rtol=0))
 if response:
  others=values.sum(axis=1)-own;ids=ids[np.isclose(others[ids],others[ids].max(),atol=1e-9,rtol=0)]
 return list(map(int,ids))
def p_terminal(t,ws):
 i=t['input'];state=i['current_state'];actor=i['player'];n=i['game']['n_players']
 if len(state['round_robin'])-state['turn_index']!=1:raise ValueError('continuation_policy_not_certified_without_prior')
 if n!=2:raise ValueError('third_player_information_set_not_certified')
 # Responders know their own row. Require the learner row to be public, so
 # helping the other player is evaluated from information they actually have.
 public={(r['player'],r['goal']) for r in i['public_preferences']}
 if not all((actor,g) in public for g in range(len(i['game']['goals']))):raise ValueError('partner_social_payoff_not_public')
 pays=[]
 for a in i['legal_actions']:
  by=[]
  for w in ws:
   before=payoff(i,state['commitments'],w)
   if a.get('response')=='ACCEPT':v=payoff(i,apply(state['commitments'],i['pending_offer'],state['current_proposer']),w)
   elif a.get('action')=='OFFER':
    accepted=payoff(i,apply(state['commitments'],a,actor),w);options=np.array([before,accepted]);opts=best(options,a['partner_id'],True)
    # In two-player games a residual response tie gives identical utilities.
    if any(not np.allclose(options[k],options[opts[0]]) for k in opts):raise ValueError('residual_response_changes_payoff')
    v=options[opts[0]]
   else:v=before # PASS, REJECT, or last-turn investigation.
   by.append(v)
  pays.append(by)
 return np.asarray(pays)
def known_continuation(t,ws):
 # Sufficient interval certificate covering every residual tie choice, including
 # mixtures. Only common-knowledge complete two-player positions are admitted.
 i=t['input'];actor=i['player']
 if len(ws)!=1 or i['game']['n_players']!=2:raise ValueError('continuation_policy_not_certified_without_prior')
 public={(f['player'],f['goal']) for f in i['public_preferences']}
 if not all((actor,g) in public for g in range(len(i['game']['goals']))):raise ValueError('partner_social_payoff_not_public')
 from training.b_sft.social_private_teacher import PrivateInvestigationRules
 from training.b_sft.debug.audit_readable_pretraining import reconstruct
 raw,_=reconstruct(i);rules=PrivateInvestigationRules(raw);world=tuple(map(tuple,ws[0]));node=rules.initial()
 for a in i['imposed_setup']+i['voluntary_history']:
  action=next(x for x in rules.actions(node) if x.to_dict()==a)
  node=rules.step(node,action,realized_world=world)
 if list(map(list,node.state.snapshot_commitments()))!=i['current_state']['commitments']:raise ValueError('continuation_reconstruction_mismatch')
 memo={};count=0
 def bounds(n):
  nonlocal count
  key=stable([n.state.snapshot_commitments(),n.state.turn_index,str(n.pending),n.state.public_state()['investigation_remaining_by_player']])
  if key in memo:return memo[key]
  count+=1
  if count>20000:raise ValueError('continuation_certificate_budget')
  if n.state.is_terminal:
   v=payoff(i,n.state.snapshot_commitments(),world);return v,v
  actions=rules.actions(n);children=[bounds(rules.step(n,a,realized_world=world)) for a in actions]
  lo=np.array([v[0] for v in children]);hi=np.array([v[1] for v in children]);p=rules.actor(n)
  keep=np.flatnonzero(hi[:,p]>=lo[:,p].max()-1e-9)
  # Only use the altruistic secondary preference when all surviving own values
  # are fixed and equal. Otherwise retain the larger set conservatively.
  if n.pending is not None and np.allclose(lo[keep,p],hi[keep,p]) and np.allclose(lo[keep,p],lo[keep[0],p]):
   other=1-p;keep=keep[hi[keep,other]>=lo[keep,other].max()-1e-9]
  result=lo[keep].min(axis=0),hi[keep].max(axis=0);memo[key]=result;return result
 actions=rules.actions(node)
 if [a.to_dict() for a in actions]!=i['legal_actions']:raise ValueError('continuation_legal_actions_mismatch')
 bs=[bounds(rules.step(node,a,realized_world=world)) for a in actions]
 lo=np.array([b[0] for b in bs]);hi=np.array([b[1] for b in bs])
 gold=[j for j,a in enumerate(i['legal_actions']) if a in t['teacher']['acceptable_actions']];bad=[j for j in range(len(actions)) if j not in gold]
 if not bad:raise ValueError('all_legal_diagnostic')
 if len(gold)==1:
  valid=lo[gold[0],actor]>hi[bad,actor].max()+1e-9
 else:
  valid=np.allclose(lo[gold,actor],hi[gold,actor]) and np.allclose(lo[gold,actor],lo[gold[0],actor]) and lo[gold[0],actor]>hi[bad,actor].max()+1e-9
 if not valid:raise ValueError('residual_continuation_ties_not_certified')
 return dict(proof='known_world_all_residual_policies_interval_certificate',nodes=count,prior_required=False)

def audit(t):
 i=t['input'];teacher=t['teacher'];record={}
 if t.get('diagnostic_only') or teacher.get('all_legal_accepted'):raise ValueError('all_legal_diagnostic')
 if t['task']=='B':
  v=present(t,t.get('name_variant',0));new=[e for e in v['history'] if e.get('belief_period')=='new evidence']
  if i.get('previous_belief')==teacher['gold'] and new and all(e['actor']==v['you'] and e.get('response') in ('ACCEPT','REJECT') for e in new):
   return dict(proof='own_response_does_not_observe_new_hidden_information',prior_required=False)
  if not i['voluntary_history'] or 'response' not in i['voluntary_history'][-1]:raise ValueError('behavior_policy_without_random_tie_rule_not_certified')
  ws=worlds(t);q=i['queries'][0];obs=i['voluntary_history'][-1]['response']
  if any(len({w[p][g] for w in ws})>1 for p in range(i['game']['n_players']) for g in range(len(i['game']['goals'])) if (p,g)!=(q['player'],q['goal'])):raise ValueError('multiple_hidden_preferences_not_certified')
  # Certificate scope is a fully known final response; recompute payoffs from
  # the visible offer and commitments rather than trusting stored likelihoods.
  setup=i['imposed_setup']+i['voluntary_history'][:-1];bits=[[0]*k for k in i['game']['n_actions_per_player']];turn=0;pending=None;actor=None
  for a in setup:
   if a.get('action')=='OFFER':pending=a;actor=i['current_state']['round_robin'][turn]
   elif 'response' in a:
    if a['response']=='ACCEPT':bits=apply(bits,pending,actor)
    pending=None;turn+=1
   else:turn+=1
  if pending is None or len(i['current_state']['round_robin'])!=turn+1:raise ValueError('not_final_response_certificate')
  respondent=pending['partner_id'];support=set()
  public={(f['player'],f['goal']) for f in i['public_preferences']}
  if not all((p,g) in public for p in range(i['game']['n_players']) if p!=respondent for g in range(len(i['game']['goals']))):raise ValueError('responder_social_payoff_not_public')
  for w in ws:
   pref=next(k for k,val in VALUES.items() if val==w[q['player']][q['goal']])
   vals=np.array([payoff(i,bits,w),payoff(i,apply(bits,pending,actor),w)])
   if (1 if obs=='ACCEPT' else 0) in best(vals,respondent,True):support.add(pref)
  if support!=set(teacher['gold']['possible_preferences']):raise ValueError('support_changes_without_random_policy')
  if len(support)!=1:raise ValueError('favored_order_requires_unspecified_prior')
  if teacher['gold']['favored']!=next(iter(support)):raise ValueError('singleton_favored_mismatch')
  return dict(proof='independent_final_response_singleton',worlds=len(ws),prior_required=False)
 ws=worlds(t)
 if len(i['current_state']['round_robin'])-i['current_state']['turn_index']!=1:return known_continuation(t,ws)
 pay=p_terminal(t,ws);actor=i['player'];response=bool(i['pending_offer'])
 if 'qualitative' in i:raise ValueError('qualifier_numeric_envelope_not_in_plain_prompt')
 belief=i['supplied_belief'];joint=belief.get('joint_distribution')
 if joint:
  from fractions import Fraction
  weights=np.zeros(len(ws))
  for row in joint:
   candidates=[j for j,w in enumerate(ws) if all(w[f['player']][f['goal']]==VALUES[f['preference']] for f in row['preferences'])]
   if len(candidates)!=1:raise ValueError('joint_row_not_complete')
   weights[candidates[0]]+=float(Fraction(row['probability']))
  if not np.isclose(weights.sum(),1):raise ValueError('joint_mass')
  ids=best(np.einsum('awp,w->ap',pay,weights),actor,response);proof='explicit_joint_terminal_decision'
 else:
  per=[best(pay[:,w],actor,response) for w in range(len(ws))]
  if any(x!=per[0] for x in per):raise ValueError('optimal_action_depends_on_unspecified_prior')
  ids=per[0];proof='same_optimal_set_in_every_consistent_world'
 actions=[i['legal_actions'][j] for j in ids]
 if {stable(a) for a in actions}!={stable(a) for a in teacher['acceptable_actions']}:raise ValueError('plain_objective_exact_actions_differ_from_teacher_tolerance')
 if len(actions)==len(i['legal_actions']):raise ValueError('all_legal_diagnostic')
 return dict(proof=proof,worlds=len(ws),prior_required=bool(joint))

def main():
 OUT.mkdir(exist_ok=True)
 assigns={r['id']:r for r in read(ROOT/'examples/social_bp/response_only_v1/kernels_v1/assignments.jsonl')}
 rows=read(SOURCE);approved=defaultdict(list);audits=[]
 for t in rows:
  if t['split']=='test':continue
  k=t.get('kernel',assigns.get(t['id'],{}).get('kernel'));r=dict(id=t['id'],split=t['split'],kernel=k)
  try:
   if assigns.get(t['id'],{}).get('deferred'):raise ValueError('previously_deferred')
   r.update(audit(t),status='approved')
   x=deepcopy(t);x.update(training_ready=True,objective_version=POLICY,kernel=k,contract_version='plain-v1',contract_proof=r['proof'])
   x['completion_mode']='binary' if all(g['binary'] for g in x['input']['game']['goals']) else 'linear' if not any(g['binary'] for g in x['input']['game']['goals']) else 'mixed'
   approved[t['split']].append(x)
  except ValueError as e:r.update(status='deferred',reason=str(e))
  audits.append(r)
 # Do not train a one-sided P4 curriculum: currently only neutral answer-use
 # branches and a deadline negative are certified, with no certified positive.
 # Preserve their certificates in the audit, but hold the whole P4 unit.
 for split in ('train','validation'):
  held={t['id'] for t in approved[split] if t['kernel']=='P4'}
  approved[split]=[t for t in approved[split] if t['id'] not in held]
  for r in audits:
   if r['id'] in held:r.update(status='deferred',reason='P4_contrast_unit_incomplete',label_individually_certified=True)
 files={}
 def write(name,rows):
  data=''.join(json.dumps(t,ensure_ascii=False)+'\n' for t in rows).encode();(OUT/name).write_bytes(data);files[name]=dict(sha256=sha(data),count=len(rows))
 for split in ('train','validation'):write('bp_'+split+'.jsonl',approved[split])
 write('audit.jsonl',audits)
 write('selfplay_train.jsonl',read(ROOT/'examples/social_mixed/selfplay_audit_v2/train_candidate.jsonl'))
 write('selfplay_validation.jsonl',read(ROOT/'examples/social_mixed/data/selfplay_validation.jsonl'))
 write('requests_train.jsonl',[dict(id=t['id'],request=request(t,'action_tools',t.get('name_variant',0))) for t in approved['train']])
 source_names=['training/b_sft/review_prompt.py','training/b_sft/social_prompt.py','training/b_sft/social_named_probe.py','training/b_sft/decision_policy.py','training/social_mixed/policy_prompt.py','training/social_mixed/frozen/selfplay_prompt.py','training/social_mixed/frozen/bp_display.py','training/social_mixed/contract_sampling.py']
 manifest=dict(version='plain-v1',formal_mixed_training_ready=False,role='diagnostic_audit_only',files=files,source_sha256=sha(SOURCE.read_bytes()),prompt_sources={n:sha((ROOT/n).read_bytes()) for n in source_names},
  counts={s:dict(Counter(t['kernel'] for t in ts)) for s,ts in approved.items()},deferred=dict(Counter(r.get('reason') for r in audits if r['status']=='deferred')),
  selection='No model scores used. Conservative sufficient certificates, not proof that every deferred label is wrong.',test_used=False)
 (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print(json.dumps({k:v for k,v in manifest.items() if k not in ('files','prompt_sources')},indent=2))
if __name__=='__main__':main()
