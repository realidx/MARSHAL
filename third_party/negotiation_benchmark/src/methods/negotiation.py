"""
negotiation.py

Negotiation strategies and terminal value estimation for multi-player
bilateral negotiation games.

Provides:
- Exact solvers (``create_solver``, ``create_solver_k_step``) using memoised
  backward induction over the full or k-step game tree.
- Terminal value estimators (``estimate_terminal_value``) supporting multiple
  methods: exact, k-step exact, reward, upper/lower bounds, and analytic
  approximations.
- Bound functions (``estimate_upper_bound``, ``estimate_lower_bound``,
  ``estimate_tighter_upper_bound``, ``estimate_tighter_lower_bound``) for
  fast non-exact value estimates.
- An offer-search function (``get_best_offer``) and a factory
  (``create_negotiation_functions``) for binding parameters into a reusable
  callable.
"""

from functools import lru_cache
from typing import Optional

import numpy as np
from core.game_logic import (
    best_offer_linear_greedy,
    get_all_joint_actions,
    get_goal_satisfaction,
)
from core.game_state import NegotiationState

MAX_CHANGES = 2


def state_key(state):
    """
    Compute a hashable cache key for a game state.

    Args:
        state (NegotiationState): Current game state.

    Returns:
        tuple: ``(turn_index, P_bytes)`` where ``P_bytes`` is the policy
            matrix serialised to bytes.
    """
    return (state.idx, state.P.tobytes())


def create_solver(root_state):
    """
    Create a memoised full-horizon exact solver for a given game instance.

    Solves the game to completion by backward induction, evaluating every
    possible joint action at every turn for every legal partner. A deal is
    accepted by the partner if it weakly improves their payoff over rejection.
    The proposer selects the offer that maximises their own terminal payoff.

    Prints periodic progress every 500,000 unique states solved.

    Args:
        root_state (NegotiationState): The game state at the root, used to
            extract fixed game parameters.

    Returns:
        callable: A memoised function ``v(state_key) -> (payoffs,
            hist_partners, hist_actions, hist_P)`` where:
            - ``payoffs`` (np.ndarray): Optimal terminal payoff vector.
            - ``hist_partners`` (list of tuple): ``(proposer, partner)`` pairs
              along the optimal path.
            - ``hist_actions`` (list): Joint actions along the optimal path.
            - ``hist_P`` (list of np.ndarray): Policy matrix snapshots at
              each step of the optimal path.
    """
    n_players = root_state.n_players
    n_actions = root_state.n_actions
    n_turns = root_state.n_turns
    G = root_state.G
    sat_masks = root_state.sat_masks
    country_idx2num_actions = root_state.country_idx2num_actions
    seed = root_state.seed
    binary_goals = root_state.binary_goals
    forbidden_actions = root_state.forbidden_actions

    total_turns = len(root_state.round_robin)
    solved_count = 0

    def state_key(s):
        return (s.idx, s.P.tobytes())

    @lru_cache(maxsize=None)
    def v_exact_internal(state_bytes_tuple):

        nonlocal solved_count
        solved_count += 1

        if solved_count % 500_000 == 0:
            current_turn = state_bytes_tuple[0]
            print(
                f"Solver Progress: {solved_count:,} unique states solved. "
                f"Currently processing Turn {current_turn}/{total_turns} "
                f"(Cache Info: {v_exact_internal.cache_info()})"
            )

        state = NegotiationState(
            n_players=n_players,
            n_actions=n_actions,
            n_turns=n_turns,
            G=G,
            sat_masks=sat_masks,
            country_idx2num_actions=country_idx2num_actions,
            seed=seed,
            binary_goals=binary_goals,
        )
        # state.round_robin = [0, 1, 2]

        state.idx = state_bytes_tuple[0]
        state.P = (
            np.frombuffer(state_bytes_tuple[1], dtype=np.uint8)
            .reshape(n_players, n_actions)
            .copy()
        )

        if state.is_terminal():
            return state.get_payoff_vector(), [], [], [state.P.copy()]

        p = state.proposer()
        legal = state.legal_negotiation_partners()

        s_rej = state.clone()
        s_rej.reject_deal()

        V_rej, hist_p_rej, hist_a_rej, hist_P_rej = v_exact_internal(state_key(s_rej))

        res_rej = (
            V_rej,
            [(p, None)] + hist_p_rej,
            [None] + hist_a_rej,
            [state.P.copy()] + hist_P_rej,
        )

        best_over_partners = res_rej
        for q in legal:
            best_with_q = None
            offers = get_all_joint_actions(
                P=state.P,
                p1=p,
                p2=q,
                country_idx2num_actions=country_idx2num_actions,
                max_changes=MAX_CHANGES,
                allowed_actions=None,
                forbidden_actions=forbidden_actions,
            )
            for offer in offers:
                s_acc = state.clone()
                s_acc.play_deal(offer, q)

                V_acc, hist_p_acc, hist_a_acc, hist_P_acc = v_exact_internal(
                    state_key(s_acc)
                )

                if V_acc[q] >= V_rej[q]:
                    candidate = (
                        V_acc,
                        [(p, q)] + hist_p_acc,
                        [offer] + hist_a_acc,
                        [state.P.copy()] + hist_P_acc,
                    )
                    if (best_with_q is None) or (candidate[0][p] > best_with_q[0][p]):
                        best_with_q = candidate

            if (best_with_q is not None) and (
                best_with_q[0][p] > best_over_partners[0][p]
            ):
                best_over_partners = best_with_q

        return best_over_partners

    return v_exact_internal


