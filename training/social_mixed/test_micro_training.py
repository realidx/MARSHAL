import unittest,json
from examples.social_mixed.micro_learning_v1 import dataset
from training.social_mixed.micro_training import PipelineCollector
class MicroTests(unittest.TestCase):
 def test_schedule(self):
  from collections import Counter
  c=Counter()
  for step in range(40):
   b=dataset.batch(step);self.assertEqual(len(b),96 if dataset.NAME=='24' else 104);c.update(set(r['task_id'] for r in b))
  self.assertEqual(set(c.values()),{20 if dataset.NAME=='24' else 40})
 def test_collection(self):
  examples=[json.loads(l) for l in (dataset.ROOT/'examples.jsonl').read_text().splitlines()]
  gold={r['task_id']:r['completion'] for r in examples if r['score']['correct']}
  specs=dataset.batch(0)
  def generate(requests):
   return [dict(completion=gold[s['task_id']],response_ids=[1,2],behavior_log_probs=[-.1,-.2]) for s in specs]
  c=PipelineCollector({},generate);rows,units,_,m=c.collect(0,'decomposed')
  self.assertEqual(len(rows),96 if dataset.NAME=='24' else 104);self.assertTrue(all(r['score']['correct'] for r in rows));self.assertTrue(all(r['task_advantage']==0 for r in rows))
  self.assertEqual(c.state['step'],1)
  with self.assertRaises(ValueError):c.restore(dict(c.state,version='other'))
