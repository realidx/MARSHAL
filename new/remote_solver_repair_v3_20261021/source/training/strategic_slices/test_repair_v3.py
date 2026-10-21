import unittest
from .test_equilibrium import off_path_tree,signaling_tree
from .equilibrium import local_policy_audit,certify_policy,_repair_local_support,_JointResidual
import numpy as np

class RepairRegression(unittest.TestCase):
    def test_off_path_own_support_repair_requires_fresh_certification(self):
        tree=off_path_tree();audit=local_policy_audit(tree)
        self.assertFalse(audit['local_own_support_verified'])
        self.assertIsNone(certify_policy(tree))
        self.assertTrue(_repair_local_support(tree,audit))
        result=certify_policy(tree)
        self.assertIsNotNone(result)
        self.assertLessEqual(result['certificate']['max_own_deviation_gain'],1e-8)
        self.assertTrue(result['certificate']['local_own_support_verified'])

    def test_response_tie_repair_keeps_original_secondary_objective(self):
        tree=off_path_tree(response_tie=True);audit=local_policy_audit(tree)
        self.assertTrue(audit['local_own_support_verified'])
        self.assertFalse(audit['verified'])
        self.assertIsNone(certify_policy(tree))
        _repair_local_support(tree,audit)
        self.assertIsNotNone(certify_policy(tree))

    def test_valid_initial_point_remains_fallback_for_zero_mass_candidate(self):
        tree=signaling_tree();r=_JointResidual(tree,{(0,0),(0,1),(1,0),(4,0)})
        bad=r.x0.copy()
        for _,_,start,actions in r.offsets:bad[start:start+actions]=-1
        from training.b_sft.shared_teacher import SearchLimit
        with self.assertRaises(SearchLimit):r.normalized_policy(bad)
        p=r.normalized_policy(r.x0)
        for a in p:
            if a is not None:np.testing.assert_allclose(a.sum(axis=0),1)