def estimate_upper_bound(state, player_idx: int) -> float:
    """
    Compute an optimistic upper bound on a player's terminal payoff.

    Adds the maximum possible gain from all positively-valued, unsatisfied
    goals to the current payoff, assuming every such goal will be fully
    satisfied. This ignores feasibility and cooperation constraints.

    Args:
        state (NegotiationState): Current game state.
        player_idx (int): Index of the player to estimate value for.

    Returns:
        float: Upper bound on the player's terminal payoff.
    """
    current_payoff = state.get_payoff_vector()[player_idx]
    s = get_goal_satisfaction(state.P.copy(), state.sat_masks)
    u = 1.0 - s
    remaining = 0

    G = state.G  # (num_goals, num_players)

    for goal_idx in range(G.shape[0]):
        goal_value = G[goal_idx, player_idx]
        if goal_value > 0 and u[goal_idx] > 0:
            remaining += goal_value * u[goal_idx]

    return current_payoff + remaining


def estimate_lower_bound(state, player_idx: int) -> float:
    """
    Compute a pessimistic lower bound on a player's terminal payoff.

    Adds the maximum possible loss from all negatively-valued, unsatisfied
    goals to the current payoff, assuming every such harmful goal will be
    fully satisfied against the player's interest.

    Args:
        state (NegotiationState): Current game state.
        player_idx (int): Index of the player to estimate value for.

    Returns:
        float: Lower bound on the player's terminal payoff.
    """
    current_payoff = state.get_payoff_vector()[player_idx]
    s = get_goal_satisfaction(state.P.copy(), state.sat_masks)
    u = 1.0 - s
    remaining = 0

    G = state.G  # (num_goals, num_players)

    for goal_idx in range(G.shape[0]):
        goal_value = G[goal_idx, player_idx]
        if goal_value < 0 and u[goal_idx] > 0:
            remaining += goal_value * u[goal_idx]

    return current_payoff + remaining


