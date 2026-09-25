import unittest,json
from examples.social_mixed.micro_learning_v1 import dataset
from training.social_mixed.micro_training import PipelineCollector
class MicroTests(unittest.TestCase):
 def test_schedule(self):
  from collections import Counter
  c=Counter()
  for step in range(40):
   expected=({'24v1_partner_o':48,'24v1_partner_c':96}.get(dataset.NAME,128)) if dataset.NAME.startswith('24v1_partner') else (104 if dataset.NAME=='13' else 32*len(dataset.KINDS))
   b=dataset.batch(step);self.assertEqual(len(b),expected);c.update(set(r['task_id'] for r in b))
  self.assertEqual(set(c.values()),{40 if dataset.NAME=='13' else 20})
 def test_collection(self):
  if dataset.NAME.startswith('24v1_partner'):self.skipTest('New partner-choice tasks have no historical model completions; tested below with native gold calls')
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

class PartnerChoiceTrainingTests(unittest.TestCase):
 def test_frozen_32_task_schedule_and_collector(self):
  import os,importlib
  from collections import Counter
  from unittest.mock import patch
  from training.social_mixed.micro_training import identity
  from training.b_sft.social_named_probe import present,action_call
  original=dataset.NAME
  try:
   with patch.dict(os.environ,{'SOCIAL_MICRO_VARIANT':'24v1_partner'}):importlib.reload(dataset)
   root=dataset.ROOT;old=root.parent/'micro_learning_24_v1_matched'
   assert (root/'augmented_tasks.jsonl').read_bytes().startswith((old/'tasks.jsonl').read_bytes())
   records=dataset.load();self.assertEqual(len(records),32)
   self.assertEqual(len({r['id'] for r in records}),32)
   by_id={r['id']:r for r in records};counts=Counter()
   old_schedule=[json.loads(line) for line in (old/'schedule.jsonl').read_text().splitlines()]
   proposed=[json.loads(line) for line in (root/'proposed_schedule.jsonl').read_text().splitlines()]
   self.assertEqual(len(proposed),40)
   for step,plan in enumerate(proposed):
    self.assertEqual(plan['original_task_ids'],old_schedule[step]['task_ids'])
    self.assertEqual(len(plan['additional_task_ids']),4)
    batch=dataset.batch(step);self.assertEqual(len(batch),128)
    counts.update(r['task_id'] for r in batch if r['replica']==0)
    self.assertEqual(dataset.scheduled_learning_rate(step),old_schedule[step]['learning_rate'])
   self.assertEqual(set(counts.values()),{20})
   self.assertAlmostEqual(dataset.row_weight()/128,1/96)
   self.assertNotEqual(identity(),'')
   old_examples=[json.loads(line) for line in (old/'examples.jsonl').read_text().splitlines()]
   gold={r['task_id']:r['completion'] for r in old_examples if r['score']['correct']}
   for row in records[24:]:
    task=row['task'];shown=present(task,task.get('name_variant',0))['legal_actions']
    accepted=task['teacher']['acceptable_actions']
    native=task['input']['legal_actions']
    choice=next(view for action,view in zip(native,shown) if action in accepted)
    name,args=action_call(choice)
    completion=dict(raw_message=dict(content='Native gold regression call.',tool_calls=[dict(function=dict(name=name,arguments=json.dumps(args)))]),finish_reason='stop')
    self.assertTrue(dataset.score(row['id'],completion)['correct'])
    gold[row['id']]=completion
   specs=dataset.batch(0)
   def generate(requests):
    self.assertEqual(len(requests),128)
    return [dict(completion=gold[s['task_id']],response_ids=[1,2],behavior_log_probs=[-.1,-.2]) for s in specs]
   collector=PipelineCollector({},generate)
   rows,units,_,_=collector.collect(0,'decomposed')
   self.assertEqual(len(rows),128)
   self.assertTrue(all(r['score']['correct'] for r in rows))
   self.assertTrue(all(r['task_advantage']==0 for r in rows))
   full_plans=[dataset.batch(i) for i in range(40)]
   full_identity=identity();identities={full_identity}
   for variant,keep,n in [('24v1_partner_o',{'O'},48),('24v1_partner_c',{'O','P'},96)]:
    with patch.dict(os.environ,{'SOCIAL_MICRO_VARIANT':variant}):importlib.reload(dataset)
    identities.add(identity());counts=Counter()
    for step,full in enumerate(full_plans):
     part=dataset.batch(step)
     self.assertEqual(part,[r for r in full if by_id[r['task_id']]['evidence']['kind'] in keep])
     self.assertEqual(len(part),n)
     counts.update(r['task_id'] for r in part if r['replica']==0)
     self.assertEqual(dataset.scheduled_learning_rate(step),old_schedule[step]['learning_rate'])
    self.assertEqual(set(counts.values()),{20})
    self.assertEqual(len(counts),n//4)
    self.assertAlmostEqual(dataset.row_weight()/n,1/96)
    specs=dataset.batch(0)
    def generate_subset(requests):
     self.assertEqual(len(requests),n)
     return [dict(completion=gold[s['task_id']],response_ids=[1,2],behavior_log_probs=[-.1,-.2]) for s in specs]
    collector=PipelineCollector({},generate_subset)
    rows,_,_,_=collector.collect(0,'decomposed')
    self.assertEqual(len(rows),n)
    self.assertTrue(all(r['score']['correct'] for r in rows))
    self.assertTrue(all(r['task_advantage']==0 for r in rows))
    for row in rows:
     for key in ('task_weight','protocol_weight','kl_weight'):
      self.assertAlmostEqual(row[key],dataset.row_weight())
   self.assertEqual(len(identities),3)
  finally:
   with patch.dict(os.environ,{'SOCIAL_MICRO_VARIANT':original}):importlib.reload(dataset)
