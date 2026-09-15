from dataclasses import replace
from itertools import product
import random

import numpy as np
import pytest

from benac_p.generator import GeneratorConfig, generate_game
from benac_p.mcts_bp_audit import audit_game, make_game
from benac_p.mcts_oracle import Budget, PrivateUCT, make_catalogues
from benac_p.private_game_pilot import apply
from benac_p.state import GameState


@pytest.mark.parametrize('cell', ('n4_k2_g12_r4', 'n4_k3_g16_r6'))
def test_compact_actions_and_transitions_match_native_all_actions(cell):
    spec, oracle, realized = make_game(62000, cell, 6, Budget(simulations=16))
    rng = random.Random(93)
    state, pending, node = GameState(spec), None, (0, 0, None)
    while not state.is_terminal:
        compact = oracle.actions(node)
        translated = tuple(oracle.native_action(node, a) for a in compact)
        from benac_p.schema import response_actions
        native_actions = state.legal_proposals() if pending is None else response_actions(pending)
        assert set(translated) == set(native_actions)
        for action, native_action in zip(compact, translated):
            import copy
            trial = copy.deepcopy(state)
            trial_pending = apply(trial, pending, native_action)
            after = oracle.step(node, action)
            mask = sum(int(trial.commitments[p, a]) << (oracle.offsets[p] + a)
                       for p in range(spec.n_players) for a in range(spec.n_actions_per_player[p]))
            assert after[:2] == (mask, trial.turn_index)
            assert (after[2] is None) == (trial_pending is None)
        chosen = rng.choice(compact)
        pending = apply(state, pending, oracle.native_action(node, chosen))
        node = oracle.step(node, chosen)
    assert state.terminal_rewards().tolist() == [oracle.utilities[p][t, node[0]] for p, t in enumerate(realized)]
    oracle.clear_caches()


def test_own_information_only_and_reproducible_actions():
    spec, first, actual = make_game(62001, 'n4_k2_g12_r4', 6, Budget(simulations=128))
    ego = spec.round_robin[0]
    other_truth = spec.private_preferences.copy()
    other_truth[:] *= -1
    second = PrivateUCT(replace(spec, private_preferences=other_truth, seed=123,
                                metadata={'hidden': 'sentinel'}), first.catalogues, first.budget)
    for t in range(6):
        a = first.search((0, 0, None), ego, t, first.prior)
        b = second.search((0, 0, None), ego, t, second.prior)
        for key in ('action', 'counts', 'means', 'root_action_coverage'):
            assert a[key] == b[key]
    assert np.all(first.spec.private_preferences == 0)
    first.clear_caches(); second.clear_caches()


def test_finite_prior_has_all_three_semantics_without_revealing_realized_row():
    rows = make_catalogues(4, 16, 7, profiles=6)
    assert rows == make_catalogues(4, 16, 7, profiles=6)
    for catalogue in rows:
        assert len(set(catalogue)) == 6
        for goal in range(16):
            assert {row[goal] for row in catalogue} == {-1, 0, 1}
    with pytest.raises(ValueError):
        make_catalogues(4, 16, 7, profiles=4)


def test_support_filter_matches_explicit_joint_worlds_and_ego_is_intervention():
    spec, oracle, actual = make_game(62002, 'n4_k2_g12_r4', 6, Budget(simulations=32))
    learner = spec.round_robin[0]
    node, domains = (0, 0, None), oracle.prior
    worlds = [w for w in product(*domains) if w[learner] == actual[learner]]
    for _ in range(12):
        if oracle.terminal(node):
            break
        actor = oracle.actor(node)
        action = oracle.search(node, actor, actual[actor], domains)['action']
        before = domains
        if actor != learner:
            worlds = [w for w in worlds if oracle.search(node, actor, w[actor], before)['action'] == action]
        domains = oracle.update(node, action, before, learner)
        if actor == learner:
            assert domains == before
        for player in range(spec.n_players):
            assert actual[player] in domains[player]
            if player != learner:
                assert set(domains[player]) == {w[player] for w in worlds}
        node = oracle.step(node, action)
    oracle.clear_caches()


def test_mcts_distinguishes_terminal_response_gain_and_keeps_full_menu_actions():
    spec, oracle, actual = make_game(62000, 'n4_k2_g12_r4', 6, Budget(simulations=256))
    # Find a legal response state with different immediate terminal utilities.
    found = False
    final_turn = len(spec.round_robin) - 1
    for mask in range(1 << oracle.bits):
        node = (mask, final_turn, None)
        for offer in oracle.actions(node)[1:]:
            if not offer[2]:
                continue
            pending = oracle.step(node, offer)
            actor = oracle.actor(pending)
            values = [int(oracle.utilities[actor][0, oracle.step(pending, a)[0]]) for a in oracle.actions(pending)]
            if len(set(values)) > 1:
                chosen = oracle.search(pending, actor, 0, oracle.prior)['action']
                assert values[chosen] == max(values)
                assert oracle.search(pending, actor, 0, oracle.prior)['root_action_coverage'] == 1
                found = True
                break
        if found:
            break
    assert found
    oracle.clear_caches()


def test_small_end_to_end_audit_exports_honest_labels_and_replays():
    game, bs, ps = audit_game(62003, 'n4_k2_g12_r4', 6, Budget(simulations=32),
                             eval_samples=4, actual_samples=1, positions=2)
    assert game['native_replay_verified'] and game['independent_joint_support_verified']
    assert bs and ps
    for sample in bs + ps:
        assert 'private_preferences' not in sample['input']['game']
        assert 'realized_types' not in sample['input']
        assert 'seed' not in sample['input']['game']
    for sample in bs:
        assert sample['answer']['possible_preferences']
        assert sample['label_status'].startswith('exact_support_under_declared_finite')
    for sample in ps:
        assert sample['label_status'] == 'approximate_search_demonstration'
        assert 'q' not in sample['input']
