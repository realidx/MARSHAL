import unittest,json
from examples.social_mixed.micro_learning_v1 import dataset
from training.social_mixed.micro_training import PipelineCollector
class MicroTests(unittest.TestCase):
 def test_schedule(self):
  from collections import Counter
  c=Counter()
  for step in range(40):
   b=dataset.batch(step);self.assertEqual(len(b),104 if dataset.NAME=='13' else 32*len(dataset.KINDS));c.update(set(r['task_id'] for r in b))
  self.assertEqual(set(c.values()),{40 if dataset.NAME=='13' else 20})
 def test_collection(self):
  examples=[json.loads(l) for l in (dataset.ROOT/'examples.jsonl').read_text().splitlines()]
  gold={r['task_id']:r['completion'] for r in examples if r['score']['correct']}
  specs=dataset.batch(0)
  def generate(requests):
   return [dict(completion=gold[s['task_id']],response_ids=[1,2],behavior_log_probs=[-.1,-.2]) for s in specs]
  c=PipelineCollector({},generate);rows,units,_,m=c.collect(0,'decomposed')
  self.assertEqual(len(rows),104 if dataset.NAME=='13' else 32*len(dataset.KINDS));self.assertTrue(all(r['score']['correct'] for r in rows));self.assertTrue(all(r['task_advantage']==0 for r in rows))
  self.assertEqual(c.state['step'],1)
  with self.assertRaises(ValueError):c.restore(dict(c.state,version='other'))

class MatchedMicroTests(unittest.TestCase):
 def test_matched_variants(self):
  import os
  from unittest.mock import patch
  import importlib
  from collections import Counter
  original=dataset.NAME
  def activate(name):
   with patch.dict(os.environ,{'SOCIAL_MICRO_VARIANT':name}):importlib.reload(dataset)
  try:
   activate('24v2');full=[dataset.batch(i) for i in range(40)]
   records=dataset.load();by_id={r['id']:r for r in records}
   for batch in full:
    operations=[by_id[r['task_id']]['operation'] for r in batch if r['replica']==0 and by_id[r['task_id']]['evidence']['kind']=='B']
    self.assertEqual(set(operations),{'insufficient','exclude','favored','revealed'})
   old=[json.loads(l) for l in (dataset.ROOT.parent/'micro_learning_24_v1'/'tasks.jsonl').read_text().splitlines()]
   self.assertEqual([r for r in records if r['evidence']['kind']=='P'],[r for r in old if r['evidence']['kind']=='P'])
   lrs=[dataset.scheduled_learning_rate(i) for i in range(40)]
   from training.social_mixed.micro_training import identity
   full_id=identity()
   activate('24v2_no_b');control=[dataset.batch(i) for i in range(40)]
   self.assertNotEqual(full_id,identity())
   kinds={r['id']:r['evidence']['kind'] for r in dataset.load()}
   for a,b in zip(full,control):
    self.assertEqual([r for r in a if kinds[r['task_id']]!='B'],b)
    self.assertEqual(len(a),96);self.assertEqual(len(b),64)
   self.assertEqual(lrs,[dataset.scheduled_learning_rate(i) for i in range(40)])
   self.assertEqual(set(Counter(r['task_id'] for b in control for r in b if r['replica']==0).values()),{20})
   self.assertAlmostEqual(dataset.row_weight()/64,1/96)
  finally:activate(original)

 def test_shared_objective_gradient(self):
  import torch
  from training.social_mixed.objective import stable_objective
  # Full arm's shared contribution with B zeroed equals no-B's 64 rows.
  x=torch.full((96,3),-.45,requires_grad=True)
  old=torch.full_like(x,-.5);ref=torch.full_like(x,-.4);mask=torch.ones_like(x)
  weights=torch.cat([torch.ones(64),torch.zeros(32)])
  data=dict(task_advantage=torch.linspace(-1,1,96),protocol_advantage=torch.full((96,),-.2),
            task_denominator=torch.zeros(96),task_weight=weights,protocol_weight=weights,kl_weight=weights)
  full,_=stable_objective(x,old,ref,mask,data,.2,.01);full.backward();expected=x.grad[:64].clone()
  y=x[:64].detach().clone().requires_grad_()
  reduced={k:v[:64].clone() for k,v in data.items()}
  for k in ('task_weight','protocol_weight','kl_weight'):reduced[k].fill_(2/3)
  loss,_=stable_objective(y,old[:64],ref[:64],mask[:64],reduced,.2,.01);loss.backward()
  torch.testing.assert_close(y.grad,expected)

class OriginalBankAblationTests(unittest.TestCase):
 def test_shared_exposures_and_weights(self):
  import os,importlib
  from unittest.mock import patch
  from training.social_mixed.micro_training import identity
  from collections import Counter
  original=dataset.NAME;plans={};rates={};identities=set()
  try:
   for arm in ('d','c','o'):
    with patch.dict(os.environ,{'SOCIAL_MICRO_VARIANT':'24v1_'+arm}):importlib.reload(dataset)
    plans[arm]=[dataset.batch(i) for i in range(40)]
    rates[arm]=[dataset.scheduled_learning_rate(i) for i in range(40)]
    identities.add(identity())
    n={'d':96,'c':64,'o':32}[arm]
    self.assertTrue(all(len(b)==n for b in plans[arm]))
    self.assertAlmostEqual(dataset.row_weight()/n,1/96)
    self.assertEqual(set(Counter(r['task_id'] for b in plans[arm] for r in b if r['replica']==0).values()),{20})
   self.assertEqual(len(identities),3)
   kinds={r['id']:r['evidence']['kind'] for r in dataset.load()}
   for arm,keep in [('c',{'O','P'}),('o',{'O'})]:
    self.assertEqual(rates[arm],rates['d'])
    for full,part in zip(plans['d'],plans[arm]):self.assertEqual([r for r in full if kinds[r['task_id']] in keep],part)
   from pathlib import Path
   source=dataset.ROOT.parent/'micro_learning_24_v1'
   self.assertEqual((dataset.ROOT/'tasks.jsonl').read_bytes(),(source/'tasks.jsonl').read_bytes())
  finally:
   with patch.dict(os.environ,{'SOCIAL_MICRO_VARIANT':original}):importlib.reload(dataset)
