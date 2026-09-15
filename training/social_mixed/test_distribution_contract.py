import unittest
import numpy as np
from training.b_sft.preference_contract import belief,profile,world_weights
class DistributionContractTests(unittest.TestCase):
 def test_b_margin_does_not_remove_possible_values(self):
  self.assertEqual(belief({'want':.45,'neutral':.4,'avoid':.15}),dict(possible_preferences=['want','neutral','avoid'],favored='undetermined'))
  self.assertEqual(belief({'want':.6,'neutral':.3,'avoid':.1})['favored'],'want')
  self.assertEqual(belief({'want':.4,'neutral':.3,'avoid':.3})['favored'],'undetermined')
  self.assertEqual(belief({'want':1.,'neutral':0.,'avoid':0.}),dict(possible_preferences=['want'],favored='want'))
  self.assertIn('avoid',belief({'want':.9,'neutral':.099999,'avoid':.000001})['possible_preferences'])
 def test_conditioned_background_weights(self):
  worlds=[((1,1),(v,1)) for v in (1,0,-1)]
  np.testing.assert_allclose(world_weights(worlds,profile('want_heavy')),[.5,.25,.25])
  np.testing.assert_allclose(world_weights(worlds,profile('neutral_heavy')),[.25,.5,.25])
  np.testing.assert_allclose(world_weights([((1,),(1,))],profile('avoid_heavy')),[1.])
class CurriculumTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import json
  from training.social_mixed.core import DATA,load_data
  cls.data=load_data();cls.root=DATA
  cls.links=json.loads((DATA/'p4_links.json').read_text())
  cls.diag=[json.loads(s) for s in (DATA/'diagnostics.jsonl').read_text().splitlines()]
 def test_full_coverage_and_every_b_margin(self):
  from training.b_sft.preference_contract import PROFILES
  rows=self.data['bp_train']
  self.assertEqual({(t['kernel'],t['background_profile']) for t in rows},{(k,p) for k in ('B1','B2','B3','P1','P2','P3','P4') for p in PROFILES})
  for t in rows+self.data['bp_validation']:
   if t['task']=='B':self.assertEqual(belief(t['teacher']['preference_weights']),t['teacher']['gold'])
 def test_schedule_covers_every_task_with_whole_controls(self):
  from training.social_mixed.distribution_sampling import groups,select
  rows=self.data['bp_train'];units=groups(rows);seen=set()
  for step in range(512):
   batch=select(rows,step,42);ids={t['id'] for t in batch};seen|=ids
   for unit in units.values():
    u={t['id'] for t in unit}
    if ids&u:self.assertTrue(u<=ids)
   self.assertEqual({len(t['teacher']['gold']['possible_preferences'])==3 for t in batch if t['task']=='B'},{True,False})
  self.assertEqual(seen,{t['id'] for t in rows})
 def test_p4_query_value_equals_weighted_result_continuations(self):
  values={'want':1,'neutral':0,'avoid':-1}
  by={t['id']:t for t in self.data['bp_train']+self.diag}
  for link in self.links:
   parent=by[link['parent']];children=[by[i] for i in link['children']]
   self.assertEqual(len({t['teacher']['policy_sha256'] for t in [parent]+children}),1)
   worlds=parent['teacher']['worlds'];weights=world_weights(worlds,parent['input']['background_prior'])
   actor=parent['input']['player'];expected=0.
   for child in children:
    result=child['input']['private_results'][-1]
    probability=sum(w for world,w in zip(worlds,weights) if world[result['player']][result['goal']]==values[result['preference']])
    expected+=probability*max(v[actor] for v in child['teacher']['action_values'])
   result=children[0]['input']['private_results'][-1]
   query={'action':'INVESTIGATE','player':result['player'],'goal':result['goal']}
   index=parent['input']['legal_actions'].index(query)
   self.assertAlmostEqual(expected,parent['teacher']['action_values'][index][actor],places=8)
if __name__=='__main__':unittest.main()

