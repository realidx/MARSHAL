"""
Metric helpers for staged negotiation RL training.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class IterationMetrics:
    """Compact summary for one collect-update iteration."""

    iteration: int
    num_episodes: int
    num_transitions: int
    mean_raw_social_welfare: float
    mean_normalized_social_welfare: float
    mean_raw_payoff: float
    mean_normalized_payoff: float
    min_raw_payoff: float
    max_raw_payoff: float
    mean_episode_length: float
    mean_total_env_reward: float
    payoff_normalization_scale_mean: float
    ppo_mean_policy_loss: float
    ppo_mean_value_loss: float
    ppo_mean_entropy: float
    ppo_mean_total_loss: float

    def to_dict(self) -> dict:
        """Serialize to a plain dict."""
        return asdict(self)


def summarize_iteration(iteration: int, episodes, train_stats) -> IterationMetrics:
    """Aggregate rollout and PPO stats into one iteration summary."""
    if not episodes:
        raise ValueError("Cannot summarize an empty episode list.")

    raw_social_welfare = [float(ep.terminal_payoff_vector.sum()) for ep in episodes]
    normalized_social_welfare = [
        float(ep.normalized_terminal_payoff_vector.sum()) for ep in episodes
    ]
    raw_payoffs = np.concatenate([ep.terminal_payoff_vector for ep in episodes]).astype(
        float
    )
    normalized_payoffs = np.concatenate(
        [ep.normalized_terminal_payoff_vector for ep in episodes]
    ).astype(float)
    episode_lengths = [ep.num_env_steps for ep in episodes]
    total_env_rewards = [ep.total_env_reward for ep in episodes]
    normalization_scales = [ep.payoff_normalization_scale for ep in episodes]

    return IterationMetrics(
        iteration=iteration,
        num_episodes=len(episodes),
        num_transitions=sum(ep.num_env_steps for ep in episodes),
        mean_raw_social_welfare=float(np.mean(raw_social_welfare)),
        mean_normalized_social_welfare=float(np.mean(normalized_social_welfare)),
        mean_raw_payoff=float(np.mean(raw_payoffs)),
        mean_normalized_payoff=float(np.mean(normalized_payoffs)),
        min_raw_payoff=float(np.min(raw_payoffs)),
        max_raw_payoff=float(np.max(raw_payoffs)),
        mean_episode_length=float(np.mean(episode_lengths)),
        mean_total_env_reward=float(np.mean(total_env_rewards)),
        payoff_normalization_scale_mean=float(np.mean(normalization_scales)),
        ppo_mean_policy_loss=float(train_stats.mean_policy_loss),
        ppo_mean_value_loss=float(train_stats.mean_value_loss),
        ppo_mean_entropy=float(train_stats.mean_entropy),
        ppo_mean_total_loss=float(train_stats.mean_total_loss),
    )
