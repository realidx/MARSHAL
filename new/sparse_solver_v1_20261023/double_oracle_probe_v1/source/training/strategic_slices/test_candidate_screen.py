"""Fast screening may reject, but cannot replace original certification."""
import unittest
from unittest.mock import patch
import numpy as np

from .batched_response import BatchedResponse
from . import equilibrium as eq
from .test_equilibrium import signaling_tree, off_path_tree
from .build import sample_parent
from .bounded import BoundedPrivateWindow
from training.b_sft.social_private_teacher import PrivateInvestigationRules


class CandidateScreenTests(unittest.TestCase):
    def test_known_nonuniform_equilibrium_still_runs_original_certification(self):
        tree = signaling_tree()
        solved = eq.solve_equilibrium(tree)
        tree.policy = solved['policy']
        tree._candidate_local_screen = BatchedResponse(tree).locally_admissible
        with patch.object(eq, 'certify_policy', wraps=eq.certify_policy) as certify:
            self.assertIsNotNone(eq._certify_candidate(tree, 1e-8, True))
            certify.assert_called_once()

    def test_rejects_off_path_own_and_response_tie_failures_before_certification(self):
        for social in (False, True):
            tree = off_path_tree(response_tie=social)
            tree._candidate_local_screen = BatchedResponse(tree).locally_admissible
            with patch.object(eq, 'certify_policy', wraps=eq.certify_policy) as certify:
                self.assertIsNone(eq._certify_candidate(tree, 1e-8, True))
                certify.assert_not_called()

    def test_social_rule_can_be_disabled_without_disabling_own_support(self):
        tree = off_path_tree(response_tie=True)
        screen = BatchedResponse(tree)
        self.assertTrue(screen.locally_admissible(require_social_ties=False))
        self.assertFalse(screen.locally_admissible(require_social_ties=True))

    def test_native_private_query_partitions_and_random_off_path_policies(self):
        rng = np.random.default_rng(11)
        for players in (2, 3):
            raw = sample_parent(2026100703, players, rounds=1)
            rules = PrivateInvestigationRules(raw)
            tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds, lookahead_rr=3, seconds=60)
            screen = BatchedResponse(tree)
            for pure in (False, True):
                for _ in range(3):
                    for i, groups in tree.information_groups.items():
                        for ids in groups:
                            size = len(tree.entries[i].actions)
                            probabilities = rng.dirichlet(np.ones(size))
                            if pure: probabilities = np.eye(size)[rng.integers(size)]
                            tree.policy[i][:, ids] = probabilities[:, None]
                    audit = eq.local_policy_audit(tree)
                    self.assertEqual(screen.locally_admissible(),
                        audit['verified'] and audit['local_own_support_verified'])


if __name__ == '__main__': unittest.main()
