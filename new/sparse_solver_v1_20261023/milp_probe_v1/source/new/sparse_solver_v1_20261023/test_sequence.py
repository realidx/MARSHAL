"""Independent payoff/BR equivalence and a known mixed-strategy equilibrium."""
from types import SimpleNamespace
import time
import unittest

import numpy as np
from scipy.optimize import linprog

from .common import parents
from .probe import build
from .sequence import SequenceGame


class SparseSequenceTests(unittest.TestCase):
    def test_native_random_policy_payoffs_and_full_best_responses(self):
        # A real unsolved terminal parent, including investigation/private recall.
        tree=build(parents()[9]);game=SequenceGame(tree)
        rng=np.random.default_rng(23)
        for i,groups in tree.information_groups.items():
            for ids in groups:
                tree.policy[i][:,ids]=rng.dirichlet(np.ones(len(tree.entries[i].actions)))[:,None]
        game.red.install()
        rs=[game.realization(tree.policy,p) for p in range(2)]
        values=tree.evaluate()[0]
        for p in range(2):
            target=np.zeros(game.E[p].shape[0]);target[0]=1.
            np.testing.assert_allclose(game.E[p]@rs[p],target,atol=1e-12)
            expected=rs[0]@game.A[p]@rs[1]-game.shift
            self.assertAlmostEqual(expected,tree.world_weights@values[:,p],places=11)
            c=game.A[p]@rs[1] if p==0 else game.A[p].T@rs[0]
            lp=linprog(-c,A_eq=game.E[p],b_eq=target,bounds=(0,1),method='highs')
            self.assertTrue(lp.success)
            _,br=tree.response(p)
            self.assertAlmostEqual(-lp.fun-game.shift,tree.world_weights@br[:,p],places=10)

    def test_matching_pennies_mixed_solution(self):
        # Sequential encoding of simultaneous matching pennies: player 1's
        # information set spans player 0's two actions. Use sequence matrices
        # directly to avoid inventing a public-history information-set fixture.
        from scipy.sparse import csr_matrix
        game=SequenceGame.__new__(SequenceGame)
        game.counts=[3,3];game.upper=3.;game.shift=2.
        game.E=[csr_matrix([[1,0,0],[-1,1,1]],dtype=float)]*2
        from .sequence import Cell
        game.cells=[{(0,0):Cell(0,0,0,(1,2),(0,1),1.)}]*2
        a=np.zeros((3,3));a[1:,1:]=[[3,1],[1,3]]
        b=np.zeros((3,3));b[1:,1:]=[[1,3],[3,1]]
        game.A=[csr_matrix(a),csr_matrix(b)]
        result,info=game.solve(seconds=5)
        self.assertIsNotNone(result,info)
        for r in result:np.testing.assert_allclose(r,[1,.5,.5],atol=1e-9)
        self.assertLess(info['max_complementarity'],1e-9)


if __name__=='__main__':unittest.main()
