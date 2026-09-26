import json,random,tempfile,unittest
from pathlib import Path
from examples.final_evaluation.team_benac import load
from examples.final_evaluation.adversarial_runtime import play
from examples.final_evaluation.bounded_reference import BoundedController,Window,predict
from training.social_mixed.core import Episode
import numpy as np

class BoundedTests(unittest.TestCase):
 def test_all_games_and_seats(self):
  _,rows=load(Path('examples/final_evaluation/team_benac_2p_v1'));rng=random.Random(46)
  def generate(route,request):
   f=rng.choice(request['tools'])['function'];args=rng.choice(f['parameters'].get('enum',[{}]))
   return dict(completion=dict(raw_message=dict(content='',tool_calls=[dict(function=dict(name=f['name'],arguments=json.dumps(args)))]),finish_reason='tool_calls'))
  with tempfile.TemporaryDirectory() as d:
   for r in rows:
    for seat in (0,1):
     result=play(r,seat,0,dict(q0={},focal={}),Path(d),generate,oracle=BoundedController(r,seat,42))
     self.assertEqual(result[0]['status'],'terminal',result[0]['error'])
 def test_hidden_world_invariance_and_depth(self):
  _,rows=load(Path('examples/final_evaluation/team_benac_2p_v1'));r=rows[0]
  ep=Episode(r,r['id'],0,42);actor=ep.rules.actor(ep.node);c=BoundedController(r,1-actor,42)
  a=c.choose(ep)['completion'];own=ep.world[actor]
  ep.world=next(w for w in ep.rules.worlds if w[actor]==own and w!=ep.world)
  self.assertEqual(a,c.choose(ep)['completion'])
  t=Window(c.rules,c.node,c.rules.worlds,c.weights,seconds=30,max_nodes=10000,max_sweeps=1)
  for e in t.entries:
   if e.actor is None:self.assertIsNone(e.node.pending);self.assertLessEqual(e.node.state.turn_index,2)
  pred=predict(c.rules,c.node,c.rules.worlds,c.weights)
  self.assertTrue(np.all(pred>0));np.testing.assert_allclose(pred.sum(axis=0),1)
  # Counterfactual reference actions must not update its belief; focal actions must.
  before=c.weights.copy();action=c.rules.actions(c.node)[0].to_dict();c.observe(action)
  np.testing.assert_array_equal(before,c.weights)
if __name__=='__main__':unittest.main()
