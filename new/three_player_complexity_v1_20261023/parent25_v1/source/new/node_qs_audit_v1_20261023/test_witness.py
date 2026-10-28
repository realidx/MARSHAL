"""Check that positive S from arbitrary tie choice is not called robust."""
import unittest
from types import SimpleNamespace as NS
import numpy as np

from .test_metrics import entry, ConstantObservation
from .witness import sequence_lp


class Tests(unittest.TestCase):
    def test_blind_tie_can_have_zero_true_context_loss(self):
        tree=NS(w=2,n=2,entries=[entry(0,actor=0,children=(1,2)),
            entry(1,payoff=np.array([[1.,0],[0,0]])),entry(1,payoff=np.array([[0.,0],[1,0]]))],
            policy=[np.full((2,2),.5),None,None])
        result=sequence_lp(tree,0,{0:np.array([.5,.5])},omitted=('private',1,0),
            observations=ConstantObservation(),target=(0,{0}))
        self.assertAlmostEqual(result['V_omitted_LP'],.5)
        # Uniform tie loses .5 in context0, yet an equally good blind policy
        # can always pick A, losing0 there. Interval must expose that freedom.
        self.assertAlmostEqual(result['target_own_value_max'],1.)
        self.assertAlmostEqual(result['target_own_value_min'],0.)

    def test_unique_blind_optimum_has_unavoidable_context_loss(self):
        tree=NS(w=2,n=2,entries=[entry(0,actor=0,children=(1,2)),
            entry(1,payoff=np.array([[2.,0],[0,0]])),entry(1,payoff=np.array([[0.,0],[1,0]]))],
            policy=[np.full((2,2),.5),None,None])
        result=sequence_lp(tree,0,{0:np.array([.5,.5])},omitted=('private',1,0),
            observations=ConstantObservation(),target=(0,{1}))
        self.assertAlmostEqual(result['V_omitted_LP'],1.)
        self.assertAlmostEqual(result['target_own_value_max'],0.)
        self.assertAlmostEqual(result['target_own_value_min'],0.)


if __name__=='__main__':unittest.main()
