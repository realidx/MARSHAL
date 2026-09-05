"""
Rollout collection for staged negotiation RL.

The collector records one transition per environment subdecision, preserving
stage ids, acting player ids, masks, and critic predictions so the resulting
data can feed PPO-style updates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np


@dataclass
class RolloutTransition:
    """One staged PPO-style transition."""

    observation: dict
    action: int
    log_prob: float
    value: float
    reward: float
    done: bool
    stage: int
    acting_player: int
    next_observation: dict
    info: dict
    episode_id: int
    timestep: int
    actor_terminal_payoff: float = 0.0
    normalized_actor_terminal_payoff: float = 0.0
    return_: float = 0.0
    advantage: float = 0.0


@dataclass
class RolloutEpisode:
    """Collected staged transitions for one full negotiation episode."""

    transitions: list[RolloutTransition]
    terminal_payoff_vector: np.ndarray
    normalized_terminal_payoff_vector: np.ndarray
    payoff_normalization_scale: float
    total_env_reward: float
    num_env_steps: int


def copy_observation(observation: dict) -> dict:
    """Deep-copy an observation dict of numpy arrays."""
    return {
        key: value.copy() if hasattr(value, "copy") else value
        for key, value in observation.items()
    }


class RolloutCollector:
    """
    Collect staged self-play trajectories from ``NegotiationTurnEnv``.

    The collector is policy-agnostic. The policy object only needs an
    ``act(observation)`` method that returns an object with ``action``,
    ``log_prob``, and ``value`` attributes.
    """

    def __init__(self, env, policy, *, gamma: float = 1.0, gae_lambda: float = 1.0):
        self.env = env
        self.policy = policy
        self.gamma = gamma
        self.gae_lambda = gae_lambda

    def collect_episode(
        self,
        *,
        seed: int | None = None,
        reset_options: dict | None = None,
        episode_id: int = 0,
    ) -> RolloutEpisode:
        """Collect one full staged episode and compute returns/advantages."""
        observation, info = self.env.reset(seed=seed, options=reset_options)
        transitions: list[RolloutTransition] = []
        done = False
        timestep = 0
        last_info = info

        while not done:
            obs_for_policy = copy_observation(observation)
            stage = int(obs_for_policy["stage"][0])
            acting_player = int(obs_for_policy["acting_player"][0])

            step_result = self.policy.act(obs_for_policy)
            next_observation, reward, terminated, truncated, info = self.env.step(
                step_result.action
            )
            done = bool(terminated or truncated)

            transitions.append(
                RolloutTransition(
                    observation=obs_for_policy,
                    action=int(step_result.action),
                    log_prob=float(step_result.log_prob),
                    value=float(step_result.value),
                    reward=float(reward),
                    done=done,
                    stage=stage,
                    acting_player=acting_player,
                    next_observation=copy_observation(next_observation),
                    info=info,
                    episode_id=episode_id,
                    timestep=timestep,
                )
            )

            observation = next_observation
            last_info = info
            timestep += 1

        terminal_payoff_vector = np.asarray(
            last_info.get("terminal_payoff_vector", self.env.game.get_payoff_vector()),
            dtype=float,
        )
        payoff_normalization_scale = self._compute_payoff_normalization_scale(self.env.game)
        normalized_terminal_payoff_vector = (
            terminal_payoff_vector / payoff_normalization_scale
        )
        self._assign_actor_terminal_targets(
            transitions,
            terminal_payoff_vector,
            normalized_terminal_payoff_vector,
        )
        total_env_reward = float(sum(transition.reward for transition in transitions))

        return RolloutEpisode(
            transitions=transitions,
            terminal_payoff_vector=terminal_payoff_vector,
            normalized_terminal_payoff_vector=normalized_terminal_payoff_vector,
            payoff_normalization_scale=payoff_normalization_scale,
            total_env_reward=total_env_reward,
            num_env_steps=len(transitions),
        )

    def collect_episodes(
        self,
        num_episodes: int,
        *,
        seed_fn: Callable[[int], int | None] | None = None,
        reset_options_fn: Callable[[int], dict | None] | None = None,
    ) -> list[RolloutEpisode]:
        """Collect multiple episodes and return them as a list."""
        episodes = []
        for episode_idx in range(num_episodes):
            seed = seed_fn(episode_idx) if seed_fn is not None else None
            reset_options = (
                reset_options_fn(episode_idx) if reset_options_fn is not None else None
            )
            episodes.append(
                self.collect_episode(
                    seed=seed, reset_options=reset_options, episode_id=episode_idx
                )
            )
        return episodes

    def flatten_episodes(self, episodes: list[RolloutEpisode]) -> list[RolloutTransition]:
        """Flatten episode objects into one transition list."""
        flat = []
        for episode in episodes:
            flat.extend(episode.transitions)
        return flat

    def _assign_actor_terminal_targets(
        self,
        transitions: list[RolloutTransition],
        terminal_payoff_vector: np.ndarray,
        normalized_terminal_payoff_vector: np.ndarray,
    ):
        """
        Assign self-interested Monte Carlo targets from the terminal payoff vector.

        Each staged transition is trained against the final payoff of the player
        who acted at that transition. Because acting players alternate through
        the episode, standard sequence-wise GAE over raw env rewards is not the
        right target here. The correct baseline target is:

        ``return_t = terminal_payoff_vector[acting_player_t]``
        """
        for transition in transitions:
            actor_terminal_payoff = float(
                terminal_payoff_vector[transition.acting_player]
            )
            normalized_actor_terminal_payoff = float(
                normalized_terminal_payoff_vector[transition.acting_player]
            )
            transition.actor_terminal_payoff = actor_terminal_payoff
            transition.normalized_actor_terminal_payoff = (
                normalized_actor_terminal_payoff
            )
            transition.return_ = normalized_actor_terminal_payoff
            transition.advantage = normalized_actor_terminal_payoff - transition.value

    @staticmethod
    def _compute_payoff_normalization_scale(game) -> float:
        """
        Compute a stable per-game payoff scale for critic targets.

        Uses ``n_goals * max(abs(G))`` so return targets reflect that terminal
        payoffs aggregate across goals rather than matching one single goal
        coefficient.
        """
        max_abs_goal_value = float(np.abs(game.G).max())
        if max_abs_goal_value <= 0.0:
            return 1.0

        n_goals = int(game.G.shape[0])
        return max(1.0, n_goals * max_abs_goal_value)
