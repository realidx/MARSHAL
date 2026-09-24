import unittest
from training.social_mixed.interaction_bank import load,PipelineCollector
class EntryTests(unittest.TestCase):
 def test_restore_boundary(self):
  tasks,sha=load();c=PipelineCollector(dict(bp_train=tasks),lambda _:[],concurrency=8)
  self.assertEqual(len(sha),64)
  state=dict(c.state);state['step']=20
  c.restore(state,arm='decomposed')
  self.assertEqual(c.state['step'],20)
  with self.assertRaisesRegex(ValueError,'step mismatch'):c.collect(0,'decomposed')
  bad=dict(state,bank_sha256='changed')
  with self.assertRaises(ValueError):c.restore(bad)
  with self.assertRaises(ValueError):PipelineCollector(dict(bp_train=tasks),lambda _:[],normalization='centered_fixed')
if __name__=='__main__':unittest.main()
