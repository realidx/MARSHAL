"""Step-1 contracts: grounding, information isolation and known likelihoods."""

from dataclasses import replace
import math

import numpy as np
import pytest

from benac_p import (
    ActionRef, GameRunner, GameSpec, GameState, Goal, Offer, OfferProposal,
    PassProposal, Preference, ResponseAction, SoftProgressPolicy,
    build_player_observation, generate_game,
)


def spec():
    return GameSpec(
        n_players=3, n_actions_per_player=(2, 1, 1),
        goals=(
            Goal(0, (ActionRef(0, 0), ActionRef(1, 0), ActionRef(2, 0))),
            Goal(1, (ActionRef(0, 1), ActionRef(1, 0))),
        ),
        private_preferences=np.array([[1, -1], [1, 0], [-1, 1]], dtype=np.int8),
        round_robin=(0, 2, 1), max_changes=1, seed=1,
    )


def test_grounding_distinguishes_partial_negative_and_hypothetical_states():
    state = GameState(spec())
    offer = Offer(1, (1, 0), (1,))
    obs = build_player_observation(state, 1, pending_proposer_id=0, pending_offer=offer)
    view = obs.to_agent_dict()
    assert view["binding_commitments"] == {"P0": [], "P1": [], "P2": []}
    assert view["current_state_facts"]["your_utility_if_terminal"] == 0
    after = view["if_accepted"]
    assert after["binding_commitments"] == {"P0": ["A0"], "P1": ["A0"], "P2": []}
    assert after["new_commitment_count"] == 2
    assert after["goals"]["G0"] == {
        "satisfied": False, "missing_commitments": ["P2:A0"], "your_utility_contribution": 0,
    }
    assert after["your_utility_if_terminal"] == 0
    assert state.snapshot_commitments() == ((0, 0), (0,), (0,))
    state.resolve_offer(offer, "ACCEPT")
    state.resolve_offer(Offer(0, (1,), (1, 1)), "ACCEPT")
    view = build_player_observation(state, 0).to_agent_dict()
    assert view["current_state_facts"]["goals"]["G0"]["your_utility_contribution"] == 1
    assert view["current_state_facts"]["goals"]["G1"]["your_utility_contribution"] == -1
    assert view["current_state_facts"]["your_utility_if_terminal"] == 0


@pytest.mark.parametrize("seed", range(3))
def test_projected_facts_agree_with_engine_for_every_legal_offer(seed):
    state = GameState(generate_game(seed))
    while not state.is_terminal:
        actor = state.current_proposer()
        offers = build_player_observation(state, actor).legal_offers
        for offer in offers:
            projected = state.clone()
            projected.resolve_offer(offer, "ACCEPT")
            for player in range(state.n_players):
                obs = build_player_observation(
                    state, player, pending_proposer_id=actor, pending_offer=offer
                )
                facts = obs.to_agent_dict()["if_accepted"]
                assert obs.commitments_if_accepted(offer) == projected.snapshot_commitments()
                assert facts["your_utility_if_terminal"] == projected.reward(player)
                assert [int(g["satisfied"]) for g in facts["goals"].values()] == list(projected.goal_satisfaction())
        if offers:
            state.resolve_offer(offers[seed % len(offers)], "ACCEPT")
        else:
            state.apply_pass()


def test_public_grounding_does_not_reveal_utilities():
    state = GameState(spec())
    offer = Offer(1, (0, 1), (1,))
    view = build_player_observation(
        state, 1, mode="public", pending_proposer_id=0, pending_offer=offer
    ).to_agent_dict()
    for key in ("current_state_facts", "if_accepted"):
        assert view[key]["your_utility_if_terminal"] is None
        assert all(g["your_utility_contribution"] is None for g in view[key]["goals"].values())


def test_likelihoods_depend_on_own_preferences_not_other_hidden_state():
    state = GameState(spec())
    preferences = state.spec.private_preferences.copy()
    preferences[1:] *= -1
    other_state = GameState(replace(state.spec, private_preferences=preferences))
    policy = SoftProgressPolicy()
    for mode in ("private", "full"):
        first = build_player_observation(state, 0, mode=mode)
        second = build_player_observation(other_state, 0, mode=mode)
        assert first.to_agent_dict()["current_state_facts"] == second.to_agent_dict()["current_state_facts"]
        assert policy.proposal_distribution(first) == policy.proposal_distribution(second)
    first = build_player_observation(state, 0)
    wanted = OfferProposal(Offer(1, (1, 0), (0,)))
    avoided = replace(first, own_preferences=(Preference.AVOID, Preference.AVOID))
    assert policy.proposal_probability(first, wanted) > policy.proposal_probability(avoided, wanted)


