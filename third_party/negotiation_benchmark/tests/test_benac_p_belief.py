"""Independent enumeration, phase order, and information-boundary checks."""

from dataclasses import replace
from itertools import product
import math

import numpy as np
import pytest

from benac_p import (
    ActionRef, BeliefLimitError, BeliefState, ConditionalPreferencePrior, ExactBayesFilter,
    GameSpec, GameState, Goal, Offer, OfferProposal, PassProposal, Preference,
    ResponseAction, SoftProgressPolicy, build_player_observation, generate_game,
)
from benac_p.belief_demo import run_demo
from benac_p.schema import VALUE_TO_PREFERENCE, PREFERENCE_TO_VALUE


def make_spec():
    return GameSpec(
        n_players=3, n_actions_per_player=(2, 2, 2),
        goals=(Goal(0, (ActionRef(0, 0), ActionRef(1, 0))),
               Goal(1, (ActionRef(1, 1), ActionRef(2, 1)))),
        private_preferences=np.array([[1, 0], [1, -1], [1, 1]], dtype=np.int8),
        round_robin=(0, 1, 2, 0, 1, 2), max_changes=1, seed=13,
    )


def test_conditional_prior_preserves_generator_correlations():
    obs = build_player_observation(GameState(make_spec()), 0)
    prior = ConditionalPreferencePrior().initialize(obs)
    assert len(prior.hypotheses) == 24
    assert math.fsum(prior.probabilities) == pytest.approx(1)
    # Each partner's WANT-containing rows weigh .64 total; (WANT,NEUTRAL)
    # weighs .08. Conditioning excludes the joint .08*.08 event.
    assert prior.marginals()["P1"]["G1"]["NEUTRAL"] == pytest.approx(1 / 9)
    assert not any(h[0][1] == h[1][1] == Preference.NEUTRAL for h in prior.hypotheses)
    nonneutral_ego = replace(obs, own_preferences=(Preference.WANT, Preference.AVOID))
    independent = ConditionalPreferencePrior().initialize(nonneutral_ego)
    assert len(independent.hypotheses) == 25
    assert independent.marginals()["P1"]["G1"]["NEUTRAL"] == pytest.approx(1 / 8)


def test_prior_matches_independent_full_matrix_enumeration_with_custom_weights():
    obs = build_player_observation(GameState(make_spec()), 0)
    probabilities = {1: 0.5, 0: 0.3, -1: 0.2}
    expected = {}
    for flat in product((1, 0, -1), repeat=6):
        matrix = np.array(flat).reshape(3, 2)
        if tuple(matrix[0]) != (1, 0):
            continue
        if not all(1 in row for row in matrix) or any(all(matrix[:, g] == 0) for g in range(2)):
            continue
        hypothesis = tuple(tuple(VALUE_TO_PREFERENCE[v] for v in row) for row in matrix[1:])
        expected[hypothesis] = math.prod(probabilities[v] for v in flat)
    normalizer = sum(expected.values())
    actual = ConditionalPreferencePrior((0.5, 0.3, 0.2)).initialize(obs)
    assert dict(zip(actual.hypotheses, actual.probabilities)) == pytest.approx(
        {h: p / normalizer for h, p in expected.items()}
    )


def test_ego_actions_do_not_update_belief_but_partner_response_does():
    state = GameState(make_spec())
    tracker = ExactBayesFilter(build_player_observation(state, 0))
    before = tracker.belief
    offer = Offer(1, (0, 0), (0, 1))
    tracker.observe_proposal(OfferProposal(offer))
    assert tracker.belief == before
    assert tracker.updates[-1]["is_evidence"] is False
    tracker.observe_response("ACCEPT")
    after = tracker.belief
    # One half of G1 completed: conditional progress gain = V_1,G1 * .25.
    weights = []
    for h, p in zip(before.hypotheses, before.probabilities):
        value = PREFERENCE_TO_VALUE[h[0][1]]
        likelihood = 0.01 + 0.98 / (1 + math.exp(-value * 0.5))
        weights.append(p * likelihood)
    expected = np.array(weights) / sum(weights)
    assert after.probabilities == pytest.approx(expected)
    assert after != before
    assert tracker.log_evidence == pytest.approx(math.log(sum(weights)))


def test_pending_partner_offer_updates_before_ego_response_exactly_once():
    state = GameState(make_spec())
    state.apply_pass()  # Ego intervention, now P1 proposes.
    tracker = ExactBayesFilter(build_player_observation(state, 0))
    offer = Offer(0, (0, 1), (0, 0))
    pending = build_player_observation(state, 0, pending_proposer_id=1, pending_offer=offer)
    before = tracker.belief
    tracker.synchronize(pending)
    assert tracker.belief != before
    assert tracker.turn_index == 1 and tracker.pending_offer == offer
    after_offer = tracker.belief
    count = len(tracker.updates)
    tracker.synchronize(pending)
    assert len(tracker.updates) == count and tracker.belief == after_offer
    state.resolve_offer(offer, "REJECT")  # Ego response is not evidence.
    tracker.synchronize(build_player_observation(state, 0))
    assert tracker.belief == after_offer
    assert len(tracker.updates) == count + 1
    assert tracker.updates[-1]["is_evidence"] is False


