"""Evidence-layered diagnostic, selected without model outputs."""
import json,hashlib
from pathlib import Path
from copy import deepcopy,copy
from collections import Counter
import numpy as np
from new.diagnostic_v7.initial_state import InitialEpisode,request
from new.diagnostic_v7.build import qualify
from training.b_sft.prepare_no_catalogue_probe import view
from training.b_sft.preference_contract import belief
from training.b_sft.social_bp_curriculum import acceptable
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
CACHE={}
def trace(c):
 sig=json.dumps([c['raw'],c['initial_state']],sort_keys=True)
 if sig not in CACHE:CACHE[sig]=InitialEpisode(c['raw'],c['initial_state'],seconds=10,max_nodes=30000,max_sweeps=128)
 ep=copy(CACHE[sig]);ep.weights=ep.weights.copy()
 i=c['task']['input'];q=i['queries'][0];own=c['raw']['own_preferences'];actor=i['observer'];out=[];private=[]
 for event in i['voluntary_history']:
  e=ep.tree.entries[ep.index];before=ep.belief(q['player'],q['goal'],observer=actor,own=own,private_results=private)['preference_weights'];who=e.actor
  ep.observe(event)
  if event.get('action')=='INVESTIGATE' and who==actor:
   f=next(f for f in i['private_results'] if f['player']==event['player'] and f['goal']==event['goal'])
   private.append((f['player'],f['goal'],{'want':1,'neutral':0,'avoid':-1}[f['preference']]))
  after=ep.belief(q['player'],q['goal'],observer=actor,own=own,private_results=private)['preference_weights']
  out.append(dict(actor=who,event=event,before=before,after=after,informative=max(abs(before[k]-after[k]) for k in before)>1e-8))
 return out

def add(pool,c):
 try:
  ev=trace(c);i=c['task']['input'];q=i['queries'][0]
  direct=any(f['player']==q['player'] and f['goal']==q['goal'] for f in i['private_results'])
  partner=[e for e in ev if e['actor']!=i['observer']]
  informed=[e for e in partner if e['informative']]
  if direct:layer='direct_feedback'
  elif len(partner)==1 and len(informed)==1:
   layer='single_elimination' if len(c['task']['teacher']['gold']['possible_preferences'])<3 else 'single_ambiguous'
  elif len(partner)>=2 and len(informed)>=2:layer='multi_update'
  else:return
  if layer=='multi_update' and sum(x['difficulty_layer']==layer and x['source_parent']==c['source_parent'] for x in pool.values())>=2:return
  if sum(x['difficulty_layer']==layer for x in pool.values())>=16:return
  c=qualify(c)
  c['difficulty_layer']=layer;c['evidence_trace']=ev
  c['stratum']=layer
  pool[c['id']]=c
 except (ValueError,RuntimeError,AssertionError) as e:
  errors.append(dict(id=c['id'],error=str(e)))

def materialize(src,ep,events,private):
 i0=src['task']['input'];raw=src['raw'];q=i0['queries'][0];own=raw['own_preferences'];actor=0
 node=ep.tree.entries[ep.index]
 if node.actor!=actor:return None
 weights=ep._weights(actor,own,private);m=ep.belief(q['player'],q['goal'],observer=actor,own=own,private_results=private)['preference_weights']
 i=view(ep,i0['public_preferences'],actor,own,private,[],events);acts=[a.to_dict() for a in node.actions]
 i.update(initial_commitments=src['initial_state']['commitments'],initial_turn_index=src['initial_state'].get('turn_index',0),queries=[q],background_prior=raw['background_prior'],favored_margin=.1,legal_actions=acts,supplied_belief=dict(known_preferences=i0['public_preferences'],unresolved_preferences=[q],support='Infer from visible evidence.'))
 pay=np.array([ep.tree.values[x] for x in node.children]);values=np.einsum('awp,w->ap',pay,weights)
 t=dict(gold=belief(m),preference_weights=m,worlds=ep.tree.worlds,posterior=weights.tolist(),per_world_payoffs=pay.tolist(),action_values=values.tolist(),acceptable_actions=[acts[j] for j in acceptable(values,actor,actions=acts)])
 cid='layer-'+hashlib.sha256(json.dumps([raw,events,private],sort_keys=True).encode()).hexdigest()[:18]
 task=dict(id=cid,task='B',condition='B',skill='formation',input=i,teacher=t);o=deepcopy(task);o.update(task='P',condition='P_infer',skill='history_planning')
 return dict(id=cid,source_parent=src['source_parent'],raw=raw,initial_state=src['initial_state'],task=task,requests=dict(B=request(task,src['initial_state']),O=request(o,src['initial_state'])),history_events=len(events))

