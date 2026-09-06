"""Bayesian planning verified against analytic values and explicit policy trees."""

from dataclasses import replace
from itertools import product
import math

import numpy as np
import pytest

from benac_p import (
    ActionRef, BayesPlanner, BayesPlannerLimitError, BeliefState, ExactBayesFilter,
    GameSpec, GameState, Goal, Offer, OfferProposal, PassProposal, Preference,
    ResponseAction, SoftProgressPolicy, build_player_observation,
)
from benac_p.belief import condition_belief
from benac_p.planner_demo import belief_choice_spec, run_demo


def test_last_turn_values_equal_posterior_predictive_acceptance():
    state = GameState(belief_choice_spec())
    state.apply_pass()
    observation = build_player_observation(state, 0)
    belief = ExactBayesFilter(observation).belief
    result = BayesPlanner().solve(observation, belief)
    for value in result.action_values:
        if isinstance(value.action, PassProposal):
            assert value.value == 0
            continue
        offer = value.action.offer
        accepted = state.clone()
        accepted.resolve_offer(offer, "ACCEPT")
        column = belief.partner_ids.index(offer.partner_id)
        expected_acceptance = 0.0
        for h, weight in zip(belief.hypotheses, belief.probabilities):
            # Analytic final-turn sigmoid of that partner's actual utility change.
            values = {Preference.WANT: 1, Preference.NEUTRAL: 0, Preference.AVOID: -1}
            gain = sum(values[v] * s for v, s in zip(h[column], accepted.goal_satisfaction()))
            expected_acceptance += weight * (0.01 + 0.98 / (1 + math.exp(-gain / 0.5)))
        assert value.value == pytest.approx(expected_acceptance * accepted.reward(0))


def test_matched_histories_change_best_partner_with_positive_regret():
    demo = run_demo()
    first, second = demo["belief_choice_cases"]
    for key in ("binding_commitments", "turn_index", "current_proposer", "pending_offer", "round_robin"):
        assert first["observation"][key] == second["observation"][key]
    assert first["planning"]["action"]["partner_id"] == 1
    assert second["planning"]["action"]["partner_id"] == 2
    assert first["regret_of_other_history_action"] > 0.2
    assert second["regret_of_other_history_action"] > 0.19


def test_long_horizon_accounts_for_third_party_not_partial_reward():
    case = run_demo()["third_party_continuation"]
    assert set(case["all_one_offer_snapshot_utilities"]) == {0}
    assert case["planning"]["action"]["action"] == "OFFER"
    assert case["regret_of_pass"] > 0.1
    # PASS leaves only P2's bilateral turn, which cannot finish the three-way goal.
    assert next(v["value"] for v in case["planning"]["action_values"] if v["action"]["action"] == "PASS") == 0


def test_supplied_belief_not_true_state_history_or_previous_solver_call():
    spec = belief_choice_spec()
    state = GameState(spec)
    state.apply_pass()
    obs = build_player_observation(state, 0, mode="full")
    want, avoid = Preference.WANT, Preference.AVOID
    left = BeliefState((1, 2), (((want, avoid), (want, avoid)),), (0.0,))
    right = BeliefState((1, 2), (((avoid, want), (avoid, want)),), (0.0,))
    planner = BayesPlanner()
    first = planner.solve(obs, left)
    assert first.action.offer.partner_id == 1
    assert planner.solve(obs, right).action.offer.partner_id == 2
    changed = replace(obs, transcript=(), all_preferences=None, legal_offers=())
    assert planner.solve(changed, left) == first
    # A mixture must not choose a separate action in each hidden world.
    mixed = BeliefState((1, 2), left.hypotheses + right.hypotheses, (math.log(.5),) * 2)
    mixed_result = planner.solve(obs, mixed)
    assert mixed_result.value == pytest.approx(0.5)
    clairvoyant = (first.value + planner.solve(obs, right).value) / 2
    assert clairvoyant - mixed_result.value > 0.3
    assert planner.solve(obs, left) == first


def test_pending_response_uses_supplied_belief_without_recounting_proposal():
    state = GameState(belief_choice_spec())
    offer = Offer(0, (1,), (1, 0))
    obs = build_player_observation(state, 0, pending_proposer_id=1, pending_offer=offer)
    belief = ExactBayesFilter(obs).belief
    planner = BayesPlanner()
    response = planner.solve(obs, belief)
    assert isinstance(response.action, ResponseAction)
    assert response.action.accepted
    for item in response.action_values:
        child = state.clone()
        child.resolve_offer(offer, item.action)
        expected = planner.solve(build_player_observation(child, 0), belief)
        assert item.value == pytest.approx(expected.value)


