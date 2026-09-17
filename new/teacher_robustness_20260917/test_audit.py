import unittest
from types import SimpleNamespace as S
import numpy as np
from audit import posterior,label
class Action:
 def __init__(self,value):self.value=value
 def to_dict(self):return self.value
class Tests(unittest.TestCase):
 def test_noise_restores_behavior_support_but_not_private_fact_exclusions(self):
  action={'response':'ACCEPT'}
  entry=S(actions=[Action(action),Action({'response':'REJECT'})],children=[1,2])
  worlds=[((1,),(v,)) for v in (1,0,-1)]
  e=S(tree=S(world_weights=np.ones(3)/3,worlds=worlds,entries=[entry],policy=[np.array([[0,.25,1],[1,.75,0]])]))
  inp=dict(voluntary_history=[action],own_preferences={'goal_0':'want'},game={'goals':[{}]},player=0,private_results=[])
  w,_,_=posterior(e,inp,0);np.testing.assert_allclose(w,[0,.2,.8])
  noisy,_,_=posterior(e,inp,.1)
  expected=np.array([.05,.275,.95]);expected/=expected.sum()
  np.testing.assert_allclose(noisy,expected);self.assertGreater(noisy[0],0)
  inp['private_results']=[dict(player=1,goal=0,preference='avoid')]
  conditioned,_,_=posterior(e,inp,.1);np.testing.assert_array_equal(conditioned,[0,0,1])
if __name__=='__main__':unittest.main()
