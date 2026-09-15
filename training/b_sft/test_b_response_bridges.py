"""Behavioral learning targets, including shortcuts the paired lessons reject."""
from copy import deepcopy
import json
import unittest

from training.b_sft.build_b_response_bridges import build_tasks, verify_task
from training.b_sft.social_bp_training import native_completion, reward


class ResponseBridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tasks = build_tasks()

    def find(self, lesson, response, skill='update', relation='target'):
        return next(t for t in self.tasks if t['b_lesson'] == lesson and t['skill'] == skill
                    and t['evidence_relation'] == relation
                    and t['input']['voluntary_history'][0]['response'] == response)

    def answer(self, task, gold):
        completion = native_completion(task)
        fn = completion['raw_message']['tool_calls'][0]['function']
        args = json.loads(fn['arguments'])
        args['judgments'][0].update(gold)
        fn['arguments'] = json.dumps(args)
        return reward(task, completion)['reward']

    def test_all_labels_reconstruct_without_hidden_catalogue(self):
        for task in self.tasks:
            with self.subTest(task=task['id']):
                verify_task(task)

    def test_prior_and_behavior_both_needed(self):
        t = self.find('binary', 'REJECT')
        self.assertEqual(t['input']['previous_belief']['possible_preferences'], ['want', 'avoid'])
        self.assertEqual(t['teacher']['gold']['possible_preferences'], ['avoid'])
        self.assertEqual(self.answer(t, t['input']['previous_belief']), 0)
        self.assertEqual(self.answer(t, dict(possible_preferences=['neutral', 'avoid'], favored='undetermined')), 0)

    def test_other_player_goal_changes_neutral_response(self):
        help_other = self.find('altruistic', 'ACCEPT')
        hurt_other = self.find('conflict', 'ACCEPT')
        self.assertEqual(help_other['teacher']['gold']['possible_preferences'], ['want', 'neutral'])
        self.assertEqual(hurt_other['teacher']['gold']['possible_preferences'], ['want'])
        self.assertEqual(help_other['contrast_group'], hurt_other['contrast_group'])
        self.assertEqual(self.answer(hurt_other, help_other['teacher']['gold']), 0)

    def test_full_set_and_carry_forward_have_counterexamples(self):
        unchanged = self.find('altruistic', 'ACCEPT', skill='maintain', relation='unrelated')
        changed = self.find('altruistic', 'ACCEPT')
        full = dict(possible_preferences=['want', 'neutral', 'avoid'], favored='undetermined')
        self.assertEqual(self.answer(unchanged, full), 1)
        self.assertEqual(self.answer(changed, full), 0)

    def test_favored_does_not_require_eliminating_all_alternatives(self):
        t = self.find('favored', 'ACCEPT')
        c = t['teacher']['response_certificate']
        self.assertEqual(c['posterior'], dict(want='2/3', neutral='1/3', avoid='0'))
        self.assertEqual(c['gold'], dict(possible_preferences=['want', 'neutral'], favored='want'))
        self.assertEqual(self.answer(t, dict(possible_preferences=['want'], favored='want')), 0)
        self.assertEqual(self.answer(t, dict(possible_preferences=['want', 'neutral'], favored='undetermined')), 0)

    def test_coupled_rewards_are_added_and_maintenance_is_exact_output(self):
        rejected = self.find('net_payoff', 'REJECT')
        accepted = self.find('net_payoff', 'ACCEPT', skill='maintain')
        self.assertEqual(rejected['teacher']['gold']['possible_preferences'], ['avoid'])
        # Weights change, but neither the possible set nor favored changes.
        self.assertEqual(accepted['teacher']['response_certificate']['posterior'],
                         dict(want='2/5', neutral='2/5', avoid='1/5'))
        self.assertEqual(accepted['input']['previous_belief'], accepted['teacher']['gold'])

    def test_bad_labels_and_prior_fail_independent_verification(self):
        t = deepcopy(self.find('binary', 'REJECT'))
        t['teacher']['gold']['favored'] = 'want'
        with self.assertRaises(AssertionError):
            verify_task(t)
        t = deepcopy(self.find('binary', 'REJECT'))
        t['input']['previous_belief']['possible_preferences'] = ['want', 'neutral', 'avoid']
        with self.assertRaises(AssertionError):
            verify_task(t)

    def test_same_set_favored_can_appear_or_disappear(self):
        gone = self.find('favored_disappears', 'ACCEPT', relation='joint_constraint')
        new = self.find('favored_appears', 'ACCEPT')
        for task in (gone, new):
            self.assertEqual(task['input']['previous_belief']['possible_preferences'],
                             task['teacher']['gold']['possible_preferences'])
            self.assertNotEqual(task['input']['previous_belief']['favored'],
                                task['teacher']['gold']['favored'])
            self.assertEqual(self.answer(task, task['input']['previous_belief']), 0)
        self.assertEqual(gone['teacher']['gold']['favored'], 'undetermined')
        self.assertEqual(new['teacher']['gold']['favored'], 'want')


if __name__ == '__main__':
    unittest.main()
