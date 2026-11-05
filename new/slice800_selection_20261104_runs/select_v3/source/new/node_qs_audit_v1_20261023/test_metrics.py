"""Independent small decision problems for omission and recall semantics."""
from types import SimpleNamespace as NS
import itertools
import unittest

import numpy as np

from .metrics import forest_response


class Action:
    def __init__(self, name): self.name=name
    def to_dict(self): return {'action':self.name}
    def __eq__(self, other): return isinstance(other,Action) and self.name==other.name


def entry(turn, *, actor=None, children=(), payoff=None):
    return NS(actor=actor, children=children, payoff=payoff,
              actions=tuple(Action(str(a)) for a in range(len(children))),
              node=NS(state=NS(turn_index=turn),pending=None))


class ConstantObservation:
    def key(self,i,wi,omitted): return ('same-visible-context',)


class Tests(unittest.TestCase):
    def test_current_context_not_ex_ante_average(self):
        # Private answer: same physical root, two worlds, different optimal acts.
        tree=NS(w=2,n=2,entries=[entry(0,actor=0,children=(1,2)),
            entry(1,payoff=np.array([[2.,0],[0,0]])),
            entry(1,payoff=np.array([[0.,0],[1,0]]))],
            policy=[np.full((2,2),.5),None,None])
        result=forest_response(tree,0,{0:np.array([.5,.5])},
            omitted=('private',1,0),observations=ConstantObservation())
        # Blind optimizes its 1 vs .5 means: always A. True context losses 0,1,
        # not the ex ante .5 repeated at both contexts.
        np.testing.assert_allclose(result['values'][0][:,0],[2,0])
        np.testing.assert_allclose(result['root_policy'][0],[[1,1],[0,0]])

    def test_public_histories_share_one_decision(self):
        tree=NS(w=1,n=2,entries=[entry(1,actor=0,children=(1,2)),
            entry(2,payoff=np.array([[1.,0]])),entry(2,payoff=np.array([[0.,0]])),
            entry(1,actor=0,children=(4,5)),entry(2,payoff=np.array([[0.,0]])),
            entry(2,payoff=np.array([[1.,0]]))],
            policy=[np.ones((2,1))*.5,None,None,np.ones((2,1))*.5,None,None])
        result=forest_response(tree,0,{0:np.array([.5]),3:np.array([.5])},
            omitted=('history',0),observations=ConstantObservation())
        np.testing.assert_allclose(result['values'][0],[[.5,0]])
        np.testing.assert_allclose(result['values'][3],[[.5,0]])
        self.assertEqual(result['merged_cells'],1)

    def test_post_entry_action_recall_changes_optimum(self):
        # At turn1 the raw observation is identical after the two own actions.
        # Remembering the own action permits matching it, value1. Forgetting
        # it and using a shared turn1 action would incorrectly reduce value.
        tree=NS(w=1,n=2,entries=[entry(0,actor=0,children=(1,4)),
            entry(1,actor=0,children=(2,3)),entry(2,payoff=np.array([[1.,0]])),
            entry(2,payoff=np.array([[0.,0]])),entry(1,actor=0,children=(5,6)),
            entry(2,payoff=np.array([[0.,0]])),entry(2,payoff=np.array([[1.,0]]))],
            policy=[np.full((2,1),.5),np.full((2,1),.5),None,None,np.full((2,1),.5),None,None])
        class Obs:
            def key(self,i,wi,omitted): return (tree.entries[i].node.state.turn_index,)
        result=forest_response(tree,0,{0:np.array([1.])},observations=Obs())
        self.assertAlmostEqual(result['values'][0][0,0],1.)
        # Independently enumerate deterministic plans (a,b_after0,b_after1).
        brute=max(float(plan[1+plan[0]]==plan[0]) for plan in itertools.product(range(2),repeat=3))
        self.assertAlmostEqual(result['values'][0][0,0],brute)

    def test_new_observation_can_restore_omitted_information(self):
        tree=NS(w=2,n=2,entries=[entry(0,actor=1,children=(1,4)),
            entry(1,actor=0,children=(2,3)),entry(2,payoff=np.array([[1.,0],[0,0]])),
            entry(2,payoff=np.array([[0.,0],[1,0]])),entry(1,actor=0,children=(5,6)),
            entry(2,payoff=np.array([[1.,0],[0,0]])),entry(2,payoff=np.array([[0.,0],[1,0]]))],
            policy=[np.eye(2),np.full((2,2),.5),None,None,np.full((2,2),.5),None,None])
        class Obs:
            def key(self,i,wi,omitted): return ('new-public-signal',i)
        result=forest_response(tree,0,{0:np.array([.5,.5])},
            omitted=('history',-1),observations=Obs())
        np.testing.assert_allclose(result['values'][0][:,0],[1,1])


if __name__=='__main__': unittest.main()
