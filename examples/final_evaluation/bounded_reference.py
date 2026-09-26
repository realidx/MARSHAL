"""Two-proposal receding-horizon best response to a fixed myopic predictor.
No equilibrium iteration; posterior likelihoods come from the same predictor.
"""
import random
import numpy as np
from training.social_mixed.core import seed_for,sp_prompt
from training.social_mixed.frozen.training.b_sft.social_private_teacher import PrivateWindow,observed_slots
from training.social_mixed.frozen.training.b_sft.shared_teacher import Entry,SearchLimit

VERSION='bounded-reference-v1'
SPEC=dict(version=VERSION,depth=2,depth_unit='completed proposal opportunities, including pending response',leaf_value='native current commitment utility, not terminal Q',partner_prediction='one-proposal myopic payoff with predicted immediate acceptance; 0.05 uniform tremble over legal actions',belief_update='Bayes on observed focal actions using the same myopic predictor; own actions are interventions; private answers condition information sets',prediction_information='current filtered prior plus acting player own preferences/private answers; no further public-action inference inside hypothetical window',ties='own utility, then others utility only at response nodes; seeded uniform remaining ties',planning='exact information-set best response within two-proposal tree to fixed predictor; replan at every reference decision')
EPSILON=.05

def payoff(rules,node,worlds):
 return np.einsum('wpg,g->wp',np.asarray(worlds),node.state.goal_satisfaction())

def groups(node,actor,worlds):
 slots=observed_slots(node,actor);out={}
 for wi,w in enumerate(worlds):out.setdefault((w[actor],tuple(w[p][g] for p,g in slots)),[]).append(wi)
 return [np.asarray(ids,dtype=int) for ids in out.values()]

def predict(rules,node,worlds,weights):
 """Information-set policy, with offer outcomes averaged before proposer choice."""
 actor=rules.actor(node);actions=rules.actions(node);values=[]
 for action in actions:
  child=rules._apply(node,action)
  if child.pending is not None:
   replies=rules.actions(child);outcomes=np.stack([payoff(rules,rules._apply(child,a),worlds) for a in replies])
   responder=rules.actor(child);response=mixture(outcomes,responder,groups(child,responder,worlds),weights,True)
   values.append(np.einsum('aw,awp->wp',response,outcomes))
  else:values.append(payoff(rules,child,worlds))
 return mixture(np.stack(values),actor,groups(node,actor,worlds),weights,node.pending is not None)

def mixture(values,actor,partitions,weights,response):
 result=np.full(values.shape[:2],EPSILON/len(values))
 for ids in partitions:
  w=weights[ids];w=w/w.sum();means=np.einsum('awp,w->ap',values[:,ids],w)
  best=np.flatnonzero(means[:,actor]>=means[:,actor].max()-1e-9)
  if response:
   others=means.sum(axis=1)-means[:,actor];best=best[others[best]>=others[best].max()-1e-9]
  result[np.ix_(best,ids)]+=(1-EPSILON)/len(best)
 return result

class Window(PrivateWindow):
 def __init__(self,rules,root,worlds,weights,depth=2,**budgets):
  self.cutoff=min(len(rules.spec.round_robin),root.state.turn_index+depth)
  super().__init__(rules,root,worlds,world_weights=weights,**budgets)
 def _grow(self,node):
  self._check()
  if len(self.entries)>=self.max_nodes:raise SearchLimit('Bounded reference node limit')
  i=len(self.entries);self.entries.append(None)
  if node.state.is_terminal or (node.state.turn_index>=self.cutoff and node.pending is None):
   self.entries[i]=Entry(node,None,(),(),payoff(self.rules,node,self.worlds))
  else:
   actions=self.rules.actions(node);children=tuple(self._grow(self.rules._apply(node,a)) for a in actions)
   self.entries[i]=Entry(node,self.rules.actor(node),actions,children)
  return i
 def best_response(self,actor):
  for i,e in enumerate(self.entries):
   self._check()
   if e.actor is not None and e.actor!=actor:self.policy[i]=predict(self.rules,e.node,self.worlds,self.world_weights)
  updates,_=self.response(actor)
  for i,policy in updates.items():self.policy[i]=policy
  # Verify every action distribution is constant within the acting information set.
  for i,partitions in self.information_groups.items():
   for ids in partitions:
    if not np.allclose(self.policy[i][:,ids],self.policy[i][:,ids[:1]],rtol=0,atol=1e-9):raise ValueError('Information leak')
  return self

class BoundedController:
 def __init__(self,reset,seat,seed,seconds=30,max_nodes=10000):
  from training.social_mixed.weighted_rules import OutcomeRules
  if reset['players']!=2:raise ValueError('Two players required')
  self.rules=OutcomeRules(reset['raw']);self.node=self.rules.initial();self.weights=self.rules.background_world_weights.copy()
  self.seat=seat;self.actor=1-seat;self.seed=seed;self.case=reset['id'];self.seconds=seconds;self.max_nodes=max_nodes;self.decisions=0
 def choose(self,ep):
  actor=ep.rules.actor(ep.node)
  if actor!=self.actor:raise ValueError('Reference called on focal seat')
  if ep.node.state.public_state()!=self.node.state.public_state():raise ValueError('Public state desynchronized')
  # Keep all worlds during search; private answers partition choices, not public state.
  tree=Window(self.rules,self.node,self.rules.worlds,self.weights,seconds=self.seconds,max_nodes=self.max_nodes,max_sweeps=1).best_response(actor)
  facts=ep.node.state.private_results[actor];own=ep.world[actor]
  ids=[wi for wi,w in enumerate(tree.worlds) if w[actor]==own and all(w[p][g]==v for p,g,v in facts)]
  if not ids:raise ValueError('Own information has no support')
  probs=tree.policy[0][:,ids[0]]
  if not np.allclose(tree.policy[0][:,ids],probs[:,None],atol=1e-9,rtol=0):raise ValueError('Hidden-world-dependent choice')
  idx=random.Random(seed_for(self.seed,self.case,self.seat,self.decisions)).choices(range(len(probs)),weights=probs,k=1)[0]
  legal=[a.to_dict() for a in ep.rules.actions(ep.node)]
  if legal!=[a.to_dict() for a in tree.entries[0].actions]:raise ValueError('Action order mismatch')
  name,args=sp_prompt.action_call(sp_prompt.visible(ep.observation())['legal_actions'][idx])
  return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments=__import__('json').dumps(args)))]),finish_reason='tool_calls'),bounded_reference=dict(version=VERSION,depth=2,nodes=len(tree.entries),root_probabilities=probs.tolist(),belief_entropy=float(-sum(p*np.log(p) for p in self.weights if p))))
 def observe(self,action):
  actions=self.rules.actions(self.node);idx=[a.to_dict() for a in actions].index(action)
  if self.rules.actor(self.node)==self.seat:
   likelihood=predict(self.rules,self.node,self.rules.worlds,self.weights)[idx]
   self.weights*=likelihood;self.weights/=self.weights.sum()
  self.node=self.rules._apply(self.node,actions[idx]);self.decisions+=1
