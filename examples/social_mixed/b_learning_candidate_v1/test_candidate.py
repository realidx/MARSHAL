import json,unittest
from pathlib import Path
from collections import Counter
from training.social_mixed.b_learning_sampling import select
from training.social_mixed.paired_requests import request
from training.social_mixed.reasoning_scoring import score
from training.b_sft.social_bp_training import native_completion
ROOT=Path(__file__).resolve().parent
class CandidateTests(unittest.TestCase):
 def test_bank(self):
  tasks=list(map(json.loads,(ROOT/'train_b.jsonl').read_text().splitlines()))
  hard={t['id'] for t in map(json.loads,(ROOT/'hard_diagnostic.jsonl').read_text().splitlines())}
  self.assertEqual(len(tasks),200);self.assertEqual(len({t['id'] for t in tasks}),200)
  self.assertFalse(hard & {t['id'] for t in tasks})
  for t in tasks:
   self.assertEqual(t['split'],'train');self.assertEqual(t['paired_view'],'B')
   self.assertTrue(score(t,native_completion(t))['correct'])
   self.assertIn('Briefly explain',request(t)['messages'][1]['content'])
   if t.get('learning_stage')=='prior_without_behavior':
    self.assertEqual(t['input']['voluntary_history'],[])
    self.assertEqual(t['input']['private_results'],[])
 def test_sampler(self):
  tasks=[dict(id='easy',b_sampling_weight=.25),dict(id='normal',b_sampling_weight=1),dict(id='improving',b_sampling_weight=2)]
  counts={}
  for _ in range(130):select(tasks,counts,size=1)
  self.assertEqual(counts,dict(easy=10,normal=40,improving=80))
  before=dict(counts);ids=select(tasks,counts,size=3)
  self.assertEqual(len(set(ids)),3)
if __name__=='__main__':unittest.main()
