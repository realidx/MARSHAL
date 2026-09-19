import json
from pathlib import Path
import unittest
from training.social_mixed.b_bridge_requests import request
from training.social_mixed.prompt_clarification import request as original
from training.b_sft.preference_contract import belief

class BBridgeTests(unittest.TestCase):
 def test_frozen_bridges_and_heldout(self):
  root=Path('examples/social_mixed');new=root/'data_reasoning_v6';old=root/'data_reasoning_v5_candidate'
  for name in ('bp_validation.jsonl','selfplay_train.jsonl','selfplay_validation.jsonl'):
   self.assertEqual((new/name).read_bytes(),(old/name).read_bytes())
  rows=[json.loads(l) for l in (new/'bp_train.jsonl').read_text().splitlines()];by={t['id']:t for t in rows}
  bridges=[t for t in rows if t.get('b_bridge')]
  self.assertTrue(bridges)
  self.assertTrue(any(len(t['teacher']['gold']['possible_preferences'])==3 for t in bridges))
  for t in bridges:
   b=t['b_bridge'];parent=by[b['parent_id']]
   self.assertEqual(t['teacher'],parent['teacher'])
   self.assertEqual(request(parent),original(parent))
   if b['stage']=='likelihood':
    mass={r['preference']:r['prior']*r['likelihood'] for r in b['table']};z=sum(mass.values())
    self.assertEqual(belief({k:v/z for k,v in mass.items()}),t['teacher']['gold'])
   self.assertIn('TRAINING INFERENCE EXERCISE',request(t)['messages'][1]['content'])

if __name__=='__main__':unittest.main()
