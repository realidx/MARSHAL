"""Reuse must preserve full histories, private information and certification."""
from copy import deepcopy
import unittest
from unittest.mock import patch

import numpy as np

from training.b_sft.social_private_teacher import PrivateInvestigationRules
from training.b_sft.shared_teacher import SearchLimit
from .bounded import BoundedPrivateWindow
from .bounded_cache import (BoundedProblemCache, problem_identity, reuse_structure,
                            structural_subtree_snapshot)
from .test_bounded_diagnostic import tiny_parent


class BoundedCacheTest(unittest.TestCase):
    def setUp(self):
        self.raw = tiny_parent(0, 2, 3)
        self.rules = PrivateInvestigationRules(self.raw)
        self.kwargs = dict(seconds=10, horizon_mode='rr', solver_mode='synchronous')

    def key(self, root=None, rules=None, raw=None, weights=None, **kwargs):
        rules = self.rules if rules is None else rules
        root = rules.initial() if root is None else root
        return problem_identity(rules, root, rules.worlds, weights,
                                self.raw if raw is None else raw, **dict(self.kwargs, **kwargs))[0]

    def test_key_keeps_full_history_absolute_endpoint_and_all_settings(self):
        root = self.rules.initial()
        pass_root = self.rules._apply(root, self.rules.actions(root)[0])
        offer_root = self.rules._apply(root, self.rules.actions(root)[1])
        reject_root = self.rules._apply(offer_root, self.rules.actions(offer_root)[0])
        self.assertEqual(pass_root.state.snapshot_commitments(), reject_root.state.snapshot_commitments())
        self.assertEqual(pass_root.state.turn_index, reject_root.state.turn_index)
        self.assertNotEqual(self.key(pass_root), self.key(reject_root))
        self.assertNotEqual(self.key(), self.key(lookahead_rr=2))
        self.assertNotEqual(self.key(), self.key(horizon_mode='rr-plus-next-own-proposal-v1'))
        self.assertNotEqual(self.key(), self.key(seconds=11))
        self.assertNotEqual(self.key(), self.key(epsilon=1e-7))
        self.assertNotEqual(self.key(), self.key(max_candidates=7))
        self.assertNotEqual(self.key(), self.key(solver_mode='equilibrium'))
        self.assertNotEqual(self.key(root), self.key(offer_root))

    def test_key_conditions_on_prior_and_private_deliveries(self):
        raw = deepcopy(self.raw)
        raw['game']['goals'].append(dict(raw['game']['goals'][0], goal_id=1))
        raw['own_preferences'] = [1, 1]
        raw['type_catalogues'] = {'0': [[1, 1]], '1': [[1, 1], [0, 1]]}
        rules = PrivateInvestigationRules(raw)
        self.assertEqual(self.key(rules=rules, raw=raw, weights=[1, 2]),
                         self.key(rules=rules, raw=raw, weights=[2, 4]))
        self.assertNotEqual(self.key(rules=rules, raw=raw, weights=[1, 2]),
                            self.key(rules=rules, raw=raw, weights=[2, 1]))
        query = next(action for action in rules.actions(rules.initial())
                     if action.to_dict()['action'] == 'INVESTIGATE')
        one = rules.step(rules.initial(), query, realized_world=rules.worlds[0])
        zero = rules.step(rules.initial(), query, realized_world=rules.worlds[1])
        self.assertEqual(one.state.public_state(), zero.state.public_state())
        self.assertNotEqual(self.key(one, rules, raw), self.key(zero, rules, raw))
        symbolic = rules._apply(rules.initial(), query)
        self.assertNotEqual(self.key(symbolic, rules, raw), self.key(one, rules, raw))

    def test_exact_replay_avoids_enumeration_and_solving_with_isolated_results(self):
        cache = BoundedProblemCache()
        first = cache.solve(self.rules, self.rules.initial(), self.rules.worlds,
                            raw=self.raw, **self.kwargs)
        self.assertFalse(first.cache_hit)
        identity = first.tree.reference_identity()
        first.tree.certificate['verified'] = False
        first.tree.policy[0][:] = 0
        first.tree.values[0][:] = 123
        with (patch.object(BoundedPrivateWindow, '_grow', side_effect=AssertionError('No replay enumeration')),
              patch.object(BoundedPrivateWindow, 'solve', side_effect=AssertionError('No replay solve'))):
            replay = cache.solve(self.rules, self.rules.initial(), self.rules.worlds,
                                 raw=self.raw, **self.kwargs)
            self.assertTrue(replay.cache_hit)
            self.assertEqual(replay.tree.reference_identity(), identity)
            self.assertTrue(replay.tree.certificate['verified'])
            self.assertTrue(replay.tree.audit_native()['all_values_match'])
            replay.tree.certificate['verified'] = False
            again = cache.solve(self.rules, self.rules.initial(), self.rules.worlds,
                                raw=self.raw, **self.kwargs)
            self.assertTrue(again.tree.certificate['verified'])
        self.assertEqual(cache.stats()['hits'], 2)
        self.assertEqual(cache.stats()['misses'], 1)
        self.assertGreater(cache.stats()['avoided_recomputation_source_seconds'], 0)
        self.assertEqual(replay.build_seconds, 0)
        self.assertEqual(replay.solve_seconds, 0)

    def test_cache_limits_evict_and_never_store_failed_answers(self):
        cache = BoundedProblemCache(max_entries=1)
        first = cache.solve(self.rules, self.rules.initial(), self.rules.worlds,
                            raw=self.raw, **self.kwargs)
        cache.solve(self.rules, self.rules.initial(), self.rules.worlds,
                    raw=self.raw, **dict(self.kwargs, seconds=11))
        self.assertEqual(cache.stats()['evictions'], 1)
        self.assertEqual(cache.stats()['stored_certified_problems'], 1)
        no_store = BoundedProblemCache(max_cached_nodes=1)
        result = no_store.solve(self.rules, self.rules.initial(), self.rules.worlds,
                                raw=self.raw, **self.kwargs)
        self.assertFalse(result.answer_stored)
        self.assertEqual(no_store.stats()['stored_certified_problems'], 0)
        failed = BoundedProblemCache()
        with patch.object(BoundedPrivateWindow, 'solve', side_effect=ValueError('Failed certification')):
            with self.assertRaises(ValueError):
                failed.solve(self.rules, self.rules.initial(), self.rules.worlds,
                             raw=self.raw, **self.kwargs)
        self.assertEqual(failed.stats()['stored_certified_problems'], 0)
        self.assertTrue(first.tree.certificate['verified'])

    def test_same_cutoff_subtree_reuse_rebuilds_root_and_independently_solves(self):
        raw = tiny_parent(0, 2, 2)
        rules = PrivateInvestigationRules(raw)
        parent_root = rules._apply(rules.initial(), rules.actions(rules.initial())[0])
        kwargs = dict(seconds=10, solver_mode='synchronous')
        parent = BoundedPrivateWindow(rules, parent_root, rules.worlds, **kwargs).solve()
        parent.equilibrium_audit = dict(max_own_deviation_gain=123.)
        index = next(i for i, entry in enumerate(parent.entries)
                     if entry.actor is not None and entry.node.pending is None
                     and entry.node.state.turn_index == 2)
        child_root = parent.entries[index].node
        snapshot = structural_subtree_snapshot(parent, index, parent.cutoff)
        self.assertIsNone(snapshot['certificate'])
        self.assertIsNone(snapshot['policy'])
        self.assertFalse(snapshot['automatically_certified'])
        reused = reuse_structure(parent, index, rules, child_root, rules.worlds, **kwargs)
        self.assertIsNotNone(reused)
        self.assertIsNone(reused.certificate)
        self.assertIsNone(reused.values)
        self.assertIsNone(reused.equilibrium_audit)
        self.assertEqual(reused.root_actor, rules.actor(child_root))
        self.assertEqual(reused.root_turn_index, 2)
        self.assertEqual(reused.cutoff, parent.cutoff)
        self.assertLess(len(reused.entries), len(parent.entries))
        self.assertTrue(reused.audit_native()['native_transitions_match'])
        fresh = BoundedPrivateWindow(rules, child_root, rules.worlds, **kwargs).solve()
        reused.solve()
        self.assertEqual(reused.reference_identity(), fresh.reference_identity())
        np.testing.assert_allclose(reused.values[0], fresh.values[0])
        cache = BoundedProblemCache()
        with patch.object(BoundedPrivateWindow, '_grow', side_effect=AssertionError('No new subtree enumeration')):
            result = cache.solve(rules, child_root, rules.worlds, raw=raw,
                                 parent_tree=parent, parent_root_index=index, **kwargs)
        self.assertTrue(result.structure_reused)
        self.assertFalse(result.cache_hit)
        self.assertTrue(result.tree.certificate['verified'])
        self.assertTrue(result.tree.structure_reuse['independently_certified'])
        self.assertTrue(result.tree.audit_native()['all_values_match'])

    def test_changed_endpoint_or_history_requires_fresh_tree(self):
        parent = BoundedPrivateWindow(self.rules, self.rules.initial(), self.rules.worlds,
                                     **self.kwargs).solve()
        index = next(i for i, entry in enumerate(parent.entries)
                     if entry.actor is not None and entry.node.pending is None
                     and entry.node.state.turn_index == 1)
        child_root = parent.entries[index].node
        self.assertIsNone(structural_subtree_snapshot(parent, index, parent.cutoff + 1))
        self.assertIsNone(reuse_structure(parent, index, self.rules, child_root,
                                         self.rules.worlds, **self.kwargs))

    def test_changed_prior_reuses_structure_but_recomputes_certificate_and_values(self):
        raw = tiny_parent(0, 2, 2)
        raw['game']['goals'].append(dict(raw['game']['goals'][0], goal_id=1))
        raw['own_preferences'] = [1, 1]
        raw['type_catalogues'] = {'0': [[1, 1]], '1': [[1, 1], [1, 0]]}
        rules = PrivateInvestigationRules(raw)
        parent_root = rules._apply(rules.initial(), rules.actions(rules.initial())[0])
        kwargs = dict(seconds=10, solver_mode='synchronous')
        parent = BoundedPrivateWindow(rules, parent_root, rules.worlds,
                                     world_weights=[1, 3], **kwargs).solve()
        index = next(i for i, entry in enumerate(parent.entries)
                     if entry.actor is not None and entry.node.pending is None
                     and entry.node.state.turn_index == 2)
        root = parent.entries[index].node
        cache = BoundedProblemCache()
        first = cache.solve(rules, root, rules.worlds, raw=raw, world_weights=[1, 3],
                            parent_tree=parent, parent_root_index=index, **kwargs)
        with patch.object(BoundedPrivateWindow, '_grow', side_effect=AssertionError('Reuse changed-prior structure')):
            changed = cache.solve(rules, root, rules.worlds, raw=raw, world_weights=[3, 1],
                                  parent_tree=parent, parent_root_index=index, **kwargs)
        fresh = BoundedPrivateWindow(rules, root, rules.worlds,
                                    world_weights=[3, 1], **kwargs).solve()
        self.assertFalse(changed.cache_hit)
        self.assertTrue(changed.structure_reused)
        self.assertNotEqual(first.problem_key, changed.problem_key)
        self.assertNotEqual(first.tree.reference_identity(), changed.tree.reference_identity())
        self.assertEqual(changed.tree.reference_identity(), fresh.reference_identity())
        np.testing.assert_allclose(changed.tree.world_weights, [.75, .25])
        np.testing.assert_allclose(parent.world_weights, [.25, .75])
        np.testing.assert_allclose(changed.tree.values[0], fresh.values[0])
        self.assertTrue(changed.tree.audit_native()['all_values_match'])

    def test_reuse_cannot_bypass_budget_validation(self):
        parent = BoundedPrivateWindow(self.rules, self.rules.initial(), self.rules.worlds,
                                     **self.kwargs)
        for invalid in (dict(seconds=float('nan')), dict(seconds=0), dict(max_nodes=0),
                        dict(max_sweeps=0), dict(epsilon=0), dict(max_candidates=1)):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                reuse_structure(parent, 0, self.rules, self.rules.initial(), self.rules.worlds,
                                **dict(self.kwargs, **invalid))

    def test_failed_root_candidate_does_not_claim_local_checks_passed(self):
        def fail_root(tree):
            tree.equilibrium_audit = dict(max_own_deviation_gain=4e-8)
            raise SearchLimit('Root candidate failed before local certification')

        cache = BoundedProblemCache()
        with patch.object(BoundedPrivateWindow, 'solve', new=fail_root):
            with self.assertRaises(SearchLimit) as failure:
                cache.solve(self.rules, self.rules.initial(), self.rules.worlds,
                            raw=self.raw, **self.kwargs)
        audit = failure.exception.bounded_candidate_audit
        self.assertFalse(audit['is_oracle_label'])
        self.assertFalse(audit['local_policy_audit_performed'])
        self.assertIsNone(audit['own_information_cell_failures'])
        self.assertIsNone(audit['response_social_tie_failures'])
        self.assertEqual(cache.stats()['stored_certified_problems'], 0)


if __name__ == '__main__':
    unittest.main()