def estimate_tighter_lower_bound(state, player_idx):
    """
    Compute a tighter lower bound by filtering out irrational threats.

    Extends ``estimate_lower_bound`` by only counting a harmful goal's loss
    if all opponents who would need to act to satisfy it actually have a
    non-negative valuation for it (i.e. they have a rational incentive to
    pursue it). Goals requiring at least one opponent who dislikes them are
    excluded as non-credible threats.

    Note: This bound is most accurate for binary goals. For linear goals it
    may still be loose if only one opponent is needed.

    Args:
        state (NegotiationState): Current game state.
        player_idx (int): Index of the player to estimate value for.

    Returns:
        float: Tighter lower bound on the player's terminal payoff.
    """

    # TODO: Good for binary goals but could tighten for linear goals by not setting is_rational_threat = False if only 1 opponent that can helps
    # the goal don't like it either and taking into account other as well
    # Could also thighten even more if take into account the number of actions needed when opponent_needed = np.count_nonzero(
    #     (mask[p_other] == 1) & (state.P[p_other] == 0)
    # )

    current_payoff = state.get_payoff_vector()[player_idx]
    remaining_loss = 0

    G = state.G
    s = get_goal_satisfaction(state.P, state.sat_masks)

    for g_idx in range(len(G)):
        val = G[g_idx, player_idx]
        if val >= 0 or s[g_idx] >= 1.0:
            continue

        mask = state.sat_masks[g_idx]

        is_rational_threat = True
        for p_other in range(state.n_players):
            if p_other == player_idx:
                continue

            opponent_needed = np.count_nonzero(
                (mask[p_other] == 1) & (state.P[p_other] == 0)
            )
            if opponent_needed > 0:
                if G[g_idx, p_other] < 0:
                    is_rational_threat = False
                    break

        if is_rational_threat:
            remaining_loss += val

    return current_payoff + remaining_loss


def estimate_tighter_upper_bound(state, player_idx):
    """
    Compute a tighter upper bound by filtering out irrational opportunities.

    Extends ``estimate_upper_bound`` by only counting a beneficial goal's
    gain if all opponents who would need to act to satisfy it have a
    non-negative valuation for it (i.e. they have a rational incentive to
    cooperate). Goals requiring at least one opponent who dislikes them are
    excluded as unreachable.

    Args:
        state (NegotiationState): Current game state.
        player_idx (int): Index of the player to estimate value for.

    Returns:
        float: Tighter upper bound on the player's terminal payoff.
    """

    current_payoff = state.get_payoff_vector()[player_idx]
    remaining_gain = 0

    G = state.G
    s = get_goal_satisfaction(state.P, state.sat_masks)

    for g_idx in range(len(G)):
        val = G[g_idx, player_idx]

        if val <= 0 or s[g_idx] >= 1.0:
            continue

        mask = state.sat_masks[g_idx]

        is_rational_opportunity = True
        for p_other in range(state.n_players):
            if p_other == player_idx:
                continue

            opponent_needed = np.count_nonzero(
                (mask[p_other] == 1) & (state.P[p_other] == 0)
            )

            if opponent_needed > 0:
                if G[g_idx, p_other] < 0:
                    is_rational_opportunity = False
                    break

        if is_rational_opportunity:
            remaining_gain += val

    return current_payoff + remaining_gain


