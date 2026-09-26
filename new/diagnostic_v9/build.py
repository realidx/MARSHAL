"""Small native games with explicit proof traces; no model-result selection."""
import json,hashlib,itertools
from copy import deepcopy,copy
from pathlib import Path
from collections import Counter
import numpy as np
from new.diagnostic_v7.initial_state import InitialEpisode
from new.diagnostic_v7.build import qualify
from new.diagnostic_v8.build import materialize,trace,CACHE
from training.b_sft.preference_contract import profile
from training.b_sft.prepare_no_catalogue_probe import expand_support
HERE=Path(__file__).resolve().parent

def main():
 pool=[];errors=[]
 templates=list(itertools.product([(1,-1),(1,0),(1,1)], [1],[(0,0,1,1),(0,0,0,1),(0,0,1,0)]))
 templates += [(own,0,g) for own in [(1,1,1),(1,1,0),(1,1,-1)] for g in [(0,0,0,0,1,1),(0,0,0,0,0,1),(0,0,0,0,1,0)]]
 for n,(own,other,geometry) in enumerate(templates):
  goals=[dict(goal_id=g,binary=True,required_actions=[dict(player_id=0,action_id=geometry[2*g]),dict(player_id=1,action_id=geometry[2*g+1])]) for g in range(len(own))]
  raw=dict(id=f'v9-small-{n}',ego=0,own_preferences=list(own),history=[],background_prior=profile('balanced'),type_catalogues={'0':[list(own)],'1':[[v,other]+([1] if len(own)==3 else []) for v in (1,0,-1)]},game=dict(n_players=2,n_actions_per_player=[2,2],round_robin=[1,0],max_changes=1,menu_enabled=False,goals=goals))
  try:raw,public,_=expand_support(raw)
  except ValueError:continue
  if len(raw['type_catalogues']['1'])!=3:continue
  # One partner choice, then a final focal action; no investigations.
  initial=dict(commitments=[[0,0],[0,0]],turn_index=0,investigation_remaining=[0,0])
  try:ep=InitialEpisode(raw,initial,seconds=5,max_nodes=30000,max_sweeps=128)
  except (ValueError,RuntimeError) as e:errors.append(str(e));continue
  src=dict(raw=raw,initial_state=initial,source_parent=raw['id'],task=dict(input=dict(public_preferences=public,queries=[dict(player=1,goal=0)])))
  CACHE[json.dumps([raw,initial],sort_keys=True)]=ep
  for ai,a in enumerate(ep.tree.entries[0].actions):
   if float(ep.weights@ep.tree.policy[0][ai])<=0:continue
   child=copy(ep);child.weights=ep.weights.copy();event=a.to_dict();child.observe(event)
   positions=[(child,[event])]
   node=child.tree.entries[child.index]
   if node.actor==0 and node.node.pending is not None:
    for aj,reply in enumerate(node.actions):
     if float(child.weights@child.tree.policy[child.index][aj])<=0:continue
     after=copy(child);after.weights=child.weights.copy();after.observe(reply.to_dict())
     positions.append((after,[event,reply.to_dict()]))
   for current,events in positions:
    try:
     c=materialize(src,current,events,[])
     if not c:continue
     ev=trace(c)
     if not ev[0]['informative']:continue
     c=qualify(c);c['evidence_trace']=ev;c['difficulty_layer']='single_elimination' if len(c['gold_judgment']['possible_preferences'])<3 else 'single_ambiguous';c['stratum']=c['difficulty_layer'];pool.append(c)
    except (ValueError,RuntimeError,AssertionError) as e:errors.append(str(e))
  # Actual self investigation as an intervention: it is not partner evidence.
  raw=deepcopy(raw);raw['game']['round_robin']=[1,0,0,1]
  initial=dict(commitments=[[0,0],[0,0]],turn_index=1,investigation_remaining=[1,0])
  try:ep=InitialEpisode(raw,initial,seconds=5,max_nodes=30000,max_sweeps=128)
  except (ValueError,RuntimeError) as e:errors.append(str(e));continue
  src=dict(src,raw=raw,initial_state=initial,source_parent=raw['id']+'-query')
  for ai,a in enumerate(ep.tree.entries[0].actions):
   event=a.to_dict()
   if event!={'action':'INVESTIGATE','player':1,'goal':0}:continue
   child=copy(ep);child.weights=ep.weights.copy();child.index=ep.tree.entries[0].children[ai]
   for v in (1,0,-1):
    try:
     c=materialize(src,child,[event],[(1,0,v)]);c=qualify(c)
     c['difficulty_layer']='direct_feedback';c['stratum']='direct_feedback';c['evidence_trace']=[dict(actor=0,event=event,intervention=True,private_answer=v)]
     c['derivation']='Native legal self-query executed as an intervention; no likelihood inference from the observers own query.'
     pool.append(c)
    except (ValueError,RuntimeError,AssertionError) as e:errors.append(str(e))
 (HERE/'pool.json').write_text(json.dumps(pool,indent=2)+'\n');(HERE/'audit.json').write_text(json.dumps(dict(counts=Counter((c['difficulty_layer']+' / '+c['intervention_qualification']['role']) for c in pool),errors=Counter(errors)),indent=2)+'\n')
 print((HERE/'audit.json').read_text())
if __name__=='__main__':main()
