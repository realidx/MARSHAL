"""Sparse exactness against an independently unfolded native action tree."""
import unittest

import numpy as np
from training.b_sft.social_private_teacher import PrivateWindow, PrivateInvestigationRules
from .build import sample_parent
from .reference import FixedReference
from .sparse import SparseWindow
from .values import window_values, masked_answer_value
from .diagnose_horizon import public_history_nodes


class SparseTests(unittest.TestCase):
    def test_sparse_values_match_full_unpruned_tree(self):
        raw = sample_parent(20261027, 3, 1)
        rules = PrivateInvestigationRules(raw)
        reference = FixedReference(rules, raw['background_prior'])
        # Full tree is constructed independently by the existing native
        # PrivateWindow; there is no sparse pruning or collapsed tail here.
        full = PrivateWindow(rules, rules.initial(), rules.worlds,
                             world_weights=reference.world_weights, seconds=30, max_nodes=10000)
        full.policy = [None if e.actor is None else reference.probabilities(e.node) for e in full.entries]
        full.certificate = dict(verified=True, policy_sha256=reference.contract_sha256)
        ego = full.entries[0].actor
        weights = reference.world_weights * np.array([w[ego] == rules.worlds[0][ego] for w in rules.worlds])
        weights /= weights.sum()
        for bound in (1, 2, 3):
            sparse = SparseWindow(reference, rules.initial(), ego, weights, bound)
            self.assertLess(len(sparse.entries), len(full.entries))
            self.assertFalse(sparse.certificate['equilibrium_verified'])
            sparse.audit_native()
            for k in range(1, bound + 1):
                dense_values = window_values(full, ego, 0, weights, k)
                sparse_values = window_values(sparse, ego, 0, weights, k)
                np.testing.assert_allclose([dense_values['V_star'], dense_values['V_min'], dense_values['C_span']],
                    [sparse_values['V_star'], sparse_values['V_min'], sparse_values['C_span']], atol=1e-10)
                np.testing.assert_allclose(dense_values['root_Q'], sparse_values['root_Q'], atol=1e-10)
                for action in full.entries[0].actions:
                    a = action.to_dict()
                    if a.get('action') != 'INVESTIGATE':
                        continue
                    kwargs = dict(ego=ego, root_index=0, root_weights=weights, k=k,
                                  query_slot=(a['player'], a['goal']))
                    dense_s = masked_answer_value(full, **kwargs)
                    sparse_s = masked_answer_value(sparse, **kwargs)
                    np.testing.assert_allclose([dense_s['V_full'], dense_s['V_mask'], dense_s['S']],
                                              [sparse_s['V_full'], sparse_s['V_mask'], sparse_s['S']], atol=1e-10)

    def test_three_rounds_keep_delayed_consequences(self):
        raw = sample_parent(20261027, 3, 3)
        reference = FixedReference(PrivateInvestigationRules(raw), raw['background_prior'])
        ego = reference.rules.actor(reference.rules.initial())
        weights = reference.world_weights * np.array([w[ego] == reference.worlds[0][ego] for w in reference.worlds])
        weights /= weights.sum()
        tree = SparseWindow(reference, reference.rules.initial(), ego, weights, 3)
        self.assertLess(len(tree.entries), 30000)
        short = window_values(tree, ego, 0, weights, 1)
        long = window_values(tree, ego, 0, weights, 3)
        self.assertGreaterEqual(long['C_span'] + 1e-10, short['C_span'])
        self.assertTrue(tree.tail_indices)
        tree.audit_native()

    def test_full_public_history_count_is_not_small_physical_dag(self):
        raw = sample_parent(20261027, 3, 2)
        count = public_history_nodes(raw)
        self.assertEqual(count['public_history_nodes'], 6287343)
        self.assertLess(count['physical_counting_states'], 1000)

    def test_short_window_tail_can_repair_all_focal_mistakes(self):
        raw = sample_parent(20261018, 3, 3)
        reference = FixedReference(PrivateInvestigationRules(raw), raw['background_prior'])
        node = reference.rules.initial(); weights = reference.world_weights.copy()
        # A legal reached entrance: one accepted offer, then a pass. Compute
        # its posterior independently of the dataset entrance sampler.
        for ai in (3, 1, 0):
            actions = reference.rules.actions(node)
            weights *= .75 * reference.probabilities(node)[ai] + .25 / len(actions)
            node = reference.rules._apply(node, actions[ai])
        ego = reference.rules.actor(node)
        self.assertEqual(ego, 2)
        weights *= np.array([list(w[ego]) == [0, 1, 1, 1] for w in reference.worlds])
        weights /= weights.sum()
        tree = SparseWindow(reference, node, ego, weights, 5)
        short = window_values(tree, ego, 0, weights, 3)
        long = window_values(tree, ego, 0, weights, 5)
        np.testing.assert_allclose([short['V_star'], short['V_min'], short['C_span']], [3., 3., 0.])
        np.testing.assert_allclose([long['V_star'], long['V_min'], long['C_span']], [3., 1., 2.])
        # Forced first-action values alone are flat: the consequence comes
        # from actual later choices, not an invented root-action reward.
        np.testing.assert_allclose(long['root_Q'], 3.)


if __name__ == '__main__':
    unittest.main()
