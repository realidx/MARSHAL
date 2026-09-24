"""Build a 200/200/200 candidate with actual O rollouts and structural B variants."""
import json,hashlib,random
from copy import deepcopy
from pathlib import Path
from collections import Counter
import numpy as np
from training.b_sft.debug.audit_readable_pretraining import reconstruct
from training.b_sft.social_private_teacher import PrivateEpisode
from training.b_sft.preference_contract import profile,belief
from training.b_sft.social_b_oracle import NAMES
from training.social_mixed.short_interaction import ShortInteraction,decision_request,decode_action
from training.social_mixed.reasoning_scoring import score
from training.b_sft.social_bp_training import native_completion
ROOT=Path(__file__).resolve().parents[3];OUT=Path(__file__).resolve().parent
base=list(map(json.loads,(ROOT/'examples/social_mixed/compact_bank_200/tasks.jsonl').read_text().splitlines()))
audit=json.loads((ROOT/'examples/social_mixed/b_learning_candidate_v1/task_audit.json').read_text())
prototypes=[r['id'] for r in audit if r['category']=='improving_repeated_contrast' and r['semantic_monotone']]
byid={t['id']:t for t in base};errors=[];new_b=[];seen={hashlib.sha256(json.dumps(t['input'],sort_keys=True).encode()).hexdigest() for t in base if t['paired_view']=='B'}
# Preserve operation/history/geometry; change actual prior or own preference,
# then solve the native policy again. Never inherit the old label.
for variant in range(12):
 for tid in prototypes:
  if len(new_b)>=20:break
  old=byid[tid];inp=deepcopy(old['input']);raw,own=reconstruct(inp)
  weights=((3,2,1),(1,3,2),(2,1,3),(4,3,3),(3,4,3),(3,3,4))[variant%6]
  prior='variant_'+'_'.join(map(str,weights))
  prior_spec=dict(version='public-prior-margin-v1',name=prior,weights=dict(zip(('want','neutral','avoid'),weights)))
  if variant>=6:
   g=(variant//6-1)%len(own);own=list(own);own[g]=0 if own[g]!=0 else -1
   if 1 not in own:continue
   raw['own_preferences']=own
   # Own information is evidence, not a change to the common type universe.
   if list(own) not in [list(x) for x in raw['type_catalogues'][str(inp['player'])]]:continue
   inp['own_preferences']={f'goal_{g}':NAMES[v] for g,v in enumerate(own)}
  inp['background_prior']=prior_spec;raw['background_prior']=prior_spec
  signature=hashlib.sha256(json.dumps(inp,sort_keys=True).encode()).hexdigest()
  if inp==old['input'] or signature in seen:continue
  try:
   ep=PrivateEpisode(raw,inp.get('imposed_setup',[]),seconds=5,max_nodes=30000,max_sweeps=128)
   for action in inp.get('voluntary_history',[]):ep.observe(action)
   facts=[(r['player'],r['goal'],{'want':1,'neutral':0,'avoid':-1}[r['preference']]) for r in inp.get('private_results',[])]
   q=inp['queries'][0];mass=ep.belief(q['player'],q['goal'],observer=inp['player'],own=own,private_results=facts)['preference_weights']
   assert ep.tree.entries[ep.index].node.state.public_state()==inp['current_state']
   t=deepcopy(old);t.update(id=signature[:20]+'-B',canonical_id=signature,source='learning-structure-variant-v1',training_ready=False,
      structure_prototype=tid,variant_prior=prior,input=inp,b_sampling_weight=1.)
   t['teacher']=dict(gold=belief(mass),preference_weights=mass,policy_sha256=ep.tree.certificate['policy_sha256'])
   t['canonical_action_task']['input']=deepcopy(inp)
   # The internal action wrapper is for rendering only, not a newly certified P.
   t['canonical_action_task']['teacher']={}
   assert score(t,native_completion(t))['correct']
   new_b.append(t);seen.add(signature)
  except Exception as exc:errors.append(dict(stage='B',prototype=tid,variant=variant,error=str(exc)))
 if len(new_b)>=20:break
if len(new_b)!=20:raise RuntimeError(f'Only {len(new_b)} valid B variants; do not pad')
# Expand from existing train-only native scene pool, preserving all 66 qualified
# original O roots. Exclude validation identities and duplicate observations.
qualified=json.loads((ROOT/'examples/social_mixed/short_interaction_v1/qualification.json').read_text())['parents']
old_ids={r['id'] for r in qualified if r['status']=='qualified'}
pool=[t for t in base if t['id'] in old_ids]
for filename in ['progressive_bank_v1/tasks.jsonl','combined_curriculum_v1/tasks.jsonl','paired_bank_v2/tasks.jsonl']:
 pool.extend(t for t in map(json.loads,(ROOT/'examples/social_mixed'/filename).read_text().splitlines()) if t['paired_view']=='O' and t['split']=='train')
short=[];root_seen=set();attempted=set();rollouts=[]
cached={};cached_results={}
if (OUT/'tasks.jsonl').exists() and (OUT/'audit.json').exists():
 cached={t['id']:t for t in map(json.loads,(OUT/'tasks.jsonl').read_text().splitlines()) if t.get('training_mode')=='short_interaction'}
 cached_results={r['id']:r for r in json.loads((OUT/'audit.json').read_text())['short_rollouts']}
for t in pool:
 if len(short)==100:break
 if t['input']['game']['n_players']!=2:continue
 signature=hashlib.sha256(json.dumps(t['input'],sort_keys=True).encode()).hexdigest()
 if signature in attempted:continue
 attempted.add(signature)
 if t['id'] in cached and t['id'] in cached_results and t['input']==cached[t['id']]['input'] and t['teacher']==cached[t['id']]['teacher']:
  short.append(cached[t['id']]);rollouts.append(cached_results[t['id']]);continue
 try:
  env=ShortInteraction(t,seconds=5,max_nodes=30000,max_sweeps=128)
  rewards=[]
  for seed in range(8):
   rng=random.Random(seed)
   def agent(inp):
    req=decision_request(inp);tool=rng.choice(req['tools'])['function']
    return decode_action(inp,dict(raw_message=dict(tool_calls=[dict(function=dict(name=tool['name'],arguments=json.dumps(rng.choice(tool['parameters']['enum']))))])))
   result=env.rollout(agent,seed);assert result['status']=='terminal';rewards.append(result['terminal_utility'])
  copy=deepcopy(t);copy['training_mode']='short_interaction';copy['max_ego_decisions']=env.max_decisions;copy['training_ready']=False
  short.append(copy);root_seen.add(signature);rollouts.append(dict(id=t['id'],max_ego_decisions=env.max_decisions,rewards=rewards))
 except Exception as exc:errors.append(dict(stage='O',id=t['id'],error=str(exc)))
if len(short)!=100:raise RuntimeError(f'Only {len(short)} qualified O roots; do not pad')
static=[t for t in base if t['paired_view']=='O' and t['id'] not in old_ids]
# Stratified removal of 34 static slots; retain broad structural coverage.
static.sort(key=lambda t:(t.get('operation_curriculum',{}).get('O',''),t['id']))
remove_indices={int(i*len(static)/34) for i in range(34)}
removed=[t['id'] for i,t in enumerate(static) if i in remove_indices]
static=[dict(t,training_mode='static') for i,t in enumerate(static) if i not in remove_indices]
assert len(static)==100
weights={'always_correct':.25,'other':1.,'improving_limited_or_fluctuating':1.5,'improving_repeated_contrast':2.}
b=[]
for r in audit:
 if r['category']=='hard_holdout':continue
 t=deepcopy(byid[r['id']]);t['b_sampling_weight']=weights[r['category']]
 if r['category']=='improving_repeated_contrast' and not r['semantic_monotone']:t['b_sampling_weight']=1.
 b.append(t)
rows=static+short+b+new_b+[t for t in base if t['paired_view']=='Pplus']
assert Counter(t['paired_view'] for t in rows)==dict(O=200,B=200,Pplus=200)
(OUT/'tasks.jsonl').write_text(''.join(json.dumps(t)+'\n' for t in rows))
(OUT/'audit.json').write_text(json.dumps(dict(prototypes=prototypes,new_b=[dict(id=t['id'],prototype=t['structure_prototype'],gold=t['teacher']['gold'],prior=t['variant_prior']) for t in new_b],short_rollouts=rollouts,removed_static_o=removed,excluded=errors),indent=2)+'\n')
print(dict(counts=Counter(t['paired_view'] for t in rows),short=len(short),new_b=len(new_b),prototypes=Counter(t['structure_prototype'] for t in new_b)))
