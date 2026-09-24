"""Round-trip the actual bank's displayed tools through the actual scorer."""
import json
import unittest
from copy import deepcopy
from unittest.mock import patch
import jsonschema
from training.social_mixed.interaction_bank import load
from training.social_mixed.interaction_training import InteractionCollector,static_request
from training.social_mixed.reasoning_scoring import score
from training.b_sft import social_named_probe as named

class ContractTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.tasks=load()[0]
 def test_entire_static_bank_roundtrip(self):
  counts={}
  for task in self.tasks:
   if task.get('training_mode')=='short_interaction':continue
   req=static_request(task);variant=task.get('name_variant',0)
   counts[variant]=counts.get(variant,0)+1
   answer=named.gold_answer(task,variant)
   name,args=('SUBMIT_BELIEFS',answer) if task['task']=='B' else named.action_call(answer)
   schema=next(t['function']['parameters'] for t in req['tools'] if t['function']['name']==name)
   jsonschema.validate(args,schema)
   completion=dict(finish_reason='stop',raw_message=dict(content='Explanation retained.',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]))
   with self.subTest(task=task['id']):self.assertEqual(score(task,completion)['status'],'ok')
  self.assertEqual(sum(counts.values()),500)
  self.assertTrue(any(k!=0 for k in counts))
 def test_wrong_mapping_is_blocked_before_generation(self):
  task=next(t for t in self.tasks if t['paired_view']=='B' and t.get('name_variant',0)!=0)
  from training.social_mixed.paired_requests import request
  with patch('training.social_mixed.interaction_training.request',return_value=request(task,variant=0)):
   with self.assertRaisesRegex(ValueError,'contract mismatch'):static_request(task)
 def test_collector_weights_and_signal(self):
  answers={}
  for t in self.tasks:
   if t.get('training_mode')=='short_interaction':continue
   req=static_request(t);answer=named.gold_answer(t,t.get('name_variant',0))
   name,args=('SUBMIT_BELIEFS',answer) if t['task']=='B' else named.action_call(answer)
   answers[json.dumps(req['tools'],sort_keys=True)]=(name,args)
  def generate(requests):
   outputs=[]
   for req in requests:
    key=json.dumps(req['tools'],sort_keys=True)
    if key in answers:name,args=answers[key]
    else:
     tool=req['tools'][0]['function'];name=tool['name'];args=tool['parameters']['enum'][0]
    completion=dict(finish_reason='stop',raw_message=dict(content='Explanation.',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]))
    outputs.append(dict(completion=completion,response_ids=[1,2],behavior_log_probs=[-.1,-.2]))
   return outputs
  class Window:
   def __init__(self,task,**kwargs):self.task=task;self.count=0
   def rollout(self,agent,seed):
    agent(self.task['input']);agent(self.task['input']);self.count+=1
    return dict(status='terminal',terminal_utility=float(self.count%2))
  collector=InteractionCollector(self.tasks,generate)
  with patch('training.social_mixed.interaction_training.ShortInteraction',Window):
   rows,units,_,metrics=collector.collect()
  self.assertEqual(len(units),96)
  self.assertEqual(metrics['signal/O/short_interaction/active_groups'],2)
  for kind in ('O','B','Pplus'):
   self.assertAlmostEqual(sum(r['task_weight'] for r in rows if r['kind']==kind)/len(rows),1/3)
  self.assertEqual(collector.state['step'],1)
  for arm,expected_units,shares in [('conditioned',96,{'O':2/3,'Pplus':1/3}),('outcome',32,{'O':1.})]:
   collector=InteractionCollector(self.tasks,generate)
   with patch('training.social_mixed.interaction_training.ShortInteraction',Window):
    rows,units,_,metrics=collector.collect(arm)
   self.assertEqual(len(units),expected_units)
   self.assertEqual({r['kind'] for r in rows},set(shares))
   for kind,share in shares.items():
    self.assertAlmostEqual(sum(r['task_weight'] for r in rows if r['kind']==kind)/len(rows),share)
 def test_old_resume_rejected(self):
  c=InteractionCollector(self.tasks,lambda _:[])
  state=deepcopy(c.state);state['version']='interaction-v1'
  with self.assertRaises(ValueError):c.restore(state)
 def test_failed_generation_does_not_consume_exposure(self):
  c=InteractionCollector(self.tasks,lambda _:[]);old=deepcopy(c.state)
  with patch('training.social_mixed.interaction_training.ShortInteraction') as env:
   env.return_value.rollout.side_effect=RuntimeError('transport failed')
   with self.assertRaises(RuntimeError):c.collect()
  self.assertEqual(c.state,old)
if __name__=='__main__':unittest.main()
