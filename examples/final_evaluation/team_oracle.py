"""Offline same-information reference-policy compilation; never clairvoyant.

The complete public tree is compiled before any LLM calls. A nonconvergent or
oversized instance fails preflight, without substituting a heuristic opponent.
"""
import argparse,json,random
from pathlib import Path
import numpy as np
from training.social_mixed.weighted_rules import OutcomeRules
from training.social_mixed.frozen.training.b_sft.social_private_teacher import PrivateWindow,observed_slots
from examples.final_evaluation.team_benac import load,digest
from training.social_mixed.core import seed_for,sp_prompt

def key(own,answers):return json.dumps([list(own),list(answers)],separators=(',',':'))
def compile_policy(reset,seconds=30,max_nodes=10000):
 if reset['players']!=2:raise ValueError('Only two-player reference evaluation supported')
 rules=OutcomeRules(reset['raw'])
 tree=PrivateWindow(rules,rules.initial(),rules.worlds,world_weights=rules.background_world_weights,seconds=seconds,max_nodes=max_nodes,max_sweeps=128).solve()
 identity,checks=tree.reference_identity();nodes=[]
 for i,e in enumerate(tree.entries):
  if e.actor is None:nodes.append(None);continue
  slots=observed_slots(e.node,e.actor);policies={}
  for ids in tree.information_groups[i]:
   w=tree.worlds[int(ids[0])]
   probs=tree.policy[i][:,ids]
   if not np.allclose(probs,probs[:,:1],atol=1e-9,rtol=0):raise ValueError('Private-information leak')
   policies[key(w[e.actor],[w[p][g] for p,g in slots])]=probs[:,0].tolist()
  nodes.append(dict(actor=e.actor,actions=[a.to_dict() for a in e.actions],children=list(e.children),slots=list(slots),policies=policies))
 return dict(case_id=reset['id'],reset_sha256=__import__('hashlib').sha256(json.dumps(reset,sort_keys=True).encode()).hexdigest(),policy_sha256=identity,information_checks=checks,certificate=tree.certificate,nodes=nodes,off_path='Initial prior conditioned on own preferences and private answers; fixed policy at all public histories')

class Controller:
 def __init__(self,policy,seat,seed):self.policy=policy;self.seat=seat;self.index=0;self.seed=seed
 def choose(self,ep):
  e=self.policy['nodes'][self.index];actor=ep.rules.actor(ep.node)
  if actor!=e['actor']:raise ValueError('Reference actor mismatch')
  # Only the oracle seat's own type and received answers index its policy.
  facts={(p,g):v for p,g,v in ep.node.state.private_results[actor]}
  k=key(ep.world[actor],[facts[tuple(slot)] for slot in e['slots']]);probs=e['policies'][k]
  rng=random.Random(seed_for(self.seed,ep.reset['id'],self.seat,self.index))
  idx=rng.choices(range(len(probs)),weights=probs,k=1)[0]
  native=[a.to_dict() for a in ep.rules.actions(ep.node)]
  if native!=e['actions']:raise ValueError('Reference legal-action mismatch')
  shown=sp_prompt.visible(ep.observation())['legal_actions'][idx];name,args=sp_prompt.action_call(shown)
  return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='tool_calls'),oracle_policy=self.policy['policy_sha256'])
 def observe(self,action):
  e=self.policy['nodes'][self.index];idx=e['actions'].index(action);self.index=e['children'][idx]

def main():
 p=argparse.ArgumentParser();p.add_argument('--suite',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--seconds',type=float,default=30);p.add_argument('--max-nodes',type=int,default=10000);a=p.parse_args()
 _,resets=load(a.suite);a.output.mkdir(parents=True,exist_ok=False);report=[]
 for r in resets:
  try:
   policy=compile_policy(r,a.seconds,a.max_nodes);name=r['id']+'.json';(a.output/name).write_text(json.dumps(policy));report.append(dict(case_id=r['id'],status='ready',file=name,sha256=digest(a.output/name)))
  except Exception as exc:report.append(dict(case_id=r['id'],status='blocked',error=repr(exc)))
  (a.output/'preflight.json').write_text(json.dumps(dict(suite_manifest_sha256=digest(a.suite/'manifest.json'),cases=report,complete=len(report)==len(resets),ready=len(report)==len(resets) and all(x['status']=='ready' for x in report)),indent=2))
 print(json.dumps(report,indent=2))
 if any(x['status']!='ready' for x in report):raise SystemExit(1)
if __name__=='__main__':main()
