import json
import unittest

from experiment import (audit_cases, b_request, load, parse_b, p_request,
                        run_case, summarize)
from training.b_sft.social_bp_training import native_completion
from training.b_sft.social_named_probe import Names


def belief_completion(case, judgment):
    query = case['task']['input']['queries'][0]
    names = Names(case['task']['input'], 0)
    item = dict(player=names.players[query['player']], goal=names.goals[query['goal']],
                **judgment)
    return dict(finish_reason='stop', raw_message=dict(tool_calls=[dict(
        function=dict(name='SUBMIT_BELIEFS',
                      arguments=json.dumps({'judgments': [item]}))) ]))


class NativeSemanticSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.cases = load()

    def test_inventory_and_invariants(self):
        report = audit_cases(self.cases)
        self.assertEqual(report['structures'], 16)
        self.assertTrue(report['no_numeric_belief_in_model_requests'])
        self.assertEqual(sum(c['mode'] == 'binary' for c in self.cases), 16)
        self.assertEqual(sum(c['planning_assisted_B'] for c in self.cases), 8)
        self.assertEqual(len({c['structure_family'] for c in self.cases}), 16)

    def test_native_b_round_trip(self):
        for case in self.cases:
            completion = belief_completion(case, case['gold_judgment'])
            value, status = parse_b(case, completion)
            self.assertEqual(status, 'ok')
            self.assertEqual(value, case['gold_judgment'])

    def test_singleton_requires_matching_favored(self):
        case = self.cases[0]
        invalid = {'possible_preferences': ['avoid'], 'favored': 'undetermined'}
        self.assertEqual(parse_b(case, belief_completion(case, invalid)),
                         (None, 'format_failure'))

    def test_requests_never_expose_numeric_belief(self):
        for case in self.cases:
            requests = [b_request(case),
                        p_request(case, case['gold_judgment'])]
            if case['planning_assisted_B']:
                requests.append(b_request(case, assisted=True))
            text = json.dumps(requests)
            for forbidden in ('joint_distribution', 'preference_weights',
                              'SUBMIT_DISTRIBUTION', 'want=', 'neutral=', 'avoid='):
                self.assertNotIn(forbidden, text)

    def test_gold_semantic_pipeline(self):
        for case in self.cases[:4]:
            def call(condition, request):
                if condition in ('B', 'B_with_qualitative_partner_plan'):
                    return belief_completion(case, case['gold_judgment'])
                return native_completion(case['task'])
            row = run_case(case, call)
            self.assertTrue(row['B']['exact'])
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

    def test_summary_uses_semantic_metrics(self):
        case = self.cases[0]
        def call(condition, request):
            if condition in ('B', 'B_with_qualitative_partner_plan'):
                return belief_completion(case, case['gold_judgment'])
            return native_completion(case['task'])
        row = dict(run_case(case, call), replica=0)
        summary = summarize([row], self.cases, 3)
        self.assertEqual(summary['planned_rows'], 96)
        self.assertEqual(summary['structure_level']['B_exact']['valid'], 1)
        self.assertNotIn('B_total_variation', summary['structure_level'])


if __name__ == '__main__':
    unittest.main()
