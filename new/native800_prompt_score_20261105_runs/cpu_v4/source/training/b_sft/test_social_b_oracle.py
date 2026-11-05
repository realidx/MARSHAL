import unittest
from copy import deepcopy

from training.b_sft.social_b_oracle import BeliefOracle, canonical, forward_fixture
from training.b_sft.shared_teacher import SearchLimit


class BeliefOracleTests(unittest.TestCase):
    def make(self, **kwargs):
        raw, prefix = forward_fixture()
        return BeliefOracle(raw, prefix, **kwargs)

    def test_forward_choice_and_deadline(self):
        o = self.make()
        expected = [[2, 1], [1, 1], [1, 1]]
        for w, values in zip(o.worlds, expected):
            row = o.choices(w[1])
            self.assertEqual([v['own'] for v in row['values']], values)
        self.assertEqual(o.choices(o.worlds[1][1])['admissible_actions'], [{'response': 'REJECT'}])
        self.assertEqual(len(o.choices(o.worlds[2][1])['admissible_actions']), 2)
        raw, prefix = forward_fixture(deadline=True)
        d = BeliefOracle(raw, prefix)
        for w in d.worlds:
            self.assertEqual(d.choices(w[1])['admissible_actions'], [{'response': 'ACCEPT'}])

    def test_ties_retained_and_later_evidence_updates(self):
        o = self.make()
        o.observe({'response': 'REJECT'})
        self.assertEqual(len(o.worlds), 3)
        o.observe(dict(action='OFFER', partner_id=2, proposer_action=[0, 1], partner_action=[1]))
        self.assertEqual(o.belief(1, 2)['possible_preferences'], ['want', 'neutral'])
        o.observe({'response': 'ACCEPT'})
        self.assertEqual(o.belief(1, 2)['possible_preferences'], ['want', 'neutral'])
        self.assertEqual(o.belief(1, 2)['favored'], 'undetermined')

    def test_accept_identifies_avoid_without_reviving_types(self):
        o = self.make()
        o.observe({'response': 'ACCEPT'})
        self.assertEqual(o.belief(1, 2)['possible_preferences'], ['avoid'])
        o.observe({'action': 'PASS'})
        self.assertEqual(o.belief(1, 2)['possible_preferences'], ['avoid'])

    def test_intervention_does_not_filter(self):
        o = self.make()
        o.observe({'response': 'ACCEPT'}, kind='intervention')
        self.assertEqual(len(o.worlds), 3)
        with self.assertRaises(ValueError):
            o.observe({'action': 'PASS'}, kind='setup')

    def test_failure_is_not_negative_evidence(self):
        o = self.make(max_nodes=1)
        before = (o.worlds, list(o.history))
        with self.assertRaises(SearchLimit):
            o.observe({'response': 'REJECT'})
        self.assertEqual((o.worlds, o.history), before)
        with self.assertRaises(ValueError):
            o.observe({'response': 'ACCEPT', 'extra': 0})
        self.assertEqual((o.worlds, o.history), before)

    def test_information_boundary_and_arithmetic(self):
        o = self.make()
        # P2 has one private row across three distinct hidden P1 types;
        # choice calculation receives no realized hidden type.
        o.observe({'response': 'REJECT'})
        o.observe(dict(action='OFFER', partner_id=2, proposer_action=[0, 1], partner_action=[1]),
                  kind='intervention')
        choices = [o.choices(w[2]) for w in o.worlds]
        self.assertTrue(all(c == choices[0] for c in choices))
        self.assertEqual(choices[0]['admissible_actions'], [{'response': 'ACCEPT'}])
        self.assertGreater(o.verify_leaf_values(), 0)

    def test_horizon_changes_are_visible(self):
        short, long = self.make(turns=1), self.make(turns=2)
        own = short.worlds[0][1]
        self.assertEqual(short.choices(own)['admissible_actions'], [{'response': 'ACCEPT'}])
        self.assertEqual(long.choices(own)['admissible_actions'], [{'response': 'REJECT'}])
        self.assertFalse(short.choices(own)['terminal_value'])

    def test_root_action_order_does_not_remove_ties(self):
        a, b = self.make(), self.make(reverse_actions=True)
        for w in a.worlds:
            normalize = lambda o: sorted(x['response'] for x in o.choices(w[1])['admissible_actions'])
            self.assertEqual(normalize(a), normalize(b))

    def test_exclusions_have_value_based_evidence(self):
        o = self.make()
        o.observe({'response': 'ACCEPT'})
        rows = o.events[-1]['comparisons']
        self.assertEqual([r['evidence_reason'] for r in rows],
                         ['strict_self_value', 'prosocial_tie_rule', 'compatible'])
        self.assertEqual(len(o.events[-1]['information_before']['public_worlds']), 3)
        self.assertEqual(len(o.events[-1]['public_worlds_after']), 1)

    def test_equal_leading_support_is_undetermined(self):
        o = self.make()
        o.observe({'response': 'REJECT'})
        rows = o.events[-1]['comparisons']
        self.assertEqual([len(r['admissible_actions']) for r in rows], [1, 1, 2])
        self.assertEqual(o.belief(1, 2)['possible_preferences'], ['want', 'neutral', 'avoid'])
        self.assertEqual(o.belief(1, 2)['preference_weights'], dict(want=.4, neutral=.4, avoid=.2))
        self.assertEqual(o.belief(1, 2)['favored'], 'undetermined')

    def test_rolling_loss_does_not_relabel_historical_b(self):
        raw, prefix = forward_fixture(rounds=2)
        o = BeliefOracle(raw, prefix)
        world = o.worlds[0]
        acceptance = None
        while not o.node.state.is_terminal:
            actor = o.rules.actor(o.node)
            row = o.choices(world[actor])
            self.assertEqual(row['cutoff_turn'], min(row['decision_turn'] + 2, 6))
            action = sorted(row['admissible_actions'], key=canonical)[-1]
            o.observe(action)
            if actor == 2 and action == {'response': 'ACCEPT'} and acceptance is None:
                acceptance = deepcopy(o.events[-1])
                estimate = next(v['own'] for v in row['values'] if v['action'] == action)
                self.assertEqual(estimate, 1)
            self.assertIn(world, o.worlds)
        self.assertEqual(sum(v * flag for v, flag in zip(
            world[2], o.node.state.goal_satisfaction())), -1)
        self.assertIsNotNone(acceptance)
        self.assertIn(acceptance, o.events)
        replay = BeliefOracle.replay(raw, o.events)
        self.assertEqual(replay.events, o.events)
        self.assertEqual(replay.belief(1, 2), o.belief(1, 2))

    def test_observer_private_query_does_not_change_public_replay(self):
        o = self.make()
        events = deepcopy(o.events)
        o.belief(1, 2, observer=1, own=o.worlds[0][1])
        self.assertEqual(o.events, events)
        self.assertEqual(len(o.worlds), 3)
        with self.assertRaises(KeyError):
            BeliefOracle.replay(o.raw, [{'action': {'action': 'PASS'}}])


if __name__ == '__main__':
    unittest.main()
