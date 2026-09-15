from copy import deepcopy
import unittest

import numpy as np

from training.b_sft.social_b_oracle import forward_fixture
from training.b_sft.social_terminal_teacher import (
    InvestigationRules, Investigate, TerminalEpisode, TerminalWindow,
)
from training.b_sft.debug.audit_social_semantics import rename, rename_action
from training.b_sft.debug.audit_social_design_iteration import small_information_fixture, investigation_use_audit
from benac_p.endgame_diagnose import decode_action


class TerminalTeacherTests(unittest.TestCase):
    def test_selected_teacher_is_reproducible_without_claiming_uniqueness(self):
        raw,prefix=forward_fixture()
        a=TerminalEpisode(raw,prefix)
        b=TerminalEpisode(raw,prefix)
        self.assertEqual(a.tree.certificate['policy_sha256'],b.tree.certificate['policy_sha256'])
        self.assertEqual(a.tree.certificate['label_reference'],'selected_contingent_policy')
        self.assertFalse(a.tree.certificate['uniqueness_required'])
        self.assertFalse(a.tree.certificate['diagnostic_policy'])
        self.assertGreater(a.tree.certificate['information_set_checks'],0)
        diagnostic=TerminalEpisode(raw,prefix,initialization='first')
        self.assertTrue(diagnostic.tree.certificate['diagnostic_policy'])

    def test_public_investigation_advantage_is_not_automatically_result_use(self):
        raw, prefix = small_information_fixture()
        e = TerminalEpisode(raw, prefix)
        row = e.choices(raw['own_preferences'])
        query = {'action': 'INVESTIGATE', 'player': 1, 'goal': 0}
        self.assertEqual(row['admissible_actions'], [query])
        audit = investigation_use_audit(e)[0]
        self.assertAlmostEqual(audit['learner_information_use_gain'], 0.)
        self.assertAlmostEqual(audit['learner_social_information_use_gain'], 0.)
        old_weights, old_index = e.weights.copy(), e.index
        with self.assertRaisesRegex(ValueError, 'revelation'):
            e.observe(query, revelation=0)
        np.testing.assert_array_equal(e.weights, old_weights)
        self.assertEqual(e.index, old_index)
        e.observe(query, revelation=-1)
        self.assertEqual(e.belief(1,0)['possible_preferences'], ['avoid'])
        self.assertEqual(e.tree.entries[e.index].node.state.public_state()['investigation_remaining'], 0)

    def test_complete_information_matches_independent_backward_induction(self):
        raw, prefix = forward_fixture()
        raw['type_catalogues']['1'] = [raw['type_catalogues']['1'][0]]
        e = TerminalEpisode(raw, prefix)
        tree = e.tree
        values = [None]*len(tree.entries)
        for i in reversed(range(len(tree.entries))):
            entry = tree.entries[i]
            if entry.actor is None:
                values[i] = entry.payoff[0]
                continue
            self.assertNotEqual(entry.actor, -1)
            av = np.array([values[c] for c in entry.children])
            own = av[:,entry.actor]
            others = av.sum(axis=1)-own
            best = np.flatnonzero(own == own.max())
            best = best[others[best] == others[best].max()]
            values[i] = av[best].mean(axis=0)
            expected = np.zeros(len(entry.actions));expected[best] = 1/len(best)
            np.testing.assert_allclose(expected, tree.policy[i][:,0])
            np.testing.assert_allclose(values[i], tree.values[i][0])

    def test_investigation_consumes_one_global_turn_and_reveals_only_one_slot(self):
        raw, _ = forward_fixture()
        rules = InvestigationRules(raw)
        root = rules.initial()
        self.assertEqual(root.state.public_state()['investigation_remaining'], 1)
        query = Investigate(1, 2)
        self.assertIn(query, rules.actions(root))
        before = root.state.snapshot_commitments()
        child = rules.reveal(root, query, 0)
        self.assertEqual(child.state.turn_index, 1)
        self.assertEqual(child.state.snapshot_commitments(), before)
        self.assertTrue(all(w[1][2] == 0 for w in child.worlds))
        self.assertFalse(any(isinstance(a, Investigate) for a in rules.actions(child)))
        self.assertEqual(child.state.public_state()['investigation_remaining'], 0)
        self.assertEqual(child.state.transcript[-1].to_dict()['revealed_preference'], 'neutral')
        self.assertEqual(root.state.turn_index, 0)
        with self.assertRaisesRegex(ValueError, 'Illegal'):
            rules.reveal(child, query, 0)
        with self.assertRaisesRegex(ValueError, 'Illegal'):
            rules.reveal(root, Investigate(0, 0), 1)
        with self.assertRaisesRegex(ValueError, 'explicit'):
            rules._apply(root, query)

    def test_menu_is_rejected_in_new_variant(self):
        raw, _ = forward_fixture()
        raw['game']['menu_enabled'] = True
        with self.assertRaisesRegex(ValueError, 'MENU'):
            InvestigationRules(raw)

    def test_terminal_opportunity_contrast_and_nonredundant_favored(self):
        raw, prefix = forward_fixture()
        raw['type_catalogues']['1'] = [raw['type_catalogues']['1'][i] for i in (0, 2)]
        e = TerminalEpisode(raw, prefix)
        self.assertEqual(e.choices(raw['type_catalogues']['1'][0])['admissible_actions'], [{'response': 'REJECT'}])
        e.observe({'response': 'REJECT'})
        b = e.belief(1, 2, observer=0, own=raw['own_preferences'])
        self.assertEqual(b['possible_preferences'], ['want', 'avoid'])
        self.assertEqual(b['favored'], 'want')
        np.testing.assert_allclose(list(b['preference_weights'].values()), [2/3, 0, 1/3])
        # The actual execution keeps the same full-game policy object.
        tree = e.tree
        row = e.choices(raw['type_catalogues']['1'][0])
        e.observe(row['admissible_actions'][0])
        self.assertIs(e.tree, tree)
        raw, prefix = forward_fixture(deadline=True)
        end = TerminalEpisode(raw, prefix)
        for own in raw['type_catalogues']['1']:
            self.assertEqual(end.choices(own)['admissible_actions'], [{'response': 'ACCEPT'}])

    def test_revelation_chance_is_world_conditioned_not_uniform(self):
        raw, _ = forward_fixture(deadline=True)
        rules = InvestigationRules(raw)
        root = rules.initial()
        for a in ({'action': 'PASS'}, {'action': 'PASS'}):
            root = rules._apply(root, decode_action(a))
        tree = TerminalWindow(rules, root, rules.worlds).solve()
        self.assertTrue(tree.chance)
        for i, probs in tree.chance.items():
            np.testing.assert_array_equal(probs.sum(axis=0), 1)
            self.assertTrue(np.isin(probs, [0, 1]).all())
        for e in tree.entries:
            if e.actor is None:
                self.assertTrue(e.node.state.is_terminal)

    def test_same_rule_under_player_renaming(self):
        raw, prefix = forward_fixture()
        first = TerminalEpisode(raw, prefix)
        mapping = {0: 2, 1: 0, 2: 1}
        rr, pp = rename(raw, prefix, mapping)
        other = TerminalEpisode(rr, pp)
        for own in raw['type_catalogues']['1']:
            a = first.choices(own)
            b = other.choices(own)
            expected = {str(rename_action(action, mapping)): (prob, values)
                        for action, prob, values in zip(a['actions'], a['probabilities'], a['values'])}
            for action, prob, values in zip(b['actions'], b['probabilities'], b['values']):
                old_prob, old_values = expected[str(action)]
                self.assertAlmostEqual(prob, old_prob)
                np.testing.assert_allclose([values[mapping[p]] for p in range(3)], old_values)


if __name__ == '__main__':
    unittest.main()
