"""Generation controls must preserve frozen seeds and the paired intervention."""
from copy import deepcopy
import unittest

from examples.strategic_slices.calibrate_goal_structure import summarize
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from .build import sample_parent, with_multi_action_goal
from .common import digest


class GoalStructureTests(unittest.TestCase):
    def test_legacy_seed_identities_are_unchanged(self):
        expected = [((15, 3, 1), 'e8ad981cd68544a95731fcc8adbc11fdaeb44a31fed44951b22de270b0d5365a'),
            ((2026100703, 2, 1), 'e7322a26002a32d1653a42076cd1b7c3ea7653d348db05945424efda9c7ce20d'),
            ((2026101100, 2, 2), '41cf2774415177278e634cb7261fc93033553ea84677a121aa3b1f434585b3d4')]
        for args, identity in expected:
            self.assertEqual(digest(sample_parent(*args)), identity)
            self.assertEqual(digest(sample_parent(*args, goal_structure='legacy')), identity)

    def test_native_pairs_change_exactly_one_requirement(self):
        changed = 0
        for seed in range(24):
            old = sample_parent(seed, 3, rounds=1)
            untouched = deepcopy(old)
            new, change = with_multi_action_goal(old, seed)
            self.assertEqual(old, untouched)
            self.assertEqual(new, sample_parent(seed, 3, rounds=1, goal_structure='multi_action'))
            self.assertEqual(PrivateInvestigationRules(old).worlds, PrivateInvestigationRules(new).worlds)
            if change is None:
                self.assertEqual(new, old)
                continue
            changed += 1
            goal = next(g for g in new['game']['goals'] if g['goal_id'] == change['goal_id'])
            added = change['added_requirement']
            self.assertGreaterEqual(sum(a['player_id']==added['player_id'] for a in goal['required_actions']), 2)
            goal['required_actions'].remove(added)
            self.assertEqual(new, old)
        self.assertGreater(changed, 0)
        self.assertLess(changed, 24)  # A no-eligible structure is not a new parent.

    def test_failed_pair_does_not_become_a_zero_information_observation(self):
        pairs = [dict(seed=1, change={}, names=dict(legacy='a', multi_action='b'))]
        results = [dict(name='a', arm='legacy', status='certified', max_measured_S=.2,
                        strong_witnesses=1, family='f1'),
                   dict(name='b', arm='multi_action', status='failed', family='f2')]
        summary = summarize(pairs, results)
        self.assertFalse(summary['pairs'][0]['both_certified'])
        self.assertIsNone(summary['pairs'][0]['S_difference'])
        self.assertEqual(summary['arms']['multi_action']['certified'], 0)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            sample_parent(0, 3, goal_structure='typo')


if __name__ == '__main__':
    unittest.main()