def test_full_history_posterior_matches_independent_likelihood_product():
    spec = make_spec()
    state = GameState(spec)
    state.apply_pass()
    state.resolve_offer(Offer(2, (0, 1), (0, 1)), "REJECT")  # P1 -> P2
    state.resolve_offer(Offer(0, (1, 0), (1, 0)), "ACCEPT")  # P2 -> ego
    tracker = ExactBayesFilter(build_player_observation(state, 0))
    weights = []
    # Independent direct joint likelihood on each fully specified hypothetical world.
    for h, p in zip(tracker.prior.hypotheses, tracker.prior.probabilities):
        matrix = np.array([[1, 0]] + [[PREFERENCE_TO_VALUE[v] for v in row] for row in h])
        world = GameState(replace(spec, private_preferences=matrix))
        likelihood = 1.0
        for event in state.transcript:
            actor = world.current_proposer()
            policy = SoftProgressPolicy(seed=99)
            action = PassProposal() if event.action == "PASS" else OfferProposal(event.offer)
            if actor != 0:
                likelihood *= policy.proposal_probability(build_player_observation(world, actor), action)
            if event.action == "PASS":
                world.apply_pass()
            else:
                if event.partner_id != 0:
                    obs = build_player_observation(world, event.partner_id,
                        pending_proposer_id=actor, pending_offer=event.offer)
                    likelihood *= policy.response_probability(obs, event.offer, ResponseAction(event.response))
                world.resolve_offer(event.offer, event.response)
        weights.append(p * likelihood)
    assert tracker.belief.probabilities == pytest.approx(np.array(weights) / sum(weights))


def test_no_information_kernel_and_policy_parameter_snapshot():
    obs = build_player_observation(GameState(make_spec()), 0)
    policies = {i: SoftProgressPolicy(uniform_mix=1) for i in (1, 2)}
    tracker = ExactBayesFilter(obs, partner_policies=policies)
    policies[1].uniform_mix = 0.02  # Caller mutation must not change the filter model.
    tracker.observe_proposal(PassProposal())
    tracker.observe_proposal(OfferProposal(Offer(2, (0, 1), (0, 1))))
    tracker.observe_response("ACCEPT")
    assert tracker.belief.probabilities == pytest.approx(tracker.prior.probabilities)
    assert tracker.specification()["partner_policies"]["1"]["uniform_mix"] == 1


def test_filter_ignores_true_other_preferences_and_seed_even_with_full_view():
    spec = make_spec()
    altered = replace(spec, private_preferences=np.array([[1, 0], [-1, 1], [0, 1]]), seed=99)
    trackers = []
    for game in (spec, altered):
        state = GameState(game)
        state.apply_pass()
        state.resolve_offer(Offer(2, (0, 1), (0, 1)), "ACCEPT")
        trackers.append(ExactBayesFilter(build_player_observation(state, 0, mode="full")))
    assert trackers[0].belief == trackers[1].belief
    assert trackers[0].specification() == trackers[1].specification()


def test_inconsistent_history_is_rejected_atomically_and_duplicate_response_rejected():
    state = GameState(make_spec())
    initial = build_player_observation(state, 0)
    tracker = ExactBayesFilter(initial)
    state.resolve_offer(Offer(1, (1, 0), (1, 0)), "ACCEPT")
    valid = build_player_observation(state, 0)
    bad_event = replace(valid.transcript[0], commitments_after=initial.commitments)
    with pytest.raises(ValueError, match="transition"):
        tracker.synchronize(replace(valid, transcript=(bad_event,)))
    assert tracker.turn_index == 0 and tracker.belief == tracker.prior and not tracker.updates
    tracker.synchronize(valid)
    with pytest.raises(ValueError, match="already consumed"):
        tracker.observe_response("ACCEPT")
    with pytest.raises(ValueError, match="stale"):
        tracker.synchronize(initial)
    assert tracker.turn_index == 1
    tracker.synchronize(valid)
    assert len(tracker.updates) == 2


def test_incompatible_prior_and_large_support_fail_explicitly():
    with pytest.raises(BeliefLimitError, match="43046721"):
        ExactBayesFilter(build_player_observation(GameState(generate_game(0)), 0))
    obs = build_player_observation(GameState(make_spec()), 0)
    with pytest.raises(ValueError, match="zero probability"):
        ConditionalPreferencePrior((1, 0, 0)).initialize(obs)
    with pytest.raises(ValueError, match="own preferences"):
        ConditionalPreferencePrior().initialize(replace(obs, own_preferences=None))
    with pytest.raises(ValueError, match="zero probability"):
        ConditionalPreferencePrior().initialize(replace(obs, own_preferences=(Preference.NEUTRAL,) * 2))
    with pytest.raises(ValueError, match="nonnegative"):
        ConditionalPreferencePrior((float("nan"), 0.2, 0.4))


def test_belief_owns_immutable_normalized_inputs():
    rows = [[["WANT", "NEUTRAL"]]]
    belief = BeliefState([1], rows, [0.0])
    rows[0][0][0] = "AVOID"
    assert belief.marginals()["P1"]["G0"]["WANT"] == 1
    with pytest.raises(ValueError, match="normalized"):
        BeliefState((1,), belief.hypotheses, (1.0,))
    with pytest.raises(ValueError, match="preference rows"):
        BeliefState((1,), ((),), (0.0,))


@pytest.mark.parametrize("ego_id", (0, 1, 2))
def test_seeded_smoke_stream_replay_and_reproducibility(ego_id):
    first = run_demo(seed=3, ego_id=ego_id)
    second = run_demo(seed=3, ego_id=ego_id)
    assert first.pop("elapsed_seconds") > 0
    second.pop("elapsed_seconds")
    assert first == second
    assert first["stream_replay_max_probability_error"] < 1e-12
    assert len(first["transcript"]) == 6
    assert any(u["is_evidence"] for u in first["updates"])
