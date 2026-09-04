"""
equilibrium.py

Provides utilities for evaluating whether a joint strategy profile constitutes
a Nash equilibrium in a multi-player game, and for quantifying per-player regret.
"""

import numpy as np
from core.game_logic import get_payoff_per_country


def check_equilibrium(P, country_idx2num_actions, G, sat_masks):
    """
    Check whether a given strategy profile is a Nash equilibrium and compute
    per-player regret.

    For each player, the function evaluates whether flipping any single binary
    action improves their payoff. Regret is accumulated as the sum of payoff
    gains from all such improving deviations. The profile is considered a Nash
    equilibrium if total regret across all players is below a small tolerance.

    Args:
        P (np.ndarray): Strategy profile matrix of shape (n, p), where n is the
            number of players and p is the maximum number of actions. Each entry
            is binary (0 or 1).
        country_idx2num_actions (dict or list): Maps each player index to the
            number of actions available to that player.
        G: Game structure passed to the payoff function.
        sat_masks: Satisfaction masks passed to the payoff function.

    Returns:
        tuple:
            - is_equilibrium (bool): True if total regret is at or below 1e-6.
            - regret_per_player (np.ndarray): Array of shape (n,) with each
              player's total regret from beneficial unilateral deviations.
    """

    n, p = P.shape

    is_equilibrium = True
    regret_per_player = np.zeros(n)

    for p_idx in range(n):
        k = country_idx2num_actions[p_idx]
        player_payoff = get_payoff_per_country(P.copy(), G, sat_masks)[p_idx]

        for a_idx in range(k):
            M = P.copy()
            M[p_idx, a_idx] = 1 - M[p_idx, a_idx]

            new_player_payoff = get_payoff_per_country(M, G, sat_masks)[p_idx]

            if new_player_payoff > player_payoff:
                regret_per_player[p_idx] += new_player_payoff - player_payoff

    total_regret = np.sum(regret_per_player)

    if total_regret > 1e-6:
        is_equilibrium = False

    return is_equilibrium, regret_per_player