errors=[]
def main():
 pool={c['id']:c for c in json.loads((HERE/'qualified_pool.json').read_text())} if (HERE/'qualified_pool.json').exists() else {}
 sources=[]
 for name in ['candidates','feedback_candidates','interaction_candidates']:
  rows=json.loads((ROOT/'new/diagnostic_v7'/f'{name}.json').read_text());sources+=rows
  for c in rows:
   if not (HERE/'qualified_pool.json').exists():add(pool,c)
 (HERE/'qualified_pool.json').write_text(json.dumps(list(pool.values()),indent=2)+'\n')
 print('existing',Counter(c['difficulty_layer'] for c in pool.values()),flush=True)
 # True private-query transitions and repeated informative partner decisions.
 seen=set()
 for src in sources:
  if src['raw']['game']['n_players']!=2 or len(src['task']['input']['game']['goals'])>4:continue
  raw=deepcopy(src['raw']);raw['game']['round_robin']=[0,1,1,0]
  raw['game']['n_actions_per_player']=[2,2]
  for g,goal in enumerate(raw['game']['goals']):
   goal['required_actions']=[dict(player_id=0,action_id=(g//2)%2),dict(player_id=1,action_id=g%2)]
  initial=dict(commitments=[[0,0],[0,0]],turn_index=1,investigation_remaining=[0,0])
  sig=json.dumps([raw,initial],sort_keys=True)
  if sig in seen:continue
  seen.add(sig);s=dict(src,raw=raw,initial_state=initial,source_parent=src['source_parent']+'-v8-window')
  try:ep=InitialEpisode(raw,initial,seconds=5,max_nodes=30000,max_sweeps=128)
  except (ValueError,RuntimeError,AssertionError) as e:
   errors.append(dict(id=src['id'],error='generation: '+str(e)));continue
  CACHE[json.dumps([raw,initial],sort_keys=True)]=ep
  frontier=[(ep,[],[])]
  for depth in range(7):
   nxt=[]
   for cur,events,private in frontier:
    node=cur.tree.entries[cur.index]
    if events and node.actor==0:
     c=materialize(s,cur,events,private)
     if c:add(pool,c)
    if node.actor is None:continue
    for ai,a in enumerate(node.actions):
     event=a.to_dict()
     if not float(cur._weights(0,raw['own_preferences'],private)@cur.tree.policy[cur.index][ai])>0:continue
     child=copy(cur);child.weights=cur.weights.copy()
     try:child.observe(event)
     except ValueError:continue
     if event.get('action')=='INVESTIGATE':
      q=src['task']['input']['queries'][0]
      if node.actor!=0 or (event['player'],event['goal'])!=(q['player'],q['goal']):continue
      for value in (1,0,-1):
       facts=[(q['player'],q['goal'],value)]
       try:
        c=materialize(s,child,events+[event],facts)
        if c:add(pool,c)
       except (ValueError,AssertionError):pass
     else:nxt.append((child,events+[event],private))
   frontier=nxt[:80]
  counts=Counter(c['difficulty_layer'] for c in pool.values())
  if len(seen)%5==0:print('searched',len(seen),counts,flush=True)
  if all(counts[k]>=12 for k in ['direct_feedback','single_elimination','single_ambiguous','multi_update']):break
  if counts['multi_update']>=12:break
  if len(seen)>=35:break
 (HERE/'qualified_pool.json').write_text(json.dumps(list(pool.values()),indent=2)+'\n')
 (HERE/'generation_audit.json').write_text(json.dumps(dict(counts=Counter(c['difficulty_layer'] for c in pool.values()),errors=errors),indent=2)+'\n')
 print('FINAL',Counter(c['difficulty_layer'] for c in pool.values()),flush=True)
if __name__=='__main__':main()
