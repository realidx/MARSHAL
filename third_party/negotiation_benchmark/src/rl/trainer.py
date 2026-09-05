"""
Minimal PPO trainer for staged negotiation RL.

This trainer consumes staged rollout transitions, groups them by decision
stage, and applies clipped PPO updates against the acting player's realized
terminal payoff target.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import torch
from torch import nn

from rl.model import stack_observations


@dataclass
class PPOTrainStats:
    """Aggregated metrics from one PPO update call."""

    num_transitions: int
    num_minibatches: int
    mean_policy_loss: float
    mean_value_loss: float
    mean_entropy: float
    mean_total_loss: float


class PPOTrainer:
    """Readable first-pass PPO trainer for the staged negotiation model."""

    def __init__(
        self,
        model,
        optimizer: torch.optim.Optimizer,
        *,
        clip_epsilon: float = 0.2,
        value_coef: float = 0.5,
        entropy_coef: float = 0.01,
        max_grad_norm: float = 0.5,
        normalize_advantages: bool = True,
        device: str | torch.device | None = None,
    ):
        self.model = model
        self.optimizer = optimizer
        self.clip_epsilon = clip_epsilon
        self.value_coef = value_coef
        self.entropy_coef = entropy_coef
        self.max_grad_norm = max_grad_norm
        self.normalize_advantages = normalize_advantages
        self.device = torch.device(device) if device is not None else model.device
        self.model.to(self.device)

    def update(
        self,
        transitions,
        *,
        ppo_epochs: int = 4,
        minibatch_size: int = 64,
    ) -> PPOTrainStats:
        """Run PPO updates over a list of staged transitions."""
        prepared = self._prepare_training_rows(transitions)
        if not prepared:
            raise ValueError("No transitions provided for PPO update.")

        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        total_loss_accum = 0.0
        total_minibatches = 0

        self.model.train()

        for _ in range(ppo_epochs):
            shuffled = prepared.copy()
            np.random.shuffle(shuffled)

            for start in range(0, len(shuffled), minibatch_size):
                minibatch_rows = shuffled[start : start + minibatch_size]
                stage_batches = self._group_rows_by_stage(minibatch_rows)

                for rows in stage_batches.values():
                    batch_obs = stack_observations([row["observation"] for row in rows])
                    actions = np.array([row["action"] for row in rows], dtype=np.int64)
                    old_log_probs = torch.as_tensor(
                        [row["old_log_prob"] for row in rows],
                        dtype=torch.float32,
                        device=self.device,
                    )
                    returns = torch.as_tensor(
                        [row["return"] for row in rows],
                        dtype=torch.float32,
                        device=self.device,
                    )
                    advantages = torch.as_tensor(
                        [row["advantage"] for row in rows],
                        dtype=torch.float32,
                        device=self.device,
                    )

                    if self.normalize_advantages and advantages.numel() > 1:
                        advantages = (advantages - advantages.mean()) / (
                            advantages.std(unbiased=False) + 1e-8
                        )

                    new_log_probs, entropies, values = self.model.evaluate_actions_batch(
                        batch_obs, actions
                    )

                    ratios = torch.exp(new_log_probs - old_log_probs)
                    unclipped = ratios * advantages
                    clipped = torch.clamp(
                        ratios, 1.0 - self.clip_epsilon, 1.0 + self.clip_epsilon
                    ) * advantages
                    policy_loss = -torch.min(unclipped, clipped).mean()
                    value_loss = torch.mean((values - returns) ** 2)
                    entropy = entropies.mean()

                    total_loss = (
                        policy_loss
                        + self.value_coef * value_loss
                        - self.entropy_coef * entropy
                    )

                    self.optimizer.zero_grad()
                    total_loss.backward()
                    nn.utils.clip_grad_norm_(self.model.parameters(), self.max_grad_norm)
                    self.optimizer.step()

                    total_policy_loss += float(policy_loss.item())
                    total_value_loss += float(value_loss.item())
                    total_entropy += float(entropy.item())
                    total_loss_accum += float(total_loss.item())
                    total_minibatches += 1

        return PPOTrainStats(
            num_transitions=len(prepared),
            num_minibatches=total_minibatches,
            mean_policy_loss=total_policy_loss / total_minibatches,
            mean_value_loss=total_value_loss / total_minibatches,
            mean_entropy=total_entropy / total_minibatches,
            mean_total_loss=total_loss_accum / total_minibatches,
        )

    def _prepare_training_rows(self, transitions) -> list[dict]:
        """Convert transition objects into trainer rows."""
        rows = []
        for transition in transitions:
            rows.append(
                {
                    "observation": transition.observation,
                    "action": transition.action,
                    "old_log_prob": transition.log_prob,
                    "return": transition.return_,
                    "advantage": transition.advantage,
                    "stage": transition.stage,
                }
            )
        return rows

    @staticmethod
    def _group_rows_by_stage(rows: Iterable[dict]) -> dict[int, list[dict]]:
        """Group training rows by stage so each batch uses one action head."""
        grouped: dict[int, list[dict]] = {}
        for row in rows:
            grouped.setdefault(int(row["stage"]), []).append(row)
        return grouped