def test_partial_progress_produces_evidence_but_last_turn_uses_terminal_utility():
    state = GameState(spec())
    offer = Offer(1, (1, 0), (1,))  # G0 still requires P2.
    obs = build_player_observation(state, 1, pending_proposer_id=0, pending_offer=offer)
    policy = SoftProgressPolicy()
    accept = ResponseAction("ACCEPT")
    # Phi gain = 0.5 * 2/3; softmax temperature = 0.5, mixture = 0.02.
    assert policy.response_probability(obs, offer, accept) == pytest.approx(
        0.01 + 0.98 / (1 + math.exp(-2 / 3))
    )
    avoid = replace(obs, own_preferences=(Preference.AVOID, Preference.NEUTRAL))
    assert policy.response_probability(avoid, offer, accept) < 0.5
    final = replace(obs, round_robin=(0,))
    assert policy.response_probability(final, offer, accept) == pytest.approx(0.5)
    # Entirely neutral preferences produce an exactly uniform proposer policy.
    neutral = replace(build_player_observation(state, 0), own_preferences=(Preference.NEUTRAL,) * 2)
    distribution = policy.proposal_distribution(neutral)
    assert all(p == pytest.approx(1 / len(distribution)) for _, p in distribution)


def test_distributions_normalized_seeded_and_queries_do_not_consume_randomness():
    obs = build_player_observation(GameState(spec()), 0)
    first, second = SoftProgressPolicy(seed=42), SoftProgressPolicy(seed=42)
    distribution = first.proposal_distribution(obs)
    assert math.fsum(p for _, p in distribution) == pytest.approx(1)
    assert all(p > 0 for _, p in distribution)
    assert {a.offer for a, _ in distribution if isinstance(a, OfferProposal)} == set(obs.legal_offers)
    assert first.proposal_probability(obs, OfferProposal(Offer(1, (0, 0), (0,)))) == 0
    for _ in range(20):
        first.proposal_distribution(obs)
        assert first.propose(obs) == second.propose(obs)
    # Empirical samples agree with the likelihood exposed to the future filter.
    response_obs = build_player_observation(
        GameState(spec()), 1, pending_proposer_id=0, pending_offer=Offer(1, (1, 0), (1,))
    )
    offer = response_obs.pending_offer
    probability = first.response_probability(response_obs, offer, ResponseAction("ACCEPT"))
    samples = [first.respond(response_obs, offer).accepted for _ in range(4000)]
    assert abs(sum(samples) / len(samples) - probability) < 0.04
    assert first.proposal_distribution(replace(obs, legal_offers=())) == ((PassProposal(), 1.0),)


def test_controlled_policy_runs_private_episodes_reproducibly():
    game = generate_game(7)
    def run():
        return GameRunner(game, [SoftProgressPolicy(seed=i) for i in range(3)]).run().to_dict()
    first = run()
    assert first == run()
    assert first["invalid_action_count"] == 0
    assert len(first["transcript"]) == len(game.round_robin)


def test_controlled_policy_rejects_missing_preferences_and_wrong_phase():
    state = GameState(spec())
    policy = SoftProgressPolicy()
    with pytest.raises(ValueError, match="own preferences"):
        policy.proposal_distribution(build_player_observation(state, 0, mode="public"))
    with pytest.raises(ValueError, match="proposer"):
        policy.proposal_distribution(build_player_observation(state, 1))
    with pytest.raises(ValueError, match="pending offer"):
        policy.response_distribution(build_player_observation(state, 1), Offer(1, (1, 0), (1,)))


@pytest.mark.parametrize("kwargs", [
    {"temperature": 0}, {"temperature": float("nan")}, {"progress_weight": -1},
    {"uniform_mix": 0}, {"uniform_mix": float("inf")},
])
def test_controlled_policy_rejects_invalid_parameters(kwargs):
    with pytest.raises(ValueError):
        SoftProgressPolicy(**kwargs)
