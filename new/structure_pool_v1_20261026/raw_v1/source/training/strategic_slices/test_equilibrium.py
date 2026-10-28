"""Independent equilibrium checks on a Bayesian signaling game and native trees."""
from collections import namedtuple
import unittest
from unittest.mock import patch

import numpy as np

from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_private_teacher import PrivateWindow
from training.b_sft.social_terminal_teacher import TerminalWindow
from . import equilibrium as equilibrium_module
from .equilibrium import (_JointResidual, _expand_profitable_supports,
                          certify_policy, solve_equilibrium)


Entry = namedtuple('Entry', 'actor actions children payoff')


def signaling_tree():
    """Known nonuniform equilibrium: bad sender L=.5; receiver A|L=.25.

    Good/bad prior is 1/3,2/3. Good always sends L. Bad receives .25
    for R, and 1/0 for receiver A/B after L. Receiver receives +1/-1
    for A after L according to sender type, 0 for B, and -1 for A|R.
    The receiver observes the public signal but not the sender's type.
    """
    tree = object.__new__(PrivateWindow)
    tree.worlds = (((1,), (0,)), ((-1,), (0,)))
    tree.world_weights = np.array([1/3, 2/3])
    tree.w, tree.n = 2, 2
    L, R = {'action': 'L'}, {'action': 'R'}
    A, B = {'action': 'A'}, {'action': 'B'}
    tree.entries = [
        Entry(0, (L, R), (1, 4), None),
        Entry(1, (A, B), (2, 3), None),
        Entry(None, (), (), np.array([[2., 1.], [1., -1.]])),
        Entry(None, (), (), np.array([[1., 0.], [0., 0.]])),
        Entry(1, (A, B), (5, 6), None),
        Entry(None, (), (), np.array([[0., -1.], [.25, -1.]])),
        Entry(None, (), (), np.array([[0., 0.], [.25, 0.]])),
    ]
    tree.information_groups = {0: [np.array([0]), np.array([1])],
                               1: [np.array([0, 1])],
                               4: [np.array([0, 1])]}
    tree.groups = {0: [np.array([0]), np.array([1])], 1: [np.array([0, 1])]}
    tree.policy = [None if e.actor is None else np.full((2, 2), .5)
                   for e in tree.entries]
    tree._check = lambda: None
    tree.evaluate = lambda policy=None: TerminalWindow.evaluate(tree, policy)
    tree.certificate = tree.values = None
    return tree


def off_path_tree(response_tie=False):
    tree = signaling_tree()
    tree.worlds = (((0,), (0,)),)
    tree.world_weights = np.ones(1)
    tree.w = 1
    actions = (({'response': 'ACCEPT'}, {'response': 'REJECT'}) if response_tie
               else ({'action': 'A'}, {'action': 'B'}))
    tree.entries = [
        Entry(0, ({'action': 'L'}, {'action': 'R'}), (1, 2), None),
        Entry(None, (), (), np.array([[2., 0.]])),
        Entry(1, actions, (3, 4), None),
        Entry(None, (), (), np.array([[0., 0.]])),
        Entry(None, (), (), np.array([[1., 0.]] if response_tie else [[0., 1.]])),
    ]
    tree.groups = {0: [np.array([0])], 1: [np.array([0])]}
    tree.information_groups = {0: [np.array([0])], 2: [np.array([0])]}
    tree.policy = [np.array([[1.], [0.]]), None, np.array([[1.], [0.]]), None, None]
    return tree