def estimate_terminal_value(
    *,
    state,
    offer: Optional[np.ndarray],
    player_idx: int,
    partner_idx: int,
    how: str,
    max_changes: int,
    model,
    k: int,
) -> float:
    """
    Estimate the terminal payoff for a player given a potential offer.

    Applies the offer to a cloned state (or rejects if ``offer`` is None),
    then evaluates the resulting state using the specified method. For
    non-terminal states, most methods fall back to the current payoff vector
    when the state is already terminal.

    Supported values of ``how``:
        - ``"reward"``: Current payoff from the (post-offer) state.
        - ``"upper"``: Optimistic upper bound (see ``estimate_upper_bound``).
        - ``"lower"``: Pessimistic lower bound (see ``estimate_lower_bound``).
        - ``"upper_tighter"``: Tighter upper bound filtering irrational
          opportunities.
        - ``"lower_tighter"``: Tighter lower bound filtering irrational
          threats.
        - ``"lower_reward_plus"``: Lower bound early in the game, switching
          to actual reward in the final turns.
        - ``"lower_reward_less"``: Lower bound until near the last round,
          then actual reward.
        - ``"exact"``: Full-horizon exact solver (expensive).


    Args:
        state (NegotiationState): Current game state (will be cloned
            internally; the original is not modified).
        offer (tuple or None): Joint action to apply. If None, the deal is
            rejected and the turn advances.
        player_idx (int): Index of the player to estimate value for.
        partner_idx (int): Index of the partner in the proposed deal.
        how (str): Estimation method (see above).
        max_changes (int): Action budget, passed to solvers that need it.
        model: Neural network model, used only by ``"value_model"`` (not
            currently active).
        k (int): Lookahead depth for ``"k_step_exact"``.

    Returns:
        float: Estimated terminal payoff for ``player_idx``.

    Raises:
        ValueError: If ``how`` is not a recognised estimation method.
    """
    # Apply action to cloned state
    tmp_state = state.clone()
    if offer is None:
        tmp_state.reject_deal()
    else:
        tmp_state.play_deal(offer, partner_idx)

    # Estimate value based on method
    if how == "reward":
        return tmp_state.get_payoff_vector()[player_idx]

    elif how == "upper":
        if tmp_state.is_terminal():
            return tmp_state.get_payoff_vector()[player_idx]

        return estimate_upper_bound(tmp_state, player_idx)

    elif how == "lower":
        if tmp_state.is_terminal():
            return tmp_state.get_payoff_vector()[player_idx]

        return estimate_lower_bound(tmp_state, player_idx)

    elif how == "lower_tighter":
        if tmp_state.is_terminal():
            return tmp_state.get_payoff_vector()[player_idx]

        return estimate_tighter_lower_bound(tmp_state, player_idx)

    elif how == "upper_tighter":
        if tmp_state.is_terminal():
            return tmp_state.get_payoff_vector()[player_idx]

        return estimate_tighter_upper_bound(tmp_state, player_idx)

    elif how == "lower_reward_plus":
        if tmp_state.is_terminal():
            return tmp_state.get_payoff_vector()[player_idx]

        lower_bound = estimate_lower_bound(tmp_state, player_idx)
        actual_reward = tmp_state.get_payoff_vector()[player_idx]
        if tmp_state.idx >= tmp_state.n_players - 1:
            return actual_reward
        else:
            return lower_bound

    elif how == "lower_reward_less":
        if tmp_state.is_terminal():
            return tmp_state.get_payoff_vector()[player_idx]

        lower_bound = estimate_lower_bound(tmp_state, player_idx)
        actual_reward = tmp_state.get_payoff_vector()[player_idx]
        if (
            tmp_state.idx
            >= tmp_state.n_turns * tmp_state.n_players - tmp_state.n_players - 1
        ):
            return actual_reward
        else:
            return lower_bound

    elif how == "exact":
        if tmp_state.is_terminal():
            return tmp_state.get_payoff_vector()[player_idx]

        solver = create_solver(tmp_state)
        V = solver(state_key(tmp_state))[0]
        return V[player_idx]

    else:
        raise ValueError(f"Unknown estimation method: {how}")


# ============================================================================
# Negotiation Functions
# ============================================================================


