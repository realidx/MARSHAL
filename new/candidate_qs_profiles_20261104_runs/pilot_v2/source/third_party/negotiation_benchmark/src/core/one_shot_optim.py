"""
one_shot_optim.py

One-shot optimisation routines for negotiation game policy matrices.

Provides two approaches for computing optimal or baseline policy matrices:

- ``baseline_solution``: A no-negotiation baseline where each player
  independently maximises their own payoff without coordinating with others.
- ``optimize_P_via_masks_with_NE``: A joint MIP optimisation that finds the
  globally optimal policy matrix subject to Nash Equilibrium participation
  constraints and goal satisfaction encoding.
"""

from itertools import product

import cvxpy as cp
import numpy as np
from config.game_configs import create_sat_masks
from core.game_logic import (
    get_payoff_per_country,
)


def baseline_solution(country_idx2num_actions, G, sat_masks, linear_goals=True):
    """
    Compute the 'No Negotiation' baseline policy.

    Each player independently selects the best combination of their own
    actions to maximise their individual payoff, assuming all other players
    take no actions.

    Two strategies are available depending on the goal structure:

    - ``linear_goals=False``: Exhaustive search. Evaluates every possible
      binary combination of the player's actions and selects the one with
      the highest payoff. Exact but exponential in the number of actions.

    - ``linear_goals=True``: Greedy single-flip search. Iterates over each
      action individually and commits to it if it improves the player's
      current payoff. Efficient and correct when goal satisfaction scales
      linearly with the number of active actions.

    Args:
        country_idx2num_actions (dict): Maps each player index to their
            number of available actions.
        G (np.ndarray): Goal valuation matrix of shape (N_GOALS, N_PLAYERS).
        sat_masks (dict): Maps each goal index to a binary satisfaction mask
            of shape (N_PLAYERS, N_ACTIONS).
        linear_goals (bool): If True, use the greedy single-flip strategy
            (suitable for linear/continuous goals). If False, use exhaustive
            search (suitable for binary/non-linear goals). Defaults to True.

    Returns:
        np.ndarray: Policy matrix of shape (N_PLAYERS, N_ACTIONS) representing
            each player's optimal unilateral strategy.
    """
    P = np.zeros(sat_masks[0].shape, dtype=np.uint8)
    N, A = P.shape

    for p_idx in range(N):
        k = country_idx2num_actions[p_idx]

        if not linear_goals:
            best_payoff = float("-inf")
            best_action_vector = np.zeros(k, dtype=np.uint8)

            for action_combo in product([0, 1], repeat=k):
                M = P.copy()
                M[p_idx, :k] = action_combo

                current_payoff = get_payoff_per_country(M, G, sat_masks)[p_idx]

                if current_payoff > best_payoff:
                    best_payoff = current_payoff
                    best_action_vector = action_combo

            P[p_idx, :k] = best_action_vector

        else:
            player_payoff = get_payoff_per_country(P.copy(), G, sat_masks)[p_idx]

            for a_idx in range(k):
                M = P.copy()
                M[p_idx, a_idx] = 1

                new_player_payoff = get_payoff_per_country(M, G, sat_masks)[p_idx]

                if new_player_payoff > player_payoff:
                    P[p_idx, a_idx] = 1
                    player_payoff = new_player_payoff

    return P


