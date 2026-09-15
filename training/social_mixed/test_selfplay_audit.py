import json,unittest,random
from copy import deepcopy
from training.social_mixed.prepare_selfplay_audit import OUT,ROOT,read,geometry,build,GeneratorConfig,generate_game,classify
from training.social_mixed.selfplay_probe import check,summarize
from training.social_mixed.core import Episode
from training.social_mixed.test_core import legal_response

class SelfplayAuditTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.old,cls.val,cls.test,cls.new,cls.selected,cls.attempts=build()
 def test_generation_reproducible_and_no_prefix(self):
  self.assertEqual(self.new,read(OUT/'train_candidate.jsonl'))
  for r in self.new:
   spec=generate_game(r['generation']['seed'],GeneratorConfig(**r['generation']['config']))
   self.assertEqual(spec.private_preferences.tolist(),r['realized_world'])
   game=spec.to_dict()
   for k in ('private_preferences','metadata','seed'):game.pop(k,None)
   self.assertEqual(game,r['raw']['game']);self.assertFalse(r['raw']['history'])
   ep=Episode(r,r['id'],0,42)
   self.assertFalse(any(any(row) for row in ep.node.state.snapshot_commitments()))
 def test_no_heldout_geometry_overlap_and_test_not_sampled(self):
  self.assertFalse({geometry(r) for r in self.new}&{geometry(r) for r in self.val+self.test})
  self.assertEqual(len(self.new),36);self.assertEqual(len(self.selected),16)
  self.assertEqual(sum(r['split']=='validation' for r in self.selected),4)
  self.assertFalse(any(r['split']=='test' for r in self.selected))
 def test_strata_cross_scoring_and_prior(self):
  cells={(r['players'],classify(r)['completion'],tuple(r['raw']['preference_generation']['values'])) for r in self.new}
  self.assertEqual(len(cells),12)
  probe={(r['players'],classify(r)['completion'],tuple(r['raw']['preference_generation']['values'])) for r in self.selected if r['split']=='train'}
  self.assertEqual(cells,probe)
 def test_scripted_full_games(self):self.assertEqual(check()['scripted_games'],32)
 def test_private_rows_and_ids_not_leaked(self):
  for r in self.selected:
   e=Episode(r,r['id'],0,42);p=e.rules.actor(e.node);obs=e.observation()
   other=next((w for w in e.rules.worlds if w[p]==e.world[p] and w!=e.world),None)
   if other:
    alt=deepcopy(r);alt['realized_world']=other
    self.assertEqual(Episode(alt,r['id'],0,42).observation(),obs)
   self.assertNotIn(r['id'],json.dumps(e.request()))
 def test_statistics_separate_seats_and_missing_outcomes(self):
  reset=self.selected[0];records=[]
  for i in range(4):
   e=Episode(reset,reset['id'],i,42);rng=random.Random(i)
   while e.status=='running':e.accept(legal_response(e,rng))
   records.append(dict(e.summary(),calls=e.calls))
  s=summarize(records);self.assertEqual(len(s['seat_groups']),reset['players'])
  self.assertTrue(all(r['complete_group'] for r in s['seat_groups']))
  records[0]['status']='infrastructure_or_client_failure';records[0]['terminal_utility']=None
  s=summarize(records)
  self.assertTrue(all(r['zero_outcome_advantage'] is None for r in s['seat_groups']))
if __name__=='__main__':unittest.main()
