from dataclasses import replace

import numpy as np
import pytest

from benac_p.endgame import SearchLimit
from benac_p.generator import generate_game
from benac_p.private_game_pilot import (
    CELLS, binary_catalogues, decision_view, oracle_probe, rollout, structure,
)
from benac_p.state import GameState


@pytest.mark.parametrize('cell', CELLS)
def test_private_native_rollouts_replay_from_zero(cell):
    spec = replace(generate_game(61000, CELLS[cell]), menu_enabled=True)
    for policy in ('category_random', 'immediate_reference'):
        result = rollout(spec, policy, 61000)
        assert result['history_replay_verified']
        assert not result['policy_is_terminal_rational_oracle']
        assert result == rollout(spec, policy, 61000)
    n, k = spec.n_players, spec.n_actions_per_player[0]
    offers = (k+1)**2-1
    assert structure(spec)['initial_proposal_actions'] == 1+(n-1)*(offers+offers*(offers-1)//2)


def test_decision_view_does_not_change_with_other_players_private_truth():
    spec = replace(generate_game(61000, CELLS['n4_k2_g12_r4']), menu_enabled=True)
    actor = spec.round_robin[0]
    prefs = spec.private_preferences.copy()
    for player in range(spec.n_players):
        if player != actor:
            prefs[player] *= -1
    altered = replace(spec, private_preferences=prefs, seed=999, metadata={'private': 'sentinel'})
    assert decision_view(GameState(spec), actor, prefs[actor]) == decision_view(GameState(altered), actor, prefs[actor])


def test_auxiliary_prior_is_explicitly_restricted_but_hides_every_goal():
    spec = generate_game(61000, CELLS['n4_k2_g12_r4'])
    types = binary_catalogues(spec, 61000)
    assert len(types) == 4
    for rows in types.values():
        assert len(rows) == 2
        assert all(1 in row for row in rows)
        assert np.all(np.array(rows[0]) != np.array(rows[1]))


def test_incomplete_search_never_emits_action_labels(monkeypatch):
    def fail(*args, **kwargs):
        raise SearchLimit('deliberate test limit')
    monkeypatch.setattr('benac_p.private_game_pilot.RationalPartner.__call__', fail)
    spec = generate_game(61000, CELLS['n4_k2_g12_r4'])
    result = oracle_probe(spec, 61000, 'all_private', 'partner_root_action', 1, 1)
    assert result['status'] == 'node_limit'
    assert result['action_labels'] is None
    assert result['hidden_worlds_given_own'] == 8
