import json
import unittest

from experiment import (audit_cases, b_request, load, parse_b, p_request,
                        reference, run_case, summarize, total_variation, values)
from build import occupied_geometries
from training.b_sft.social_bp_training import native_completion


def belief_completion(belief):
    return dict(finish_reason='stop', raw_message=dict(tool_calls=[dict(function=dict(
        name='SUBMIT_DISTRIBUTION', arguments=json.dumps(dict(zip(
        ('want', 'neutral', 'avoid'), belief)))))]))


def run_gap(case):
    scores = values(case, case['gold_belief'])
    lower = [value for value in scores if max(scores) - value > 1e-9]
    return max(scores) - max(lower)


class FrozenSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest, cls.cases = load()

    def test_structure_inventory_and_invariants(self):
        report = audit_cases(self.cases)
        self.assertEqual(report['structures'], 16)
        self.assertEqual(len(self.cases), 32)
        self.assertEqual(sum(case['mode'] == 'binary' for case in self.cases), 16)
        self.assertEqual(sum(case['planning_assisted_B'] for case in self.cases), 8)

    def test_no_geometry_overlap_with_protected_data(self):
        protected, _ = occupied_geometries()
        selected = {case['structure_family'] for case in self.cases}
        self.assertFalse(selected & protected)

    def test_every_pair_has_a_material_decision_switch(self):
        grouped = {}
        for case in self.cases:
            grouped.setdefault(case['structure_id'], []).append(case)
        for pair in grouped.values():
            voluntary = next(case for case in pair if case['provenance'] == 'voluntary')
            preset = next(case for case in pair if case['provenance'] == 'preset')
            self.assertFalse(set(reference(voluntary, voluntary['gold_belief'])['action_indices']) &
                             set(reference(preset, preset['gold_belief'])['action_indices']))
            self.assertGreaterEqual(min(
                run_gap(voluntary), run_gap(preset)), .15 - 1e-9)

    def test_gold_belief_round_trip(self):
        for case in self.cases:
            def call(condition, request):
                if condition in ('B', 'B_with_planning_assistance'):
                    return belief_completion(case['gold_belief'])
                return native_completion(case['task'])
            row = run_case(case, call)
            self.assertAlmostEqual(row['B_total_variation'], 0.)
            self.assertLessEqual(row['cells']['correct_B_model_P']['regret'], .1 + 1e-9)
            self.assertTrue(row['four_cells_complete'])

    def test_invalid_b_blocks_only_dependent_cells(self):
        case = self.cases[0]
        def call(condition, request):
            if condition == 'B':
                return {'finish_reason': 'length'}
            return native_completion(case['task'])
        row = run_case(case, call)
        self.assertIsNone(row['cells']['model_B_model_P']['utility'])
        self.assertIsNotNone(row['cells']['correct_B_model_P']['utility'])
        self.assertIsNotNone(row['end_to_end_P']['utility'])

    def test_controlled_p_hides_evidence_and_source(self):
        for case in self.cases:
            text = p_request(case, [1/3] * 3)['messages'][1]['content']
            self.assertNotIn('EVENTS IN ORDER', text)
            self.assertNotIn('CORRECT CURRENT BELIEF', text)
            self.assertNotIn(case['id'], text)
            self.assertNotIn(case['structure_id'], text)
            self.assertIn('CURRENT BINDING STATE', text)
            visible_b = json.dumps(b_request(case))
            for secret in ('per_world_payoffs', 'preference_weights', 'structure_family'):
                self.assertNotIn(secret, visible_b)

    def test_assistance_is_likelihood_not_answer_hint(self):
        case = next(case for case in self.cases if case['planning_assisted_B'])
        plain = b_request(case)['messages'][1]['content']
        helped = b_request(case, assisted=True)['messages'][1]['content']
        self.assertNotIn('VERIFIED PARTNER-PLANNING ASSISTANCE', plain)
        self.assertIn('These are likelihoods, not posterior probabilities', helped)
        prior = next(other['gold_belief'] for other in self.cases
                     if other['structure_id'] == case['structure_id'] and other['provenance'] == 'preset')
        implied = [x*y for x, y in zip(prior, case['likelihood_by_preference'])]
        implied = [x/sum(implied) for x in implied]
        self.assertLess(total_variation(implied, case['gold_belief']), 1e-9)

    def test_probability_contract_rejects_invalid_sum(self):
        completion = belief_completion([1., 1., 0.])
        self.assertEqual(parse_b(completion), (None, 'format_failure'))

    def test_structure_level_summary(self):
        case = self.cases[0]
        def call(condition, request):
            if condition in ('B', 'B_with_planning_assistance'):
                return belief_completion(case['gold_belief'])
            return native_completion(case['task'])
        row = dict(run_case(case, call), replica=0)
        summary = summarize([row], self.cases, 3)
        self.assertEqual(summary['planned_rows'], 96)
        self.assertEqual(summary['structure_level']['B_total_variation']['valid'], 1)
        self.assertEqual(summary['missing_rows'], 95)


if __name__ == '__main__':
    unittest.main()
