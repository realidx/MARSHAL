"""Independent checks of RR horizons, native leaves and private solution scope."""
from copy import deepcopy
from itertools import product
import unittest

import numpy as np

from training.b_sft.shared_teacher import SearchLimit
from training.b_sft.social_private_teacher import PrivateInvestigationRules, PrivateWindow, observed_slots
from training.strategic_slices.bounded import (BoundedPrivateWindow,
    DEFAULT_HORIZON_MODE, VERSION, current_payoffs, resolve_horizon)


def raw_game(players=2, rounds=3, *, uncertain=False, binary=True):
    catalogues = {str(p): [[1]] for p in range(players)}
    goals = [dict(goal_id=0, binary=binary,
                  required_actions=[dict(player_id=p, action_id=0)
                                    for p in range(players)])]
    own = [1]
    if uncertain:
        # Every native teaching type must retain a positive goal. A separate
        # WANT anchor permits another preference to vary independently.
        goals.append(dict(goal_id=1, binary=True,
                          required_actions=[dict(player_id=p, action_id=0)
                                            for p in (0, 1)]))
        catalogues = {str(p): [[1, 1]] for p in range(players)}
        catalogues['1'] = [[1, 1], [0, 1]]
        own = [1, 1]
    return dict(ego=0, own_preferences=own, type_catalogues=catalogues,
                game=dict(n_players=players, n_actions_per_player=[1] * players,
                          goals=goals,
                          max_changes=1, menu_enabled=False,
                          round_robin=list(range(players)) * rounds))


def action_index(actions, *, action=None, response=None, partner=None):
    for index, native in enumerate(actions):
        value = native.to_dict()
        if (action is not None and value.get('action') != action or
                response is not None and value.get('response') != response):
            continue
        if partner is not None:
            if value.get('partner_id') != partner:
                continue
        return index
    raise AssertionError('Requested native test action is absent')