class EquilibriumTests(unittest.TestCase):
    def test_matrix_free_solver_above_old_cell_limit(self):
        # One indifferent third player chooses among 100 distinct histories
        # of the independently known signaling game. No histories are merged.
        base = signaling_tree(); tree = signaling_tree(); branches = 100
        tree.n = 3
        tree.worlds = tuple(w + ((0,),) for w in tree.worlds)
        tree.groups[2] = [np.array([0, 1])]
        tree.entries = [Entry(2, tuple({'action': str(i)} for i in range(branches)),
                              tuple(1 + 7*i for i in range(branches)), None)]
        tree.information_groups = {0: [np.array([0, 1])]}
        tree.policy = [np.full((branches, 2), 1/branches)]
        for branch in range(branches):
            offset = 1 + 7*branch
            for i, entry in enumerate(base.entries):
                tree.entries.append(Entry(entry.actor, entry.actions,
                    tuple(c + offset for c in entry.children),
                    None if entry.payoff is None else np.pad(entry.payoff, ((0, 0), (0, 1)))))
                tree.policy.append(None if entry.actor is None else base.policy[i].copy())
                if entry.actor is not None:
                    tree.information_groups[i + offset] = base.information_groups[i]
        result = solve_equilibrium(tree)
        self.assertGreater(result['certificate']['joint_information_cells'], 192)
        self.assertLessEqual(result['certificate']['max_own_deviation_gain'], 1e-8)
        for branch in range(branches):
            root = 1 + 7*branch
            self.assertAlmostEqual(result['policy'][root][0, 1], .5, places=6)
            self.assertAlmostEqual(result['policy'][root + 1][0, 0], .25, places=6)

    def test_known_nonuniform_bayesian_equilibrium(self):
        tree = signaling_tree()
        result = solve_equilibrium(tree, max_sweeps=40, epsilon=1e-8)
        p = result['policy']
        self.assertAlmostEqual(p[0][0, 0], 1., places=6)
        self.assertAlmostEqual(p[0][0, 1], .5, places=6)
        self.assertAlmostEqual(p[1][0, 0], .25, places=6)
        self.assertAlmostEqual(p[4][0, 0], 0., places=6)
        np.testing.assert_allclose(p[1][:, 0], p[1][:, 1])
        certificate = result['certificate']
        self.assertTrue(certificate['own_utility_epsilon_nash_verified'])
        self.assertFalse(certificate['exact_equilibrium_claim'])
        self.assertLessEqual(certificate['max_own_deviation_gain'], 1e-8)
        # Verify all pure contingent unilateral policies independently, without
        # the solver's BR implementation or complementarity residual.
        tree.policy = p
        baseline = tree.evaluate()[0]
        for kind in (0, 1):
            for signal in (0, 1):
                payoff = sum(p[1 if signal == 0 else 4][a, kind]
                             * tree.entries[(2, 3)[a] if signal == 0 else (5, 6)[a]].payoff[kind, 0]
                             for a in (0, 1))
                self.assertLessEqual(payoff - baseline[kind, 0], 1e-8)
        for left in (0, 1):
            for right in (0, 1):
                payoff = sum(tree.world_weights[k] * (
                    p[0][0, k] * tree.entries[(2, 3)[left]].payoff[k, 1]
                    + p[0][1, k] * tree.entries[(5, 6)[right]].payoff[k, 1])
                    for k in (0, 1))
                self.assertLessEqual(payoff - np.dot(tree.world_weights, baseline[:, 1]), 1e-8)

    def test_compressed_residual_matches_full_tree(self):
        tree = signaling_tree()
        cells = {(0, 0), (0, 1), (1, 0), (4, 0)}
        compressed = _JointResidual(tree, cells)
        x = compressed.x0.copy()
        for _, _, start, _ in compressed.offsets:
            x[start:start+2] = [.3, .7]
        tree.policy = compressed.unpack(x)
        values = tree.evaluate()
        direct = []
        for i, ids, start, actions in compressed.offsets:
            actor = tree.entries[i].actor
            reach = tree.world_weights[ids].copy()
            for parent, action in compressed.paths[i]:
                reach *= tree.policy[parent][action, ids]
            if reach.sum() == 0:
                reach = tree.world_weights[ids]
            own = np.array([np.average(values[c][ids, actor], weights=reach)
                            for c in tree.entries[i].children])
            p = x[start:start+actions]
            gap = x[start+actions] - own
            direct.extend(np.hypot(p, gap)-p-gap)
            direct.append(p.sum()-1)
        np.testing.assert_allclose(compressed.residual(x), direct, atol=1e-12)

    def test_restricted_support_keeps_full_game_and_expands_profitable_action(self):
        tree = signaling_tree()
        cells = {(0, 0), (0, 1), (1, 0), (4, 0)}
        supports = {(0, 0): (0,), (0, 1): (0,), (1, 0): (1,), (4, 0): (1,)}
        original_branches = [(entry.actions, entry.children) for entry in tree.entries]
        restricted = _JointResidual(tree, cells, action_supports=supports)
        full = _JointResidual(tree, cells)
        self.assertEqual(len(restricted.x0), 8)
        self.assertEqual(len(full.x0), 12)
        tree.policy = restricted.normalized_policy(restricted.x0)
        self.assertIsNone(certify_policy(tree))
        # Restricted candidates omit R for the bad sender. Independent full
        # native action values find its profitable R deviation and expand it.
        additions, count = _expand_profitable_supports(tree, cells, supports, 1e-8)
        self.assertIn((0, 1), additions)
        self.assertEqual(supports[0, 1], (0, 1))
        self.assertGreaterEqual(count, 1)
        self.assertEqual(original_branches,
                         [(entry.actions, entry.children) for entry in tree.entries])
        self.assertEqual(tree.policy[0][1, 1], 0.)

    def test_uncertified_cycle_fails_closed(self):
        tree = signaling_tree()
        before = [None if p is None else p.copy() for p in tree.policy]
        with self.assertRaises(SearchLimit):
            solve_equilibrium(tree, max_sweeps=12, max_joint_cells=0)
        self.assertIsNone(tree.certificate)
        self.assertIsNone(tree.values)
        for p, q in zip(tree.policy, before):
            if p is not None:
                np.testing.assert_array_equal(p, q)

    def test_time_budget_is_honored(self):
        tree = signaling_tree()
        tree.equilibrium_audit = {'stale_from_previous_attempt': True}
        def exhausted():
            raise SearchLimit('Teacher wall budget exceeded')
        tree._check = exhausted
        with self.assertRaisesRegex(SearchLimit, 'wall budget'):
            solve_equilibrium(tree)
        self.assertIsNone(tree.certificate)
        self.assertIsNone(tree.equilibrium_audit)

    def test_rejects_private_leak_and_profitable_deviation(self):
        tree = signaling_tree()
        tree.policy[1][:, 0] = [1., 0.]
        with self.assertRaisesRegex(SearchLimit, 'private information'):
            certify_policy(tree)
        tree = signaling_tree()
        self.assertIsNone(certify_policy(tree))

    def test_nonfinite_payoffs_and_best_response_fail_closed(self):
        for bad in (np.nan, np.inf, -np.inf):
            tree = signaling_tree()
            tree.entries[2].payoff[0, 0] = bad
            with self.assertRaisesRegex(SearchLimit, 'nonfinite'):
                certify_policy(tree)
        tree = signaling_tree()
        tree.response = lambda player: ({}, np.full((2, 2), np.nan))
        with self.assertRaisesRegex(SearchLimit, 'nonfinite best response'):
            certify_policy(tree)
        for bad in (np.nan, np.inf, -1., 0.):
            with self.assertRaises(ValueError):
                certify_policy(signaling_tree(), epsilon=bad)

    def test_root_nash_does_not_accept_off_path_suboptimal_threat(self):
        tree = off_path_tree()
        # Independent root Nash check finds no gain: the bad response is on
        # an unreachable branch and the sender prefers its certain L payoff.
        baseline = tree.evaluate()[0]
        for player in (0, 1):
            _, best = tree.response(player)
            self.assertAlmostEqual(best[0, player]-baseline[0, player], 0.)
        self.assertIsNone(certify_policy(tree))
        result = solve_equilibrium(tree)
        self.assertTrue(result['certificate']['local_own_support_verified'])
        self.assertEqual(result['policy'][2][1, 0], 1.)

    def test_response_social_tie_audited_separately(self):
        tree = off_path_tree(response_tie=True)
        self.assertIsNone(certify_policy(tree))
        own_only = certify_policy(tree, require_social_ties=False)
        self.assertTrue(own_only['certificate']['own_utility_epsilon_nash_verified'])
        self.assertFalse(own_only['certificate']['response_only_social_ties_verified'])
        result = solve_equilibrium(tree)
        self.assertTrue(result['certificate']['response_only_social_ties_verified'])
        self.assertEqual(result['policy'][2][1, 0], 1.)

    def test_ordered_candidate_is_recertified_and_records_selection(self):
        tree = off_path_tree()
        result = solve_equilibrium(tree, max_sweeps=1, max_ordered_sweeps=1)
        certificate = result['certificate']
        self.assertEqual(certificate['candidate_method'],
                         'ordered-complete-contingent-best-response')
        self.assertEqual(certificate['initialization'], 'uniform')
        self.assertEqual(certificate['update_order'], [0, 1])
        self.assertTrue(certificate['local_own_support_verified'])
        self.assertLessEqual(certificate['max_own_deviation_gain'], 1e-8)

    def test_three_player_bayesian_profile_checks_every_player(self):
        # The third player is a dummy, so this isolates the n-player API and
        # certificate checks; it is not evidence of native three-player yield.
        tree = signaling_tree()
        tree.n = 3
        tree.worlds = tuple(world + ((0,),) for world in tree.worlds)
        tree.groups[2] = [np.array([0, 1])]
        tree.entries = [entry if entry.actor is not None else
                        entry._replace(payoff=np.pad(entry.payoff, ((0, 0), (0, 1))))
                        for entry in tree.entries]
        result = solve_equilibrium(tree)
        self.assertEqual({r['player'] for r in result['certificate'][
            'root_private_information_deviation_checks']}, {0, 1, 2})
        self.assertTrue(result['certificate']['local_own_support_verified'])
        self.assertAlmostEqual(result['policy'][0][0, 1], .5, places=6)
        self.assertAlmostEqual(result['policy'][1][0, 0], .25, places=6)

    def test_own_mixed_equilibrium_cannot_silently_drop_social_tie(self):
        tree = signaling_tree()
        tree.policy[0] = np.array([[1., .5], [0., .5]])
        tree.policy[1] = np.array([[.25, .25], [.75, .75]])
        tree.policy[4] = np.array([[0., 0.], [1., 1.]])
        response_actions = ({'response': 'ACCEPT'}, {'response': 'REJECT'})
        for index in (1, 4):
            tree.entries[index] = tree.entries[index]._replace(actions=response_actions)
        self.assertIsNone(certify_policy(tree))
        own_only = certify_policy(tree, require_social_ties=False)
        self.assertIsNotNone(own_only)
        self.assertTrue(own_only['certificate']['own_utility_epsilon_nash_verified'])
        self.assertFalse(own_only['certificate']['response_only_social_ties_verified'])

    def test_candidate_stage_budget_leaves_time_for_joint_and_full_audit(self):
        tree = signaling_tree()
        clock = [0.]
        tree.deadline = 100.
        original_response = tree.response
        def timed_response(player):
            result = original_response(player)
            clock[0] += 5.
            return result
        tree.response = timed_response
        entered_joint = []
        class InstrumentedResidual(_JointResidual):
            def __init__(self, *args, **kwargs):
                entered_joint.append(clock[0])
                super().__init__(*args, **kwargs)
        with patch.object(equilibrium_module.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(equilibrium_module, '_JointResidual', InstrumentedResidual), \
                patch.object(equilibrium_module, 'certify_policy', wraps=certify_policy) as final_audit:
            result = solve_equilibrium(tree)
        self.assertTrue(entered_joint)
        self.assertLessEqual(entered_joint[0], 50.)
        self.assertGreaterEqual(final_audit.call_count, 1)
        certificate = result['certificate']
        self.assertTrue(certificate['independent_final_certification'])
        self.assertTrue(certificate['local_own_support_verified'])
        self.assertTrue(certificate['response_only_social_ties_verified'])
        self.assertLessEqual(certificate['max_own_deviation_gain'], 1e-8)
        self.assertEqual(certificate['candidate_method'], 'joint-behavioral-complementarity')

    def test_root_screening_cannot_bypass_independent_final_audit(self):
        tree = off_path_tree()
        with patch.object(equilibrium_module, 'certify_policy',
                          side_effect=SearchLimit('Independent final private/local audit rejected')) as final_audit:
            with self.assertRaisesRegex(SearchLimit, 'Independent final'):
                solve_equilibrium(tree)
        self.assertGreaterEqual(final_audit.call_count, 1)
        self.assertIsNone(tree.certificate)
        self.assertIsNone(tree.values)


if __name__ == '__main__':
    unittest.main()
