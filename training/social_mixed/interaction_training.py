"""Opt-in collector for the mixed static/short-interaction candidate.

Returns the existing sequence-loss row contract; does not change default jobs.
"""
from collections import Counter
from copy import deepcopy
import hashlib,json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
from training.social_mixed.b_learning_sampling import select
from training.social_mixed.paired_requests import request
from training.social_mixed.reasoning_scoring import score
from training.social_mixed.reasoning_training import group_advantages
from training.social_mixed.short_interaction import ShortInteraction,decision_request,decode_action

VERSION = 'interaction-v2-name-contract'

def static_request(task):
 """Use precisely the name mapping consumed by the static scorer."""
 variant=task.get('name_variant',0)
 payload=request(task,variant=variant)
 from training.b_sft import social_named_probe as named
 expected=(named.request(task,'action_tools',variant)['tools'] if task['task']=='B'
           else named.action_tools(named.present(task,variant)))
 if payload['tools']!=expected:
  raise ValueError('Request/scorer tool contract mismatch: '+task['id'])
 return payload

class InteractionCollector:
 def __init__(self,tasks,generate,seed=42):
  self.tasks={t['id']:t for t in tasks};self.generate=generate;self.seed=seed;self.envs={}
  self.sha=hashlib.sha256(json.dumps(tasks,sort_keys=True).encode()).hexdigest()
  self.state=dict(version=VERSION,bank_sha256=self.sha,step=0,counts={},consumed=0)
  root=Path(__file__).resolve().parents[2]/'examples/social_mixed/compact_bank_200'
  self.p_reference=list(map(json.loads,(root/'tasks.jsonl').read_text().splitlines()))
  self.p_categories=json.loads((root/'metadata.json').read_text())['categories']
  if {t['id']:t for t in tasks if t['paired_view']=='Pplus'}!={t['id']:t for t in self.p_reference if t['paired_view']=='Pplus'}:raise ValueError('P reference changed')
 def restore(self,state):
  if state['version']!=VERSION or state['bank_sha256']!=self.sha:raise ValueError('Candidate/state mismatch')
  self.state=deepcopy(state)
 def collect(self,arm='decomposed'):
  if arm not in ('decomposed','outcome'):raise ValueError('O or D only')
  # Transactional bookkeeping: failed inference does not advance exposure.
  counts=deepcopy(self.state['counts']);plan=[];working=deepcopy(self.state);working['block']=self.state['step']
  pools=[('O',2,'short_interaction'),('O',2,'static')]
  if arm=='decomposed':pools += [('B',4,None),('Pplus',4,None)]
  for kind,size,mode in pools:
   if kind=='Pplus':
    from training.social_mixed.coverage_sampling import choose_view
    from training.social_mixed.reasoning_training import case_schedule
    proxy=SimpleNamespace(state=working,schedule=case_schedule(self.p_reference,self.seed),views={(t['canonical_id'],t['paired_view']):t for t in self.p_reference},p_categories=self.p_categories,feedback_windows={})
    plan.extend(proxy.views[c,v]['id'] for c,v,_ in choose_view(proxy,'Pplus',size));continue
   candidates=[dict(t,b_sampling_weight=t.get('b_sampling_weight',1.)) for t in self.tasks.values() if t['paired_view']==kind and (mode is None or t.get('training_mode')==mode)]
   plan.extend(select(candidates,counts,size))
  rows=[];units=[];step=self.state['step']
  for slot,tid in enumerate(plan):
   task=self.tasks[tid];kind=task['paired_view'];group=f'{step}:{slot}:{tid}';trajectories=[]
   short=task.get('training_mode')=='short_interaction'
   if short and tid not in self.envs:self.envs[tid]=ShortInteraction(task,seconds=10,max_nodes=30000,max_sweeps=128)
   pending=[]
   if not short:
    payloads=[]
    for replica in range(8):
     payload=static_request(task);payload['seed']=int(hashlib.sha256(f'{self.seed}:{group}:{replica}:0'.encode()).hexdigest()[:8],16);payloads.append(payload)
    pending=self.generate(payloads)
    if len(pending)!=8:raise ValueError('Missing static rollout outputs')
   for replica in range(8):
    calls=[]
    def run(payload):
     payload=deepcopy(payload);payload['seed']=int(hashlib.sha256(f'{self.seed}:{group}:{replica}:{len(calls)}'.encode()).hexdigest()[:8],16)
     if short:
      generated=self.generate([payload])
      if len(generated)!=1:raise ValueError('Missing short rollout output')
      output=generated[0]
     else:output=pending[replica]
     if output['completion'].get('status')=='infrastructure_failure':raise ValueError('Infrastructure failure')
     if not output.get('response_ids') or not output.get('behavior_log_probs'):raise ValueError('Missing behavior tokens/probabilities')
     if len(output['behavior_log_probs'])!=len(output['response_ids']):raise ValueError('Behavior probability/token mismatch')
     calls.append(dict(output,request=payload))
     return output['completion']
    if short:
     def agent(inp):
      completion=run(decision_request(inp))
      try:return decode_action(inp,completion)
      except (ValueError,TypeError,KeyError):return dict(action='INVALID_SUBMISSION')
     result=self.envs[tid].rollout(agent,seed=self.seed+step*100000+slot*100+replica)
     ok=result['status']=='terminal';value=result['terminal_utility']
     scores=[dict(status='ok' if ok else 'format_failure',reward=value,correct=None)]*len(calls)
    else:
     completion=run(static_request(task));s=score(task,completion);scores=[s]
     if s.get('reward') is None:raise ValueError('Unscorable response')
     ok=s['status']!='format_failure' and completion.get('finish_reason')!='length'
     value=s['reward']
    trajectories.append(dict(calls=calls,scores=scores,ok=ok,value=value))
   if short:
    vals=[t['value'] for t in trajectories if t['ok']];mean=float(np.mean(vals)) if vals else 0.;std=float(np.std(vals)) if vals else 0.
    advantages=[(t['value']-mean)/(std+1e-6) if t['ok'] else 0. for t in trajectories]
   else:
    advantages,_=group_advantages([t['scores'][0] for t in trajectories],[t['calls'][0] for t in trajectories],'standard_sequence')
   for replica,(tr,a) in enumerate(zip(trajectories,advantages)):
    unit=f'{group}:r{replica}';units.append(dict(unit=unit,group=group,kind=kind,utility=tr['value']))
    for decision,(output,s) in enumerate(zip(tr['calls'],tr['scores'])):
     invalid=not tr['ok'] and decision==len(tr['calls'])-1
     rows.append(dict(output,kind=kind,task_id=tid,canonical_id=task['canonical_id'],group=group,unit=unit,replica=replica,
       name_variant=0 if short else task.get('name_variant',0),decision=decision,trajectory_length=len(tr['calls']),training_mode='short_interaction' if short else 'static',score=s,
       task_advantage=float(a),protocol_advantage=-.2 if invalid else 0.,protocol_failure=('truncated' if output['completion'].get('finish_reason')=='length' else 'invalid_action') if invalid else None,
       task_denominator=0.,selected_task_group=any(abs(v)>1e-12 for v in advantages)))
  n=len(rows);groups=Counter(self.tasks[tid]['paired_view'] for tid in plan);share=1/len(groups)
  for row in rows:
   w=n*share/(groups[row['kind']]*8*row['trajectory_length'])
   row.update(task_weight=w,protocol_weight=w,kl_weight=w,loss_weight=w,advantage=row['task_advantage']+row['protocol_advantage'])
  tokens=sum(len(r['response_ids']) for r in rows)
  working.update(counts=counts,step=step+1,consumed=self.state['consumed']+tokens)
  self.state=working
  metrics={}
  for kind in groups:
   for mode in ('static','short_interaction'):
    selected=[r for r in rows if r['kind']==kind and r['training_mode']==mode]
    if not selected:continue
    prefix=f'signal/{kind}/{mode}/'
    grouped={r['group'] for r in selected}
    metrics.update({prefix+'groups':len(grouped),prefix+'active_groups':len({r['group'] for r in selected if abs(r['task_advantage'])>1e-12}),prefix+'positive_units':len({r['unit'] for r in selected if r['task_advantage']>1e-12}),prefix+'truncations':sum(r['protocol_failure']=='truncated' for r in selected),prefix+'invalid_actions':sum(r['protocol_failure']=='invalid_action' for r in selected),prefix+'masked_calls':sum(r['score'].get('semantic_outcome')=='masked' for r in selected)})
  return rows,units,[],dict(metrics,rows=n,generated_tokens=tokens,candidate_groups=len(plan),skip_optimizer=False,
      short_groups=sum(self.tasks[k].get('training_mode')=='short_interaction' for k in plan))