def optimize_P_via_masks_with_NE(
    game_config,
    delta=1e-3,
    objective: str = "sum",
):
    """
    Find the jointly optimal policy matrix using a Mixed Integer Program (MIP).

    Maximises a global objective over all players' payoffs subject to:
    - Per-player action availability constraints.
    - Goal satisfaction constraints (continuous or binary).
    - A minimum payoff floor (``delta``) for each player, enforcing a weak
      Nash Equilibrium participation condition.

    Goal satisfaction is encoded directly from the satisfaction masks. Binary
    goals use auxiliary boolean variables to enforce all-or-nothing semantics;
    continuous goals are expressed as a linear fraction of satisfied
    requirements. Uses MOSEK as the solver via CVXPY.

    Args:
        game_config (dict): Game configuration dictionary containing:
            - ``"G"`` (np.ndarray): Goal valuation matrix of shape
              (N_GOALS, N_PLAYERS).
            - ``"N_PLAYERS"`` (int): Number of players.
            - ``"N_ACTIONS"`` (int): Maximum number of actions per player.
            - ``"country_idx2num_actions"`` (dict): Maps each player index to
              their number of available actions.
            - ``"binary_goals"`` (list, optional): Goal indices treated as
              binary (all-or-nothing).
            - ``"sat_masks"`` (dict, optional): Pre-computed satisfaction
              masks. If absent, they are generated via ``create_sat_masks``.
        delta (float): Minimum payoff each player must receive. Acts as a
            participation constraint. Defaults to 1e-3.
        objective (str): Aggregation objective. ``"sum"`` maximises the sum
            of payoffs; ``"prod"`` maximises the product (via log-sum).
            Defaults to ``"sum"``.

    Returns:
        tuple:
            - P_opt (np.ndarray): Optimal binary policy matrix of shape
              (N_PLAYERS, N_ACTIONS).
            - s_val (np.ndarray): Goal satisfaction vector of shape
              (N_GOALS,).
            - y_val (np.ndarray): Player payoff vector of shape (N_PLAYERS,).
            - prod_y (float): Product of all player payoffs.
            - log_sum_y (float): Sum of log payoffs (Nash bargaining value).
            - obj_val (float): Optimal objective value reported by the solver.

    Raises:
        ValueError: If ``objective`` is not ``"sum"`` or ``"prod"``.
        RuntimeError: If the solver fails to find a feasible solution.
    """

    if objective not in ["sum", "prod"]:
        raise ValueError("objective must be 'sum' or 'prod'")

    G = game_config["G"]
    n_players, n_actions = game_config["N_PLAYERS"], game_config["N_ACTIONS"]
    country_idx2num_actions = game_config["country_idx2num_actions"]

    # Extract binary goals
    binary_goals = set(game_config.get("binary_goals", []))

    sat_masks = game_config.get("sat_masks", None)
    if sat_masks is None:
        sat_masks = create_sat_masks(game_config)

    J, N = G.shape  # goals, players

    P = cp.Variable((n_players, n_actions), boolean=True)  # decision matrix
    s = cp.Variable(J)  # goal satisfactions (continuous, bounded [0,1])
    y = cp.Variable(N)  # player payoffs

    # Dictionary to hold the strictly boolean variables for binary goals
    z_bin = {j: cp.Variable(boolean=True) for j in binary_goals}

    cons = []

    # Per-player availability: columns beyond available actions are 0
    for i in range(n_players):
        k = country_idx2num_actions[i]
        if k < n_actions:
            cons += [P[i, k:] == 0]

    # Goal satisfaction
    for j in range(J):
        mask = sat_masks[j].astype(int)
        denom = int(mask.sum())
        assert denom > 0, f"Goal {j} has no requirements"

        sum_P = cp.sum(cp.multiply(mask, P))

        if j in binary_goals:
            z_j = z_bin[j]
            cons += [s[j] == z_j]

            cons += [sum_P >= denom * z_j]

            cons += [sum_P <= (denom - 1) + z_j]

        else:
            cons += [s[j] == sum_P / denom]
            cons += [s[j] >= 0, s[j] <= 1]

    cons += [y == G.T @ s]

    cons += [y >= delta]

    if objective == "prod":
        obj = cp.Maximize(cp.sum(cp.log(y)))
    elif objective == "sum":
        obj = cp.Maximize(cp.sum(y))

    prob = cp.Problem(obj, cons)
    prob.solve(solver=cp.MOSEK, verbose=False)

    if P.value is None:
        raise RuntimeError(
            "Optimization failed. Try a different solver or relax integrality."
        )

    P_opt = (P.value > 0.5).astype(np.uint8)
    return (
        P_opt,
        s.value,
        y.value,
        np.prod(y.value),
        np.sum(np.log(y.value)),
        prob.value,
    )
