import json
import unittest

from experiment import (audit_cases, b_request, load, p_request, run_case,
                        summarize, _strip_judgment_prompt)
from new.diagnostic_v5.experiment import parse_b
from training.b_sft.social_bp_training import native_completion
from training.b_sft.social_named_probe import Names


def belief_completion(case, judgment):
    query = case['task']['input']['queries'][0]
    names = Names(case['task']['input'], 0)
    item = dict(player=names.players[query['player']],
                goal=names.goals[query['goal']], **judgment)
    return dict(finish_reason='stop', raw_message=dict(tool_calls=[dict(
        function=dict(name='SUBMIT_BELIEFS',
                      arguments=json.dumps({'judgments': [item]}))) ]))


class CleanPlanningSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.cases = load()

    def test_inventory_and_strong_invariants(self):
        report = audit_cases(self.cases)
        self.assertEqual(report['structures'], 16)
        self.assertTrue(report['controlled_P_history_free'])
        self.assertTrue(report['controlled_P_pair_base_byte_identical'])
        self.assertTrue(report['end_to_end_history_retained'])
        self.assertTrue(report['all_semantic_regions_decision_sufficient'])
        self.assertTrue(report['invariant_semantic_optimal_actions_disjoint'])
        self.assertEqual(sum(case['mode'] == 'binary'
                             for case in self.cases), 16)
        self.assertEqual(sum(case['planning_assisted_B']
                             for case in self.cases), 8)

    def test_controlled_p_has_state_but_no_behavioral_evidence(self):
        forbidden = ('EVENTS IN ORDER', 'Observed player choice',
                     'Preset event', 'voluntary', 'imposed setup',
                     'displayed history')
        required = ('CURRENT BINDING STATE', 'KNOWN PREFERENCES',
                    'GOAL REQUIREMENTS BY PLAYER',
                    'Investigation uses remaining')
        for case in self.cases:
            text = case['requests']['P_clean']['messages'][1]['content']
            for token in forbidden:
                self.assertNotIn(token.lower(), text.lower())
            for token in required:
                self.assertIn(token, text)

    def test_pair_base_requests_are_exactly_equal(self):
        grouped = {}
        for case in self.cases:
            grouped.setdefault(case['structure_id'], []).append(case)
        for pair in grouped.values():
            self.assertEqual(pair[0]['requests']['P_clean'],
                             pair[1]['requests']['P_clean'])

    def test_judgment_is_only_controlled_p_difference(self):
        for case in self.cases:
            gold = case['gold_judgment']
            alternative = {'possible_preferences': ['want'],
                           'favored': 'want'}
            if alternative == gold:
                alternative = {'possible_preferences': ['avoid'],
                               'favored': 'avoid'}
            first = p_request(case, gold)
            second = p_request(case, alternative)
            self.assertEqual(_strip_judgment_prompt(first),
                             _strip_judgment_prompt(second))
            self.assertEqual(_strip_judgment_prompt(first),
                             case['requests']['P_clean'])

    def test_end_to_end_still_receives_history(self):
        for case in self.cases:
            text = case['requests']['P_infer']['messages'][1]['content']
            self.assertIn('EVENTS IN ORDER', text)

    def test_native_b_round_trip(self):
        for case in self.cases:
            value, status = parse_b(
                case, belief_completion(case, case['gold_judgment']))
            self.assertEqual(status, 'ok')
            self.assertEqual(value, case['gold_judgment'])

    def test_every_semantic_summary_has_one_invariant_optimal_set(self):
        for case in self.cases:
            certificate = case['semantic_decision_certificate']
            self.assertTrue(certificate['decision_sufficient'])
            self.assertEqual(len(certificate[
                'distinct_vertex_optimal_action_sets']), 1)
            self.assertIsNotNone(certificate[
                'invariant_optimal_action_indices'])

    def test_requests_never_expose_numeric_posterior(self):
        for case in self.cases:
            requests = [b_request(case),
                        p_request(case, case['gold_judgment'])]
            if case['planning_assisted_B']:
                requests.append(b_request(case, assisted=True))
            text = json.dumps(requests)
            for forbidden in ('joint_distribution', 'preference_weights',
                              'SUBMIT_DISTRIBUTION', 'want=', 'neutral=',
                              'avoid='):
                self.assertNotIn(forbidden, text)

    def test_gold_semantic_pipeline(self):
        for case in self.cases[:4]:
            def call(condition, request):
                if condition in ('B', 'B_with_qualitative_partner_plan'):
                    return belief_completion(case, case['gold_judgment'])
                return native_completion(case['task'])
            row = run_case(case, call)
            self.assertTrue(row['B']['exact'])
            self.assertTrue(row['controlled_P_history_free'])
            self.assertIsNotNone(row['correct_B_model_P']['utility'])
            self.assertIsNotNone(row['model_B_model_P']['utility'])

    def test_invalid_b_blocks_only_model_b_planning(self):
        case = self.cases[0]

        def call(condition, request):
            if condition == 'B':
                return {'finish_reason': 'length'}
            return native_completion(case['task'])

        row = run_case(case, call)
        self.assertIsNone(row['model_B_model_P']['utility'])
        self.assertIsNotNone(row['correct_B_model_P']['utility'])
        self.assertIsNotNone(row['end_to_end_P']['utility'])

    def test_summary_records_clean_interpretation(self):
        case = self.cases[0]

        def call(condition, request):
            if condition in ('B', 'B_with_qualitative_partner_plan'):
                return belief_completion(case, case['gold_judgment'])
            return native_completion(case['task'])

        row = dict(run_case(case, call), replica=0)
        summary = summarize([row], self.cases, 3)
        self.assertEqual(summary['planned_rows'], 96)
        self.assertIn('sufficient deployed B interface',
                      summary['interpretation'])
        identity = summary['paired_scoring_identity']
        self.assertEqual(identity['row_identity_failures'], 0)
        self.assertAlmostEqual(identity['aggregate_identity_residual'], 0.)


if __name__ == '__main__':
    unittest.main()