class BoundedSolverTests(unittest.TestCase):
    def tree(self, players=2, rounds=3, **options):
        rules = PrivateInvestigationRules(raw_game(players, rounds))
        options.setdefault('horizon_mode', 'rr')
        return BoundedPrivateWindow(rules, rules.initial(), rules.worlds, **options)

    def test_default_horizon_completes_next_focal_proposal_after_investigation(self):
        for players in (2, 3):
            rules = PrivateInvestigationRules(raw_game(players))
            tree = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
                                        max_nodes=40000)
            self.assertEqual(tree.horizon_mode, DEFAULT_HORIZON_MODE)
            self.assertEqual(tree.base_cutoff, players)
            self.assertEqual(tree.next_own_proposal_index, players)
            self.assertEqual(tree.cutoff, players + 1)
            self.assertEqual(tree.actual_proposal_turns, players + 1)
            self.assertTrue(tree.next_own_proposal_included)
            entry = tree.entries[0]
            index = entry.children[action_index(entry.actions, action='INVESTIGATE')]
            for _ in range(players - 1):
                entry = tree.entries[index]
                index = entry.children[action_index(entry.actions, action='PASS')]
            own_return = tree.entries[index]
            self.assertEqual(own_return.actor, 0)
            self.assertEqual(own_return.node.state.turn_index, players)
            self.assertEqual(observed_slots(own_return.node, 0), ((1, 0),))
            self.assertTrue(own_return.children)
            offers = [(ai, a) for ai, a in enumerate(own_return.actions)
                      if a.to_dict().get('action') == 'OFFER'
                      and a.to_dict().get('partner_id') == 1]
            ai, _ = max(offers, key=lambda item:
                        sum(item[1].offer.proposer_action)
                        + sum(item[1].offer.partner_action))
            pending = tree.entries[own_return.children[ai]]
            self.assertIsNotNone(pending.node.pending)
            self.assertIsNotNone(pending.actor)
            accepted = pending.children[action_index(pending.actions, response='ACCEPT')]
            self.assertIn(accepted, tree.cutoff_leaves)
            leaf = tree.entries[accepted]
            self.assertEqual(leaf.node.state.turn_index, players + 1)
            self.assertIsNone(leaf.node.pending)
            # The return action can now alter cutoff commitments. The
            # original three-player binary goal needs an earlier C commitment;
            # its two-player version earns utility immediately here.
            self.assertEqual(leaf.node.state.snapshot_commitments()[0][0], 1)
            self.assertEqual(leaf.node.state.snapshot_commitments()[1][0], 1)
            if players == 2:
                np.testing.assert_array_equal(leaf.payoff, [[1., 1.]])
            self.assertEqual({e.node.state.turn_index for e in tree.entries
                              if e.actor is None}, {players + 1})
            tree.audit_native()

    def test_private_query_changes_the_next_own_action_in_two_and_three_player_games(self):
        for players in (2, 3):
            # Rotate the second native round so the investigator's return is
            # last. This isolates use of its private answer in that actual
            # next decision, without requiring a continuation-value model.
            raw = dict(ego=0, own_preferences=[1, 1],
                type_catalogues={'0': [[1, 1]], '1': [[1, -1], [-1, 1]],
                                 **({'2': [[0, 1]]} if players == 3 else {})},
                game=dict(n_players=players,
                    n_actions_per_player=[1, 2] + ([1] if players == 3 else []),
                    goals=[dict(goal_id=0, binary=True, required_actions=[
                        dict(player_id=0, action_id=0), dict(player_id=1, action_id=0)]),
                        dict(goal_id=1, binary=True, required_actions=[
                        dict(player_id=0, action_id=0), dict(player_id=1, action_id=1)])],
                    max_changes=1, menu_enabled=False,
                    round_robin=list(range(players)) + list(range(1, players)) + [0]))
            rules = PrivateInvestigationRules(raw)
            root = rules.initial()
            horizon = resolve_horizon(rules, root)
            self.assertEqual(horizon['next_own_proposal_index'], 2 * players - 1)
            self.assertEqual(horizon['cutoff'], 2 * players)
            query = next(a for a in rules.actions(root) if a.to_dict() ==
                         dict(action='INVESTIGATE', player=1, goal=0))
            node = rules._apply(root, query)
            while node.state.turn_index < 2 * players - 1:
                actions = rules.actions(node)
                node = rules._apply(node, actions[action_index(actions, action='PASS')])
            self.assertEqual(rules.actor(node), 0)
            self.assertEqual(observed_slots(node, 0), ((1, 0),))
            tree = BoundedPrivateWindow(rules, node, rules.worlds).solve()
            self.assertEqual([len(ids) for ids in tree.information_groups[0]], [1, 1])
            self.assertFalse(np.allclose(tree.policy[0][:, 0], tree.policy[0][:, 1]))
            # Both answers permit utility one, but require different offers:
            # the partner wants exactly one of the two cooperation goals.
            # Repeating the same offer would be rejected in the other world.
            np.testing.assert_allclose(tree.values[0][:, 0], [1., 1.])
            self.assertTrue(tree.certificate['terminal'])
            tree.audit_native()

    def test_pending_root_includes_responder_next_proposal_without_extra_round(self):
        for players in (2, 3):
            rules = PrivateInvestigationRules(raw_game(players))
            root = rules.initial()
            offer = next(a for a in rules.actions(root)
                         if a.to_dict().get('action') == 'OFFER'
                         and a.to_dict().get('partner_id') == 1)
            pending = rules._apply(root, offer)
            tree = BoundedPrivateWindow(rules, pending, rules.worlds,
                                        max_nodes=40000)
            self.assertEqual(tree.root_actor, 1)
            self.assertEqual(tree.next_own_proposal_index, 1)
            self.assertEqual(tree.cutoff, players)
            self.assertTrue(tree.next_own_proposal_included)
            tree.audit_native()

    def test_native_terminal_clips_horizon_without_inventing_own_return(self):
        rules = PrivateInvestigationRules(raw_game(2, 1))
        root = rules.initial()
        tree = BoundedPrivateWindow(rules, root, rules.worlds).solve()
        self.assertIsNone(tree.next_own_proposal_index)
        self.assertFalse(tree.next_own_proposal_included)
        self.assertEqual(tree.cutoff, 2)
        self.assertFalse(tree.cutoff_leaves)
        root = rules._apply(root, rules.actions(root)[action_index(rules.actions(root), action='PASS')])
        tree = BoundedPrivateWindow(rules, root, rules.worlds).solve()
        self.assertEqual(tree.actual_proposal_turns, 1)
        self.assertTrue(tree.terminal_truncated_horizon)
        self.assertTrue(tree.certificate['terminal'])
        self.assertFalse(tree.certificate['next_own_proposal_included'])

    def test_legacy_rr_mode_retains_endpoint_but_has_distinct_contract_identity(self):
        rules = PrivateInvestigationRules(raw_game(2))
        root = rules.initial()
        old = BoundedPrivateWindow(rules, root, rules.worlds, horizon_mode='rr').solve()
        new = BoundedPrivateWindow(rules, root, rules.worlds).solve()
        self.assertEqual(old.cutoff, 2)
        self.assertEqual(new.cutoff, 3)
        self.assertFalse(old.next_own_proposal_included)
        self.assertTrue(new.next_own_proposal_included)
        self.assertNotEqual(old.reference_identity()[0], new.reference_identity()[0])
        self.assertEqual(old.certificate['horizon_mode'], 'rr')
        self.assertEqual(new.certificate['horizon_mode'], DEFAULT_HORIZON_MODE)

    def test_rr_counts_completed_proposal_opportunities_for_two_and_three_players(self):
        for players in (2, 3):
            tree = self.tree(players)
            self.assertEqual(tree.proposal_turns, players)
            self.assertEqual(tree.cutoff, players)
            self.assertTrue(tree.cutoff_leaves)
            self.assertEqual({entry.node.state.turn_index for entry in tree.entries
                              if entry.actor is None}, {players})
            self.assertTrue(all(tree.entries[index].node.pending is None
                                for index in tree.cutoff_leaves))
            # Count a complete native path independently of solver values.
            index = 0
            for _ in range(players):
                entry = tree.entries[index]
                ai = action_index(entry.actions, action='PASS')
                index = entry.children[ai]
            self.assertIn(index, tree.cutoff_leaves)
            tree.audit_native()

    def test_last_offer_is_resolved_before_cutoff_and_queries_consume_one_turn(self):
        tree = self.tree()
        # INVESTIGATE is an entire completed proposal opportunity.
        entry = tree.entries[0]
        ai = action_index(entry.actions, action='INVESTIGATE')
        index = entry.children[ai]
        self.assertEqual(tree.entries[index].node.state.turn_index, 1)
        # OFFER leaves the proposal cursor unchanged and creates a responder.
        entry = tree.entries[index]
        ai = action_index(entry.actions, action='OFFER')
        pending = tree.entries[entry.children[ai]]
        self.assertEqual(pending.node.state.turn_index, 1)
        self.assertIsNotNone(pending.node.pending)
        self.assertIsNotNone(pending.actor)
        self.assertEqual({a.to_dict()['response'] for a in pending.actions}, {'ACCEPT', 'REJECT'})
        for child in pending.children:
            self.assertIn(child, tree.cutoff_leaves)
            self.assertEqual(tree.entries[child].node.state.turn_index, 2)
            self.assertIsNone(tree.entries[child].node.pending)

    def test_nonterminal_leaf_scores_current_commitments_without_optimistic_tail(self):
        tree = self.tree(3)
        index = 0
        for _ in range(3):
            entry = tree.entries[index]
            index = entry.children[action_index(entry.actions, action='PASS')]
        leaf = tree.entries[index]
        self.assertFalse(leaf.node.state.is_terminal)
        np.testing.assert_array_equal(leaf.payoff, [[0., 0., 0.]])
        # Original native continuation can still earn the goal. Its attainable
        # future reward must not be included in the bounded leaf payoff.
        node = deepcopy(leaf.node)
        for partner in (1, 2):
            actions = tree.rules.actions(node)
            choices = [a for a in actions if a.to_dict().get('action') == 'OFFER'
                       and a.to_dict().get('partner_id') == partner]
            chosen = max(choices, key=lambda a: sum(a.offer.proposer_action)
                         + sum(a.offer.partner_action))
            node = tree.rules._apply(node, chosen)
            ai = action_index(tree.rules.actions(node), response='ACCEPT')
            node = tree.rules._apply(node, tree.rules.actions(node)[ai])
        self.assertEqual(current_payoffs(tree.rules, node, tree.worlds[0]), (1., 1., 1.))
        np.testing.assert_array_equal(leaf.payoff, [[0., 0., 0.]])

    def test_linear_cutoff_payoff_preserves_fraction_and_pending_offer_has_no_value(self):
        rules = PrivateInvestigationRules(raw_game(3, binary=False))
        node = rules.initial()
        offers = [a for a in rules.actions(node) if a.to_dict().get('action') == 'OFFER']
        chosen = max(offers, key=lambda a: sum(a.offer.proposer_action) + sum(a.offer.partner_action))
        pending = rules._apply(node, chosen)
        self.assertEqual(current_payoffs(rules, pending, rules.worlds[0]), (0., 0., 0.))
        ai = action_index(rules.actions(pending), response='ACCEPT')
        child = rules._apply(pending, rules.actions(pending)[ai])
        np.testing.assert_allclose(current_payoffs(rules, child, rules.worlds[0]), [2/3] * 3)
        # Starting from a pending decision must include that response in the
        # completed-opportunity budget, without counting OFFER twice.
        tree = BoundedPrivateWindow(rules, pending, rules.worlds, horizon_mode='rr')
        self.assertEqual(tree.cutoff, 3)
        self.assertIsNotNone(tree.entries[0].node.pending)
        tree.audit_native()

    def test_full_remaining_game_matches_existing_terminal_private_solver(self):
        rules = PrivateInvestigationRules(raw_game(2, 1, uncertain=True))
        prior = [.75, .25]
        bounded = BoundedPrivateWindow(rules, rules.initial(), rules.worlds,
                                      world_weights=prior,
                                      solver_mode='synchronous').solve()
        terminal = PrivateWindow(rules, rules.initial(), rules.worlds,
                                 world_weights=prior, max_sweeps=128).solve()
        self.assertEqual(len(bounded.entries), len(terminal.entries))
        for a, b in zip(bounded.policy, terminal.policy):
            if a is not None:
                np.testing.assert_array_equal(a, b)
        np.testing.assert_allclose(bounded.values[0], terminal.values[0])
        self.assertTrue(bounded.certificate['terminal'])
        self.assertTrue(bounded.certificate['remaining_game_terminal_scope'])
        self.assertFalse(bounded.certificate['full_game_equilibrium_verified'])
        self.assertEqual(bounded.cutoff_leaves, set())
        self.assertTrue(bounded.audit_native()['all_values_match'])

    def test_private_query_partitions_only_the_investigators_information(self):
        rules = PrivateInvestigationRules(raw_game(3, 3, uncertain=True))
        root = rules.initial()
        query = next(a for a in rules.actions(root) if a.to_dict() ==
                     dict(action='INVESTIGATE', player=1, goal=0))
        root = rules._apply(root, query)
        tree = BoundedPrivateWindow(rules, root, rules.worlds,
                                   world_weights=[.8, .2], horizon_mode='rr').solve()
        self.assertEqual(len(tree.worlds), 2)
        self.assertEqual(observed_slots(root, 0), ((1, 0),))
        self.assertEqual(observed_slots(root, 2), ())
        actor_zero = [i for i, entry in enumerate(tree.entries) if entry.actor == 0]
        actor_two = [i for i, entry in enumerate(tree.entries) if entry.actor == 2]
        self.assertTrue(actor_zero and actor_two)
        self.assertEqual([len(ids) for ids in tree.information_groups[actor_zero[0]]], [1, 1])
        self.assertEqual([len(ids) for ids in tree.information_groups[actor_two[0]]], [2])
        for index, groups in tree.information_groups.items():
            for ids in groups:
                np.testing.assert_allclose(tree.policy[index][:, ids],
                    np.repeat(tree.policy[index][:, ids[:1]], len(ids), axis=1))
        self.assertTrue(tree.certificate['all_player_same_solver'])
        self.assertFalse(tree.certificate['terminal'])
        self.assertFalse(tree.certificate['full_game_equilibrium_verified'])
        self.assertEqual(tree.certificate['version'], VERSION)
        checks = tree.certificate['root_private_information_deviation_checks']
        self.assertTrue(all(check['own_gain'] <= 1e-9 for check in checks))
        self.assertEqual(sum(check['player'] == 0 for check in checks), 2)

    def test_rr_from_mid_round_is_n_proposal_opportunities_and_identity_names_horizon(self):
        rules = PrivateInvestigationRules(raw_game(2, 3))
        root = rules.initial()
        ai = action_index(rules.actions(root), action='PASS')
        root = rules._apply(root, rules.actions(root)[ai])
        one = BoundedPrivateWindow(rules, root, rules.worlds, horizon_mode='rr').solve()
        two = BoundedPrivateWindow(rules, root, rules.worlds, lookahead_rr=2,
                                   horizon_mode='rr').solve()
        self.assertEqual((one.root_turn_index, one.cutoff), (1, 3))
        self.assertEqual((two.proposal_turns, two.cutoff), (4, 5))
        self.assertNotEqual(one.reference_identity()[0], two.reference_identity()[0])
        self.assertNotEqual(one.certificate['policy_sha256'], two.certificate['policy_sha256'])

    def test_certificate_against_independent_exhaustive_contingent_deviations(self):
        rules = PrivateInvestigationRules(raw_game(2, 1, uncertain=True))
        root = rules.initial()
        ai = action_index(rules.actions(root), action='PASS')
        root = rules._apply(root, rules.actions(root)[ai])
        tree = BoundedPrivateWindow(rules, root, rules.worlds,
                                   world_weights=[.75, .25]).solve()

        def information(index, wi):
            entry = tree.entries[index]
            world = tree.worlds[wi]
            return (index, world[entry.actor],
                    tuple(world[p][g] for p, g in observed_slots(entry.node, entry.actor)))

        def expected(index, wi, player, strategy):
            entry = tree.entries[index]
            if entry.actor is None:
                commitments = entry.node.state.snapshot_commitments()
                score = [int(all(commitments[a.player_id][a.action_id]
                                 for a in goal.required_actions))
                         for goal in rules.spec.goals]
                return sum(v * s for v, s in zip(tree.worlds[wi][player], score))
            if entry.actor == player:
                return expected(entry.children[strategy[information(index, wi)]],
                                wi, player, strategy)
            return sum(tree.policy[index][ai, wi] * expected(child, wi, player, strategy)
                       for ai, child in enumerate(entry.children))

        for player in range(2):
            spaces = {}
            for index, entry in enumerate(tree.entries):
                if entry.actor == player:
                    for wi in range(tree.w):
                        spaces[information(index, wi)] = range(len(entry.actions))
            keys = list(spaces)
            best = {own: -np.inf for own in set(w[player] for w in tree.worlds)}
            # Here all complete pure contingent strategies fit in 8 or 36
            # cases. This enumerator uses neither response() nor its reaches,
            # grouping tables or final deviation-check implementation.
            for choices in product(*(spaces[key] for key in keys)):
                strategy = dict(zip(keys, choices))
                outcomes = np.asarray([expected(0, wi, player, strategy)
                                       for wi in range(tree.w)])
                for own in best:
                    ids = [wi for wi, world in enumerate(tree.worlds) if world[player] == own]
                    best[own] = max(best[own], float(np.average(outcomes[ids],
                        weights=tree.world_weights[ids])))
            for own, optimum in best.items():
                ids = [wi for wi, world in enumerate(tree.worlds) if world[player] == own]
                baseline = np.average(tree.values[0][ids, player],
                                      weights=tree.world_weights[ids])
                self.assertAlmostEqual(optimum, baseline)

    def test_cycle_and_resource_limits_fail_closed_without_a_certificate(self):
        tree = self.tree(max_sweeps=128, solver_mode='synchronous')

        def alternating_response(player):
            updates = {}
            for index, entry in enumerate(tree.entries):
                if entry.actor == player:
                    probabilities = np.zeros_like(tree.policy[index])
                    chosen = 1 if tree.policy[index][0, 0] == 1 else 0
                    probabilities[chosen] = 1
                    updates[index] = probabilities
            return updates, np.zeros((tree.w, tree.n))

        tree.response = alternating_response
        with self.assertRaisesRegex(SearchLimit, 'cycled'):
            tree.solve()
        self.assertIsNone(tree.certificate)
        self.assertIsNone(tree.values)
        with self.assertRaisesRegex(SearchLimit, 'node budget'):
            self.tree(max_nodes=1)
        tree = self.tree()
        tree.deadline = 0
        with self.assertRaisesRegex(SearchLimit, 'wall budget'):
            tree.solve()
        self.assertIsNone(tree.certificate)

    def test_invalid_rr_budgets_rejected(self):
        for value in (0, -1, True, 1.5):
            with self.assertRaises(ValueError):
                self.tree(lookahead_rr=value)
        with self.assertRaisesRegex(ValueError, 'horizon_mode'):
            self.tree(horizon_mode='query-only-extra-step')


if __name__ == '__main__':
    unittest.main()