def policy_tree_vectors(state, belief, pending=None):
    """Independent alpha-vector enumeration. No posterior updates or planner calls.

    Each vector scores a complete contingent ego policy in every hidden world.
    At chance nodes, Cartesian products permit different future policies after
    each public observation; at ego nodes, choices concatenate policy sets.
    """
    if state.is_terminal:
        return (np.full(len(belief.hypotheses), state.reward(0), dtype=float),)
    actor = state.current_proposer() if pending is None else pending.partner_id
    actions = (
        (PassProposal(),) + tuple(OfferProposal(o) for p in state.legal_partners() for o in state.legal_offers(p))
        if pending is None else (ResponseAction("REJECT"), ResponseAction("ACCEPT"))
    )
    children = []
    for action in actions:
        if isinstance(action, OfferProposal):
            vectors = policy_tree_vectors(state, belief, action.offer)
        else:
            child = state.clone()
            if isinstance(action, PassProposal):
                child.apply_pass()
            else:
                child.resolve_offer(pending, action)
            vectors = policy_tree_vectors(child, belief)
        children.append(vectors)
    if actor == 0:
        return tuple(vector for alternatives in children for vector in alternatives)
    probabilities = []
    for h in belief.hypotheses:
        obs = replace(build_player_observation(state, actor, mode="public",
            pending_proposer_id=state.current_proposer() if pending else None,
            pending_offer=pending), own_preferences=h[belief.partner_ids.index(actor)])
        policy = SoftProgressPolicy()
        distribution = policy.proposal_distribution(obs) if pending is None else policy.response_distribution(obs, pending)
        probabilities.append([p for _, p in distribution])
    probabilities = np.array(probabilities)
    return tuple(sum(probabilities[:, i] * vector for i, vector in enumerate(selection))
                 for selection in product(*children))


@pytest.mark.parametrize("weights", ((0.2, 0.8), (0.75, 0.25)))
def test_two_turn_search_matches_independent_contingent_policy_enumeration(weights):
    spec = GameSpec(
        n_players=2, n_actions_per_player=(1, 1),
        goals=(Goal(0, (ActionRef(0, 0), ActionRef(1, 0))),),
        private_preferences=np.array([[1], [1]], dtype=np.int8),
        round_robin=(1, 0), max_changes=1, seed=0,
    )
    state = GameState(spec)
    # Deliberately supplied diagnostic prior, not the v0 generator's 1-goal prior.
    belief = BeliefState((1,), (((Preference.WANT,),), ((Preference.AVOID,),)), tuple(map(math.log, weights)))
    vectors = policy_tree_vectors(state, belief)
    expected = max(float(np.dot(weights, vector)) for vector in vectors)
    result = BayesPlanner().solve(build_player_observation(state, 0), belief)
    assert result.action is None  # Root is the partner's stochastic proposal.
    assert result.value == pytest.approx(expected, abs=1e-12)
    assert result.nodes_expanded > 10


def test_terminal_negative_utility_and_ties():
    state = GameState(belief_choice_spec())
    state.apply_pass()
    obs = build_player_observation(state, 0)
    belief = ExactBayesFilter(obs).belief
    neutral = replace(obs, own_preferences=(Preference.NEUTRAL, Preference.NEUTRAL))
    result = BayesPlanner().solve(neutral, belief)
    assert result.action == PassProposal() and len(result.optimal_actions) == len(result.action_values)
    with pytest.raises(ValueError, match="legal ego action"):
        result.regret(ResponseAction("ACCEPT"))
    offer = Offer(1, (1, 0), (1,))
    state.resolve_offer(offer, "ACCEPT")
    terminal = replace(build_player_observation(state, 0), own_preferences=(Preference.AVOID, Preference.NEUTRAL))
    end = BayesPlanner().solve(terminal, belief)
    assert end.value == -1 and end.action is None and end.remaining_turns == 0
    with pytest.raises(ValueError, match="ego"):
        BayesPlanner().act(terminal, belief)


def test_budgets_fail_without_returning_truncated_or_partial_values():
    obs = build_player_observation(GameState(belief_choice_spec()), 0)
    belief = ExactBayesFilter(obs).belief
    with pytest.raises(BayesPlannerLimitError, match="truncated"):
        BayesPlanner(max_remaining_turns=1).solve(obs, belief)
    with pytest.raises(BayesPlannerLimitError, match="truncated"):
        BayesPlanner(max_hypotheses=1).solve(obs, belief)
    with pytest.raises(BayesPlannerLimitError, match="partial"):
        BayesPlanner(max_nodes=1).solve(obs, belief)
    with pytest.raises(ValueError, match="positive integer"):
        BayesPlanner(max_nodes=0)
    with pytest.raises(ValueError, match="ego"):
        BayesPlanner().act(obs, belief)


def test_shared_bayes_update_has_predictive_probabilities_and_zero_support_checks():
    belief = BeliefState((1,), (((Preference.WANT,),), ((Preference.AVOID,),)), (math.log(.5),) * 2)
    after, logp = condition_belief(belief, (.2, .8))
    assert after.probabilities == pytest.approx((.2, .8))
    assert math.exp(logp) == pytest.approx(.5)
    for invalid in ((0, 0), (1.1, .5), (.5,), (float("nan"), .5)):
        with pytest.raises(ValueError):
            condition_belief(belief, invalid)


def test_partner_kernel_parameters_are_respected_and_copied():
    state = GameState(belief_choice_spec())
    state.apply_pass()
    obs = build_player_observation(state, 0)
    belief = ExactBayesFilter(obs).belief
    policies = {i: SoftProgressPolicy(uniform_mix=1) for i in (1, 2)}
    planner = BayesPlanner(partner_policies=policies)
    assert planner.solve(obs, belief).value == pytest.approx(0.5)
    policies[1].uniform_mix = 0.02
    assert planner.solve(obs, belief).value == pytest.approx(0.5)
    assert BayesPlanner().solve(obs, belief).value > 0.6
    with pytest.raises(ValueError, match="one kernel"):
        BayesPlanner(partner_policies={1: SoftProgressPolicy()}).solve(obs, belief)
