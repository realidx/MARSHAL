"""Validated opt-in release loader for O100/B-structure training."""
import hashlib,json
from pathlib import Path
from collections import Counter
PATH=Path(__file__).resolve().parents[2]/'examples/social_mixed/interaction_bank_v1/tasks.jsonl'
def load():
 raw=PATH.read_bytes();tasks=[json.loads(line) for line in raw.splitlines()]
 if Counter(t['paired_view'] for t in tasks)!=dict(O=200,B=200,Pplus=200):raise ValueError('Interaction bank counts changed')
 if len({t['id'] for t in tasks})!=600 or any(t['split']!='train' for t in tasks):raise ValueError('Invalid identities/split')
 if sum(t.get('training_mode')=='short_interaction' for t in tasks)!=100:raise ValueError('Expected 100 short roots')
 return tasks,hashlib.sha256(raw).hexdigest()

class PipelineCollector:
 """Bridge the new collector to the existing pipeline call/restore contract."""
 def __init__(self,data,generate,seed=42,concurrency=8,protocol_coefficient=.2,normalization='standard_sequence'):
  from training.social_mixed.interaction_training import InteractionCollector
  if normalization!='standard_sequence' or protocol_coefficient!=.2:raise ValueError('Interaction recipe requires standard_sequence and protocol coefficient 0.2')
  self.data=data;self.concurrency=concurrency
  self.inner=InteractionCollector(data['bp_train'],generate,seed)
 @property
 def state(self):return self.inner.state
 def restore(self,state,arm=None):self.inner.restore(state)
 def collect(self,step,arm,token_target=65536,validation=False):
  if validation:raise ValueError('Use the fixed static validator')
  if self.state['step']!=step:raise ValueError('Collector/optimizer step mismatch')
  return self.inner.collect(arm)
