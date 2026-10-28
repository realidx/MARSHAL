"""
Reward helpers for RL wrappers.
"""

from __future__ import annotations


def terminal_reward_for_actor(state, actor_id: int, terminated: bool) -> float:
    """
    Return terminal-only reward for the acting player.

    Intermediate steps get zero reward. At terminal states, the acting player
    receives their final payoff. Full terminal payoff vectors are exposed in
    ``info`` by the environment.
    """
    if not terminated:
        return 0.0

    payoff_vector = state.get_payoff_vector()
    return float(payoff_vector[actor_id])
