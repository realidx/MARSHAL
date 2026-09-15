from copy import deepcopy
import unittest

from training.b_sft.social_cases_expand import (
    information_fixture, information_audit, compensated_fixture, solve_conditioned,
    second_long_route, annotated_records, select_case,
)
from training.b_sft.shared_teacher import native
from training.b_sft.social_cases import verify_conditioned
from benac_p.endgame_diagnose import decode_action


class ExpandedCasesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = {mode: solve_conditioned(*information_fixture(mode))
                     for mode in ('two_types', 'independent', 'multi_partner', 'wait_for_better')}

    def test_useful_attempt_and_rejection_fallback(self):
        c = self.cases['two_types']; audit = information_audit(c)
        self.assertEqual(audit['probe_terminal_value'], 1.5)
        self.assertEqual(audit['best_other_first_action_value'], 1)
        self.assertEqual([e['utilities'][0] for e in c['episodes']], [2, 1])
        for e in c['episodes']:
            self.assertEqual(e['records'][1]['evidence_after_action']['exclusion_reasons']['strict_self_value'], 1)
            self.assertEqual(e['records'][1]['evidence_after_action']['exclusion_reasons']['residual_native_order'], 0)
        rejection = next(b for b in audit['branches'] if b['response'] == {'response': 'REJECT'})
        self.assertEqual(rejection['next_ego_decision']['action'], {'response': 'ACCEPT'})
        self.assertTrue(all(b['answer']['possible_preferences'] == ['avoid']
                            for b in rejection['next_ego_decision']['B']))

    def test_more_hidden_dimensions_retain_valid_premium(self):
        for mode, n in [('independent', 9), ('multi_partner', 27)]:
            c = self.cases[mode]; self.assertEqual(len(c['episodes']), n)
            self.assertGreater(information_audit(c)['policy_contingent_premium'], 0)
        q = self.cases['multi_partner']['episodes'][0]['records'][0]['B']
        self.assertEqual({(b['player'], b['goal']) for b in q}, {(1, 0), (1, 1), (2, 0)})

    def test_accepting_bundle_does_not_identify_target_preference(self):
        c = solve_conditioned(*compensated_fixture(), turns=2)
        for e in c['episodes']:
            self.assertEqual(e['records'][0]['P']['selected'], {'response': 'ACCEPT'})
            later = e['records'][1]
            self.assertEqual(later['input']['player'], 0)
            self.assertEqual(later['B'][0]['answer']['possible_preferences'], ['want', 'neutral', 'avoid'])

    def test_reject_positive_immediate_payoff_for_better_future(self):
        c = self.cases['wait_for_better']; e = c['episodes'][0]
        r, _, _ = native(c['fixture']); node = r.initial()
        for a in c['prefix']: node = r._apply(node, decode_action(a))
        before = node.state.goal_satisfaction()
        after = r._apply(node, decode_action({'response': 'ACCEPT'})).state.goal_satisfaction()
        own = e['environment_world'][1]
        delta = sum(w*(a-b) for w, a, b in zip(own, after, before))
        self.assertEqual(delta, 2)
        label = e['records'][0]['P']
        self.assertEqual(label['selected'], {'response': 'REJECT'})
        self.assertGreater(label['actions'][0]['own'], label['actions'][1]['own'])

    def test_audit_catches_corrupt_more_complex_b(self):
        c = self.cases['multi_partner']; bad = deepcopy(c['episodes'])
        bad[0]['records'][0]['B'][0]['answer']['favored'] = 'avoid'
        with self.assertRaises(ValueError): verify_conditioned(c['fixture'], c['prefix'], bad)

    def test_selection_preserves_self_chosen_targets_and_tie_masks(self):
        c = self.cases['multi_partner']; rs, ps = annotated_records(c, c['fixture']['id'], 'information')
        keep = select_case(rs, ps, 20)
        self.assertEqual(len(keep), 20)
        self.assertTrue(all('queries' not in r['input'] for r in keep))
        for r in keep:
            if r['teacher']['residual_order_evidence_in_prefix']:
                self.assertFalse(r['teacher']['B_aux_mask'])
        self.assertTrue(any(len(r['teacher']['B_by_target']) == 3 for r in keep))

    def test_second_long_route_substantive_delay_and_capacity(self):
        c = second_long_route()
        values = [r['own_utility'] for r in c['timeline'] if 'response' in r['action']]
        self.assertEqual(values, [-1, -1, -1, -1, 2])
        self.assertEqual(c['audit']['first_two_passes_terminal_upper_bound'], 1)
        self.assertEqual(c['audit']['terminal_utilities'], c['audit']['static_utility_upper_bounds'])
        self.assertFalse(c['B_supervision']); self.assertFalse(c['P_action_ranking_supervision'])


if __name__ == '__main__': unittest.main()
