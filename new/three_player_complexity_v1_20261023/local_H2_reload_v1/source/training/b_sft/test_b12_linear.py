import json,unittest
from copy import deepcopy
from collections import defaultdict
from training.b_sft.build_b12_linear import build,OUT,ROOT
from training.b_sft.social_named_probe import request
from training.b_sft.social_bp_training import native_completion,reward

class B12LinearTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.tasks,cls.checks,cls.unavailable=build()
 def test_expected_likelihoods(self):
  expected={('partial_helpful','binary'):[[.5,.5,.5],[.5,.5,.5]],
   ('partial_helpful','linear'):[[1,1,0],[0,0,1]],
   ('partial_harmful','binary'):[[.5,.5,.5],[.5,.5,.5]],
   ('partial_harmful','linear'):[[1,0,0],[0,1,1]],
   ('compensated_control','binary'):[[1,1,1]],('compensated_control','linear'):[[1,1,1]],
   ('target_offer_control','binary'):[[.5,0,0]],('target_offer_control','linear'):[[.5,0,0]],
   ('background_offer','binary'):[[.5,1,1]],('background_offer','linear'):[[.5,1,.5]],
   ('partial_background','linear'):[[0,0,.5]]}
  actual=defaultdict(list)
  for c in self.checks:actual[c['case'],c['mode']].append(c['likelihood'])
  self.assertEqual(dict(actual),expected)
 def test_pairs_only_change_scoring(self):
  groups=defaultdict(list)
  for t in self.tasks:groups[t['b12_case'],json.dumps(t['input']['voluntary_history'],sort_keys=True)].append(t)
  pairs=0
  for ts in groups.values():
   if len(ts)!=2:continue
   inputs=[deepcopy(t['input']) for t in ts]
   def normalize(x):
    if isinstance(x,dict):
     for k,v in x.items():
      if k=='binary':x[k]=True
      else:normalize(v)
    elif isinstance(x,list):
     for v in x:normalize(v)
   for inp in inputs:normalize(inp)
   self.assertEqual(*inputs);pairs+=1
  self.assertEqual(pairs,7)
 def test_impossible_excluded(self):
  self.assertEqual(len(self.unavailable),3)
  for x in self.unavailable:self.assertFalse(any(x['likelihood']))
 def test_rewards_and_budget(self):
  self.assertEqual(len(self.tasks),15)
  for t in self.tasks:
   self.assertFalse(t['training_ready']);self.assertEqual(t['split'],'train')
   self.assertEqual(reward(t,native_completion(t))['reward'],1)
   self.assertEqual(request(t,'action_tools',t['name_variant'])['max_tokens'],1024)
 def test_candidate_preserves_previous(self):
  def read(path):return [json.loads(s) for s in path.read_text().splitlines()]
  old=read(ROOT/'examples/social_bp/b3_external_linear_v1/bp_candidate_tasks.jsonl')
  new=read(OUT/'bp_candidate_tasks.jsonl')
  self.assertEqual(new[:len(old)],old);self.assertEqual(len(new),306)
  self.assertEqual(len({t['id'] for t in new}),306)
if __name__=='__main__':unittest.main()
