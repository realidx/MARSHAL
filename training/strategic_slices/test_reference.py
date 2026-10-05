"""Independent privacy, native scoring, legality and identity checks."""
from copy import deepcopy
import unittest

import numpy as np

from training.b_sft.preference_contract import profile
from training.b_sft.social_private_teacher import PrivateInvestigationRules
from .reference import FixedReference


def fixture():
    return dict(
        game=dict(n_players=3, n_actions_per_player=[1, 1, 1], max_changes=1,
                  menu_enabled=False, round_robin=[0, 1, 2] * 3,
                  goals=[dict(goal_id=0, binary=True, required_actions=[
                      dict(player_id=0, action_id=0), dict(player_id=1, action_id=0)]),
                         dict(goal_id=1, binary=False, required_actions=[
                      dict(player_id=0, action_id=0), dict(player_id=2, action_id=0)])]),
        ego=0, own_preferences=[1, 1],
        type_catalogues={'0': [[1, 1]], '1': [[1, 1], [-1, 1]],
                         '2': [[1, 1], [1, -1]]},
        background_prior=profile('balanced'))


class GuardedWorld:
    """Fail if a reference reads an unobserved actual preference."""
    def __init__(self, world, actor, slots=()):
        self.world, self.actor, self.slots = world, actor, set(slots)

    def __getitem__(self, player):
        if player == self.actor:
            return self.world[player]
        world, slots = self.world, self.slots
        class Row:
            def __getitem__(self, goal):
                if (player, goal) not in slots:
                    raise AssertionError('Reference read an unobserved actual preference')
                return world[player][goal]
        return Row()


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.raw = fixture()
        self.rules = PrivateInvestigationRules(self.raw)
        self.reference = FixedReference(self.rules, self.raw['background_prior'])

    def test_unobserved_truth_never_enters_choice_or_acceptance_forecast(self):
        root = self.rules.initial()
        choices = {self.reference.action_index(root, w) for w in self.rules.worlds}
        self.assertEqual(len(choices), 1)
        for world in self.rules.worlds:
            fresh = FixedReference(self.rules, self.raw['background_prior'])
            self.assertEqual(fresh.action_index(root, GuardedWorld(world, 0)), next(iter(choices)))

    def test_only_own_query_answers_can_be_read_and_change_belief(self):
        node = self.rules.initial()
        query = next(a for a in self.rules.actions(node)
                     if a.to_dict() == dict(action='INVESTIGATE', player=1, goal=0))
        node = self.rules._apply(node, query)
        for _ in range(2):
            node = self.rules._apply(node, self.rules.actions(node)[0])  # Native PASS.
        self.assertEqual(self.rules.actor(node), 0)
        policies = {}
        for world in self.rules.worlds:
            guarded = GuardedWorld(world, 0, {(1, 0)})
            fresh = FixedReference(self.rules, self.raw['background_prior'])
            policies.setdefault(world[1][0], set()).add(fresh.action_index(node, guarded))
        self.assertTrue(all(len(actions) == 1 for actions in policies.values()))
        self.assertNotEqual(policies[1], policies[-1])
        self.assertEqual(self.reference._belief(0, (1, 1), ((1, 0, -1),))[0].sum(), 1)
        self.assertTrue(all(w[1][0] == -1 for w, mass in zip(self.rules.worlds,
            self.reference._belief(0, (1, 1), ((1, 0, -1),))[0]) if mass))

    def test_public_behavior_is_not_posterior_evidence(self):
        root = self.rules.initial()
        passed = self.rules._apply(root, self.rules.actions(root)[0])
        offer = next(a for a in self.rules.actions(root) if a.to_dict().get('action') == 'OFFER')
        pending = self.rules._apply(root, offer)
        rejected = self.rules._apply(pending, self.rules.actions(pending)[0])
        self.assertNotEqual(passed.state.transcript, rejected.state.transcript)
        self.assertEqual(self.reference.state_key(passed), self.reference.state_key(rejected))
        np.testing.assert_array_equal(self.reference.probabilities(passed), self.reference.probabilities(rejected))

    def test_three_round_native_rollouts_are_legal_and_one_hot(self):
        for world in self.rules.worlds:
            node = self.rules.initial()
            decisions = 0
            while not node.state.is_terminal:
                probabilities = self.reference.probabilities(node)
                self.assertEqual(probabilities.shape, (len(self.rules.actions(node)), len(self.rules.worlds)))
                np.testing.assert_array_equal(probabilities.sum(axis=0), np.ones(len(self.rules.worlds)))
                self.assertTrue(np.isin(probabilities, [0, 1]).all())
                ai = self.reference.action_index(node, world)
                node = self.rules.step(node, self.rules.actions(node)[ai], realized_world=world)
                decisions += 1
            self.assertGreaterEqual(decisions, 9)
            self.assertTrue(np.isfinite(self.rules.terminal_payoffs(node, world)).all())

    def test_responder_uses_native_linear_scoring_and_own_utility(self):
        root = self.rules.initial()
        offer = next(a for a in self.rules.actions(root)
                     if a.to_dict().get('action') == 'OFFER'
                     and a.to_dict()['partner_id'] == 2
                     and a.to_dict()['proposer_action'] == [1]
                     and a.to_dict()['partner_action'] == [1])
        pending = self.rules._apply(root, offer)
        for world in self.rules.worlds:
            action = self.rules.actions(pending)[self.reference.action_index(pending, world)].to_dict()
            self.assertEqual(action['response'], 'ACCEPT' if world[2][1] == 1 else 'REJECT')

    def test_response_own_tie_uses_expected_other_scores_before_native_order(self):
        raw = fixture()
        raw['type_catalogues']['2'] = [[1, 1], [1, 0], [1, -1]]
        rules = PrivateInvestigationRules(raw)
        reference = FixedReference(rules, raw['background_prior'])
        root = rules.initial()
        offer = next(a for a in rules.actions(root)
                     if a.to_dict().get('action') == 'OFFER'
                     and a.to_dict()['partner_id'] == 2
                     and a.to_dict()['proposer_action'] == [1]
                     and a.to_dict()['partner_action'] == [1])
        pending = rules._apply(root, offer)
        neutral_world = next(w for w in rules.worlds if w[2][1] == 0)
        action = rules.actions(pending)[reference.action_index(pending, neutral_world)].to_dict()
        self.assertEqual(action['response'], 'ACCEPT')

    def test_contract_identity_and_scope_are_explicit(self):
        repeat = FixedReference(self.rules, deepcopy(self.raw['background_prior']))
        self.assertEqual(repeat.certificate, self.reference.certificate)
        self.assertTrue(self.reference.certificate['verified'])
        self.assertFalse(self.reference.certificate['equilibrium'])
        self.assertFalse(self.reference.certificate['terminal_optimal'])
        changed = FixedReference(self.rules, profile('want_heavy'))
        self.assertNotEqual(changed.contract_sha256, self.reference.contract_sha256)


if __name__ == '__main__':
    unittest.main()
