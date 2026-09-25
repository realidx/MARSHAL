"""Isolated frozen-request micro learning experiment."""
from copy import deepcopy
from collections import defaultdict
import hashlib,json
from examples.social_mixed.micro_learning_v1 import dataset
from training.social_mixed.reasoning_training import group_advantages
VERSION='micro-learning-frozen-v1'
def identity():
 dataset.load()
 raw=(dataset.ROOT/'manifest.json').read_bytes()
 if dataset.FROZEN_LR:raw+=dataset.NAME.encode()
 return hashlib.sha256(raw).hexdigest()
class PipelineCollector:
 def __init__(self,data,generate,seed=42,concurrency=8,protocol_coefficient=.2,normalization='standard_sequence'):
  if normalization!='standard_sequence':raise ValueError('Micro requires standard_sequence')
  self.data=data;self.concurrency=concurrency
  self.generate=generate;self.seed=seed;self.coefficient=protocol_coefficient
  self.tasks={r['id']:r['task'] for r in dataset.load()}
  self.state=dict(version=VERSION,bank_sha256=identity(),step=0,consumed=0)
 def restore(self,state,arm=None):
  if state['version']!=VERSION or state['bank_sha256']!=identity():raise ValueError('Micro resume mismatch')
  self.state=deepcopy(state)
 def collect(self,step,arm,token_target=65536,validation=False):
  if validation or step!=self.state['step']:raise ValueError('Micro collection state mismatch')
  specs=dataset.batch(step,self.seed);outputs=self.generate([x['request'] for x in specs])
  if len(outputs)!=len(specs):raise ValueError('Missing micro responses')
  groups=defaultdict(list)
  for spec,out in zip(specs,outputs):
   if not out.get('response_ids') or len(out['response_ids'])!=len(out.get('behavior_log_probs',[])):raise ValueError('Missing behavior tokens/probabilities')
   s=dataset.score(spec['task_id'],out['completion'])
   if s.get('reward') is None:raise ValueError('Unscorable micro response')
   groups[spec['group']].append((spec,out,s))
  rows=[];units=[];weight=dataset.row_weight()
  for group,items in groups.items():
   adv,valid=group_advantages([x[2] for x in items],[x[1] for x in items],'standard_sequence')
   for (spec,out,s),a,ok in zip(items,adv,valid):
    task=self.tasks[spec['task_id']];kind=task.get('paired_view',task['task']);unit=f'{group}:r{spec["replica"]}'
    row=dict(out,request=spec['request'],kind=kind,task_id=spec['task_id'],group=group,unit=unit,replica=spec['replica'],score=s,training_mode='static',task_advantage=a,protocol_advantage=0. if ok else -self.coefficient,protocol_failure=None if ok else ('truncated' if out['completion']['finish_reason']=='length' else 'invalid_action'),task_denominator=0.,task_weight=weight,protocol_weight=weight,kl_weight=weight,loss_weight=weight,selected_task_group=any(abs(v)>1e-12 for v in adv))
    row['advantage']=row['task_advantage']+row['protocol_advantage'];rows.append(row)
    units.append(dict(unit=unit,group=group,kind=kind,utility=s['reward']))
  tokens=sum(len(r['response_ids']) for r in rows)
  self.state.update(step=step+1,consumed=self.state['consumed']+tokens)
  return rows,units,[],dict(rows=len(rows),generated_tokens=tokens,candidate_groups=len(groups),skip_optimizer=False)
