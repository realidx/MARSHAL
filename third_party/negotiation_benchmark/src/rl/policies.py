"""
Policy helpers for RL data collection.

These are lightweight utilities for rollout collection and smoke tests, not
the final learned PPO/MAPPO policy implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from rl.observation import OFFER_SELECTION_STAGE, PARTNER_SELECTION_STAGE


@dataclass
class PolicyStep:
    """One action-selection result for a staged RL environment."""

    action: int
    log_prob: float
    value: float


class RandomMaskedPolicy:
    """
    Random masked policy for smoke-testing collection logic.

    The policy samples uniformly from currently legal actions and returns a
    dummy value baseline of zero.
    """

    def __init__(self, rng: np.random.Generator | None = None):
        self.rng = rng if rng is not None else np.random.default_rng()

    def act(self, observation: dict) -> PolicyStep:
        """Sample a legal action based on the current stage-specific mask."""
        stage = int(observation["stage"][0])
        if stage == PARTNER_SELECTION_STAGE:
            mask = observation["partner_mask"]
        elif stage == OFFER_SELECTION_STAGE:
            mask = observation["offer_mask"]
        else:
            raise ValueError(f"Unsupported stage id for random policy: {stage}")

        legal_actions = np.flatnonzero(mask == 1)
        if legal_actions.size == 0:
            raise ValueError("No legal actions available for RandomMaskedPolicy.")

        chosen_idx = int(self.rng.integers(legal_actions.size))
        action = int(legal_actions[chosen_idx])
        log_prob = -float(np.log(legal_actions.size))
        return PolicyStep(action=action, log_prob=log_prob, value=0.0)
