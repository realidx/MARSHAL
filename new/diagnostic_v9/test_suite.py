import json,unittest
from copy import deepcopy
from collections import Counter
from new.diagnostic_v9.experiment import load,p_request,run_case,summarize,action_score
from new.diagnostic_v7.test_suite import gold_b,action
from new.diagnostic_v7.build import qualify

class Tests(unittest.TestCase):
 def test_certificates_and_oracle(self):
  _,cases=load();rows=[]
  self.assertEqual(set(c['difficulty_layer'] for c in cases),{'direct_feedback','single_elimination','single_ambiguous','multi_update'})
  for c in cases:
   self.assertEqual(qualify(c)['certificate'],c['certificate'])
   informative=[e for e in c['evidence_trace'] if e['actor']!=c['task']['input']['observer'] and e['informative']]
   if c['difficulty_layer']=='multi_update':self.assertGreaterEqual(len(informative),2)
   elif c['difficulty_layer'].startswith('single_'):self.assertEqual(len(informative),1)
   self.assertIn('possible_preferences lists the preferences still possible',p_request(c,c['gold_judgment'])['messages'][1]['content'])
   for idx in range(len(c['task']['input']['legal_actions'])):
    self.assertEqual(action_score(c,action(c,idx))['correct'],idx in c['certificate']['acceptable_action_indices'])
   idx=c['certificate']['acceptable_action_indices'][0]
   rows.append(run_case(c,lambda kind,req:gold_b(c) if kind=='B' else action(c,idx)))
  multi=[c for c in cases if c['difficulty_layer']=='multi_update']
  self.assertGreaterEqual(len({c['source_parent'] for c in multi}),4)
  s=summarize(rows,len(rows))
  self.assertEqual(s['primary_panels'],['repair_sensitive','action_control'])
  for panel in s['panels'].values():
   for component in ['support','favored','joint']:self.assertEqual(panel['B'][component+'_accuracy_all'],1)
if __name__=='__main__':unittest.main()
