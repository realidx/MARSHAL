from copy import deepcopy
import unittest

from training.b_sft.social_cases import (
    b_input, p_input, collect, construct_bundle, long_horizon_case, verify_conditioned,
)


class SocialCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = construct_bundle()
        cls.deadline = construct_bundle(True)

    def test_refusal_retains_all_types_and_revised_offer_is_uncertain(self):
        episodes = self.bundle['episodes']
        for e in episodes:
            self.assertEqual(e['records'][0]['P']['selected'], {'response': 'REJECT'})
            first = e['records'][0]['P']
            reject, accept = first['actions']
            self.assertGreater(reject['own'], accept['own'])
            observer = e['records'][1]
            self.assertEqual(observer['input']['player'], 0)
            self.assertEqual(observer['B'][0]['answer'], dict(
                possible_preferences=['want', 'neutral', 'avoid'], favored='undetermined'))
        self.assertEqual([e['utilities'][0] for e in episodes], [1, 1, 0])
        self.assertEqual(self.bundle['verification']['certificate']['nodes'], 29)

    def test_deadline_probe_has_no_information_and_real_opportunity_cost(self):
        comparison = self.deadline['verification']['nominated_action_comparison']
        self.assertEqual(comparison['bundled']['observable_response_groups'], 1)
        self.assertEqual(comparison['clean']['observable_response_groups'], 2)
        self.assertEqual(comparison['bundled']['own_terminal_value'], 0)
        self.assertAlmostEqual(comparison['clean']['own_terminal_value'], 2/3)
        for e in self.deadline['episodes']:
            self.assertEqual(e['status'], 'terminal')

    def test_independent_audit_rejects_corrupt_b_and_p(self):
        for part in ('B', 'P'):
            bad = deepcopy(self.bundle['episodes'])
            r = bad[0]['records'][1]
            if part == 'B': r['B'][0]['answer']['possible_preferences'] = ['avoid']
            else:
                next(x for x in r['P']['actions'] if x['action'] == r['P']['selected'])['own'] += 1
            with self.assertRaises(ValueError):
                verify_conditioned(self.bundle['fixture'], self.bundle['prefix'], bad)

    def test_no_teacher_target_in_prompt_and_model_b_passes_unchanged(self):
        record = self.bundle['episodes'][0]['records'][1]
        inp = b_input(record['input'])
        self.assertNotIn('queries', inp)
        self.assertNotIn('B', inp)
        self.assertNotIn('P', inp)
        # Intentionally wrong answer must not be silently oracle-corrected.
        wrong = [{'player': 1, 'goal': 0, 'possible_preferences': ['avoid'], 'favored': 'avoid'}]
        planned = p_input(inp, wrong)
        self.assertEqual(planned['model_beliefs'], wrong)
        self.assertNotEqual(planned['model_beliefs'][0]['possible_preferences'],
                            record['B'][0]['answer']['possible_preferences'])
        self.assertIn('public_setup', inp)

    def test_duplicate_worlds_do_not_duplicate_decisions(self):
        records, pairs = collect(self.bundle['episodes'], 'test')
        observers = [r for r in records if r['input']['player'] == 0]
        self.assertEqual(len(observers), 1)
        self.assertEqual(pairs, [])  # Refusal maintain is a prior/posterior audit, not a fake same-actor pair.

    def test_long_horizon_cost_delay_and_pass_bound(self):
        case = long_horizon_case()
        self.assertEqual([r['own_utility'] for r in case['timeline'] if 'response' in r['action']],
                         [-1, -1, -1, 2])
        self.assertEqual(case['audit']['first_pass_terminal_upper_bound'], 1)
        self.assertEqual(case['audit']['terminal_utilities'], case['audit']['static_utility_upper_bounds'])
        self.assertFalse(case['B_supervision'])
        self.assertFalse(case['P_action_ranking_supervision'])


if __name__ == '__main__':
    unittest.main()
