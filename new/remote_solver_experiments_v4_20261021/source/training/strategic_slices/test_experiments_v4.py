import unittest
import numpy as np
from .test_equilibrium import off_path_tree,signaling_tree
from .equilibrium import (_backward_local_repair,_staged_cells,certify_policy,solve_equilibrium)

class ExperimentsV4(unittest.TestCase):
    def test_backward_repairs_actual_off_path_continuation(self):
        tree=off_path_tree();self.assertIsNone(certify_policy(tree))
        _backward_local_repair(tree)
        self.assertIsNotNone(certify_policy(tree))

    def test_backward_preserves_response_social_tie(self):
        tree=off_path_tree(response_tie=True)
        _backward_local_repair(tree)
        self.assertIsNotNone(certify_policy(tree))

    def test_staging_is_only_candidate_working_set(self):
        tree=signaling_tree();before=[None if p is None else p.copy() for p in tree.policy]
        cells={(0,0),(0,1),(1,0),(4,0)}
        selected=_staged_cells(tree,cells,limit=2)
        self.assertEqual(len(selected),2);self.assertTrue(selected<=cells)
        for a,b in zip(before,tree.policy):
            if a is not None:np.testing.assert_array_equal(a,b)
        self.assertIsNone(certify_policy(tree))

    def test_sparse_known_nonuniform_equilibrium(self):
        tree=signaling_tree();tree.experiment_mode='sparse'
        result=solve_equilibrium(tree,max_sweeps=40)
        self.assertAlmostEqual(result['policy'][0][0,1],.5,places=6)
        self.assertAlmostEqual(result['policy'][1][0,0],.25,places=6)
        self.assertTrue(result['certificate']['local_own_support_verified'])
