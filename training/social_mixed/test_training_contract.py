import copy,json,unittest
from collections import Counter
from training.social_mixed.core import ROOT
DATA=ROOT/'examples/social_mixed/data_plain_v1'
def load_data():
 return {name:[json.loads(x) for x in (DATA/(name+'.jsonl')).read_text().splitlines()] for name in ('bp_train','bp_validation','selfplay_train','selfplay_validation')}
from training.social_mixed.contract_sampling import select,units
from training.social_mixed.prepare_training_contract import audit,read,SOURCE
class ContractTests(unittest.TestCase):
 def test_certified_only_and_original_labels_unchanged(self):
  data=load_data();source={t['id']:t for t in read(SOURCE)}
  for split in ('train','validation'):
   for t in data['bp_'+split]:
    self.assertEqual(t['split'],split);self.assertTrue(t['training_ready'])
    self.assertEqual(t['teacher'],source[t['id']]['teacher'])
    self.assertEqual(t['input'],source[t['id']]['input'])
    self.assertEqual(audit(t)['proof'],t['contract_proof'])
    self.assertNotIn(t['kernel'],('B2','P3','P4'))
  self.assertEqual(len(data['selfplay_train']),36)
 def test_contrasts_preserved_and_no_score_filter(self):
  rows=load_data()['bp_train'];groups=units(rows);seen=set()
  for step in range(30):
   batch=select(rows,step,42);ids={t['id'] for t in batch};seen|=ids
   for group in groups.values():
    g={t['id'] for t in group};self.assertTrue(not(ids&g) or g<=ids)
   self.assertTrue(any(t['task']=='B' and len(t['teacher']['gold']['possible_preferences'])==3 for t in batch))
   self.assertTrue(any(t['task']=='B' and len(t['teacher']['gold']['possible_preferences'])<3 for t in batch))
  self.assertEqual(seen,{t['id'] for t in rows})
 def test_corrupt_labels_rejected(self):
  rows=load_data()['bp_train']
  for t in [next(t for t in rows if t['kernel']=='B1'),next(t for t in rows if t['kernel']=='P2')]:
   t=copy.deepcopy(t)
   if t['task']=='B':t['teacher']['gold']={'possible_preferences':['want','neutral','avoid'],'favored':'undetermined'}
   else:t['teacher']['acceptable_actions']=[]
   with self.assertRaises(ValueError):audit(t)
 def test_audit_accounts_for_every_non_test_candidate(self):
  source={t['id'] for t in read(SOURCE) if t['split']!='test'}
  rows=read(DATA/'audit.jsonl');self.assertEqual({t['id'] for t in rows},source)
  self.assertEqual(len(rows),len(source))
if __name__=='__main__':unittest.main()