def get_best_offer(
    state, p2, max_changes, how, model, allowed_actions, forbidden_actions, k
):
    """
    Find the best offer for the current proposer to make to partner ``p2``.

    Evaluates all feasible joint actions and returns the one that maximises
    the proposer's estimated terminal value subject to the partner's
    acceptance constraint (the partner accepts only if the offer gives them
    at least as much as rejection).

    When ``how == "reward"``, the greedy linear offer function is used
    directly instead of exhaustive search. For all other methods (including
    ``"mix:<method1>_<method2>"`` variants), every joint action in the
    feasible set is evaluated.

    Args:
        state (NegotiationState): Current game state.
        p2 (int): Index of the partner player.
        max_changes (int): Maximum number of 0→1 action flips per player.
        how (str): Value estimation method, passed to
            ``estimate_terminal_value``. Supports a ``"mix:<m1>_<m2>"``
            syntax to use different methods for proposer and partner.
        model: Model object passed through to ``estimate_terminal_value``
            (only relevant for model-based methods).
        allowed_actions (np.ndarray or None): Binary mask of permitted
            actions per player.
        forbidden_actions (np.ndarray or None): Binary mask of forbidden
            actions per player.
        k (int): Lookahead depth for k-step exact methods.

    Returns:
        tuple:
            - best_offer (tuple or None): The best feasible joint action,
              or None if no offer improves on rejection.
            - best_p1 (float): The proposer's estimated terminal value under
              the best offer (equals rejection value if no offer is found).
    """

    epsilon = 1e-10
    p1 = state.proposer()

    how_p1, how_p2 = how, how
    mixed = False
    if isinstance(how, str):
        how_clean = how.replace(":", "_").replace(" ", "_")
        parts = [p for p in how_clean.split("_") if p]
        if len(parts) == 3 and parts[0] == "mix":
            mixed = True
            how_p1, how_p2 = parts[1], parts[2]

    p2_reject = estimate_terminal_value(
        state=state.clone(),
        offer=None,
        player_idx=p2,
        partner_idx=None,
        how=how_p2,
        max_changes=max_changes,
        model=model,
        k=k,
    )

    p1_reject = estimate_terminal_value(
        state=state.clone(),
        offer=None,
        player_idx=p1,
        partner_idx=None,
        how=how_p1,
        max_changes=max_changes,
        model=model,
        k=k,
    )

    best_offer = None
    best_p1 = p1_reject

    if (not mixed) and how == "reward_fast":
        best_offer, _ = best_offer_linear_greedy(
            state=state,
            partner=p2,
            max_changes=max_changes,
            how="reward",
            allowed_actions=None,
            forbidden_actions=None,
            eps=1e-12,
        )

    else:
        offers = get_all_joint_actions(
            P=state.P,
            p1=p1,
            p2=p2,
            country_idx2num_actions=state.country_idx2num_actions,
            max_changes=max_changes,
            allowed_actions=allowed_actions,
            forbidden_actions=forbidden_actions,
        )
        for offer in offers:
            # 1) Check p1 improvement first; if not better, skip p2 computation

            p1_val = estimate_terminal_value(
                state=state.clone(),
                offer=offer,
                player_idx=p1,
                partner_idx=p2,
                how=how_p1,
                max_changes=max_changes,
                model=model,
                k=k,
            )
            if p1_val + epsilon < best_p1:
                continue

            # 2) Now check if p2 would accept

            p2_val = estimate_terminal_value(
                state=state.clone(),
                offer=offer,
                player_idx=p2,
                partner_idx=p2,
                how=how_p2,
                max_changes=max_changes,
                model=model,
                k=k,
            )
            if p2_val >= p2_reject:
                best_offer = offer
                best_p1 = p1_val
                best_p2 = p2_val

    return best_offer, best_p1


def create_negotiation_functions(
    how: str, max_changes: int, model, allowed_actions, forbidden_actions, k: int
):
    """
    Create a ``get_best_offer`` callable with pre-bound parameters.

    Useful for passing a configured offer function to MCTS or other search
    routines without threading all parameters through each call.

    Args:
        how (str): Value estimation method for ``get_best_offer``.
        max_changes (int): Maximum action flips per player per turn.
        model: Model passed through to ``estimate_terminal_value``.
        allowed_actions (np.ndarray or None): Permitted action mask.
        forbidden_actions (np.ndarray or None): Forbidden action mask.
        k (int): Lookahead depth for k-step exact methods.

    Returns:
        callable: A function ``get_best_offer_fn(state, partner) ->
            (offer, value)`` with all other parameters bound.
    """

    def get_best_offer_fn(state, partner):
        return get_best_offer(
            state,
            partner,
            max_changes,
            how,
            model,
            allowed_actions,
            forbidden_actions,
            k,
        )

    return get_best_offer_fn
