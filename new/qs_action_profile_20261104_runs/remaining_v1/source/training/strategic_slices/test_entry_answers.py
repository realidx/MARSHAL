"""Analytic information-value and oracle-reach regression checks."""
from types import SimpleNamespace as NS
from collections import Counter, defaultdict
import unittest
from unittest.mock import patch

import numpy as np

from .entry_answers import action_information_value, measure_entry_answers


class EntryAnswerTests(unittest.TestCase):
    def test_opposite_actions_have_information_value(self):
        result = action_information_value([[1, 0], [0, 1]], [.25, .75])
        self.assertAlmostEqual(result['S'], .25)
        self.assertEqual(result['must_change_pairs'], [[0, 1]])

    def test_different_exact_optima_need_not_be_epsilon_must_change(self):
        result = action_information_value([[.05, 0], [0, .05]], [.5, .5])
        self.assertEqual(result['must_change_pairs'], [])
        self.assertAlmostEqual(result['S'], .025)

    def test_common_optimum_is_an_information_invariant_control(self):
        result = action_information_value([[2, 1, 0], [2, 0, 1]], [.4, .6])
        self.assertEqual(result['S'], 0)
        self.assertEqual(result['must_change_pairs'], [])

    def test_reach_posterior_not_balanced_answers(self):
        action = NS(to_dict=lambda: {'action': 'PASS'})
        def entry(actor, turn, children):
            return NS(actor=actor, children=children, actions=[action]*len(children),
                      node=NS(state=NS(turn_index=turn), number=turn, pending=None))
        # The frozen prefix sends world 0 here with probability .2 and world 1
        # with probability .6. Their initial probabilities are both .5.
        entries = [entry(1, 0, [1, 4]), entry(0, 1, [2, 3]),
                   entry(None, 2, []), entry(None, 2, []), entry(None, 2, [])]
        payoff_a = np.array([[1., 0], [0., 0]])
        payoff_b = np.array([[0., 0], [1., 0]])
        tree = NS(entries=entries, rules=NS(spec=NS(round_robin=[1, 0])), w=2,
            worlds=[((1,), (-1,)), ((1,), (1,))], world_weights=np.array([.5, .5]),
            policy=[np.array([[.2, .6], [.8, .4]]), np.eye(2), None, None, None],
            evaluate=lambda: [np.zeros((2, 2)), np.zeros((2, 2)), payoff_a, payoff_b, np.zeros((2, 2))])
        with patch('training.strategic_slices.entry_answers.observed_slots',
                   side_effect=lambda node, ego: ((1, 0),) if node.number == 1 else ()):
            groups = measure_entry_answers(tree, 'test')
        self.assertEqual(len(groups), 1)
        group = groups[0]
        self.assertAlmostEqual(group['group_reach_probability'], .4)
        self.assertAlmostEqual(group['S'], .25)
        np.testing.assert_allclose([m['probability'] for m in group['members']], [.25, .75])
        self.assertEqual(group['members'][0]['world_weights'], [1., 0.])
        self.assertEqual(group['members'][1]['world_weights'], [0., 1.])
        self.assertEqual(group['members'][0]['history'], [0])

    def test_selection_keeps_complete_pair_and_minimizes_replacements(self):
        from examples.strategic_slices.rebalance_candidates import select_parent
        def row(i):
            return dict(id=str(i), ego=0, k=1, decision_kind='proposal', entrance_id=str(i),
                        members=[dict(remaining_proposals=1, history=[i])],
                        entry_kind='oracle-reach-singleton', detectable_information_value=False)
        original = [row(i) for i in range(8)]
        additions = [row(i) for i in range(8, 10)]
        kept, _ = select_parent(original+additions, 2, defaultdict(Counter),
                                required_ids={'8', '9'}, existing_ids={r['id'] for r in original})
        self.assertEqual(len(kept), 8)
        self.assertTrue({'8', '9'} <= {r['id'] for r in kept})
        self.assertEqual(sum(int(r['id']) < 8 for r in kept), 6)
        with self.assertRaisesRegex(ValueError, 'Required contrast member'):
            select_parent(original, 2, defaultdict(Counter), required_ids={'missing'})


if __name__ == '__main__':
    unittest.main()
