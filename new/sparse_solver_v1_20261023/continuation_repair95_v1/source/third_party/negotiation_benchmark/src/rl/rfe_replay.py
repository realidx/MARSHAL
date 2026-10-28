"""
Replay storage for reward-free exploration and offline planning.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rl.rollout import copy_observation


@dataclass
class RFETransition:
    """One staged transition collected without using extrinsic rewards."""

    observation: dict
    action: int
    next_observation: dict
    done: bool
    stage: int
    acting_player: int
    episode_id: int
    timestep: int
    q_value: float = 0.0
    uncertainty: float = 0.0
    random_action: bool = False
    actor_terminal_payoff: float = 0.0
    normalized_actor_terminal_payoff: float = 0.0
    planning_return: float = 0.0


class RFEReplayBuffer:
    """Simple replay buffer storing transition objects by reference."""

    def __init__(
        self,
        capacity: int,
        *,
        rng: np.random.Generator | None = None,
    ):
        if capacity <= 0:
            raise ValueError("Replay buffer capacity must be positive.")
        self.capacity = capacity
        self.rng = rng if rng is not None else np.random.default_rng()
        self._storage: list[RFETransition] = []
        self._next_idx = 0

    def __len__(self) -> int:
        return len(self._storage)

    def __iter__(self):
        return iter(self._storage)

    def add(self, transition: RFETransition):
        """Add a transition, evicting the oldest slot when full."""
        if len(self._storage) < self.capacity:
            self._storage.append(transition)
        else:
            self._storage[self._next_idx] = transition
        self._next_idx = (self._next_idx + 1) % self.capacity

    def sample(self, batch_size: int) -> list[RFETransition]:
        """Uniformly sample transitions."""
        if not self._storage:
            raise ValueError("Cannot sample from an empty replay buffer.")
        size = min(batch_size, len(self._storage))
        indices = self.rng.choice(len(self._storage), size=size, replace=False)
        return [self._storage[int(idx)] for idx in indices]

    def as_list(self) -> list[RFETransition]:
        """Return a shallow copy of stored transitions."""
        return list(self._storage)


def make_rfe_transition(
    *,
    observation: dict,
    action: int,
    next_observation: dict,
    done: bool,
    stage: int,
    acting_player: int,
    episode_id: int,
    timestep: int,
    q_value: float = 0.0,
    uncertainty: float = 0.0,
    random_action: bool = False,
) -> RFETransition:
    """Build a transition with defensive observation copies."""
    return RFETransition(
        observation=copy_observation(observation),
        action=int(action),
        next_observation=copy_observation(next_observation),
        done=bool(done),
        stage=int(stage),
        acting_player=int(acting_player),
        episode_id=int(episode_id),
        timestep=int(timestep),
        q_value=float(q_value),
        uncertainty=float(uncertainty),
        random_action=bool(random_action),
    )


def assign_terminal_planning_targets(
    transitions: list[RFETransition],
    *,
    terminal_payoff_vector,
    payoff_normalization_scale: float,
):
    """Attach acting-player terminal payoff labels to one episode's transitions."""
    terminal_payoff_vector = np.asarray(terminal_payoff_vector, dtype=float)
    scale = float(max(1.0, payoff_normalization_scale))

    for transition in transitions:
        payoff = float(terminal_payoff_vector[transition.acting_player])
        normalized = payoff / scale
        transition.actor_terminal_payoff = payoff
        transition.normalized_actor_terminal_payoff = normalized
        transition.planning_return = normalized
