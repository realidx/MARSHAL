"""
Training utilities for the GFA-RFE-style baseline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import torch
from torch import nn

from rl.model import stack_observations


@dataclass
class RFEExplorationStats:
    """Aggregated metrics from one reward-free ensemble update."""

    updated_network: int
    num_transitions: int
    mean_loss: float
    mean_uncertainty: float
    mean_intrinsic_reward: float
    mean_bonus: float


@dataclass
class OfflinePlanningStats:
    """Aggregated metrics from offline planning updates."""

    num_transitions: int
    num_minibatches: int
    mean_loss: float


class RFEExplorationTrainer:
    """
    Online reward-free trainer for a staged Q ensemble.

    The loss follows Appendix F's practical recipe, adapted to masked discrete
    actions: ensemble target variance supplies intrinsic reward, optimism, and
    inverse-variance weighting.
    """

    def __init__(
        self,
        ensemble,
        *,
        learning_rate: float = 1e-4,
        gamma: float = 0.99,
        beta: float = 1.0,
        target_tau: float = 0.01,
        variance_floor: float = 1e-4,
        max_weight: float = 100.0,
        device: str | torch.device | None = None,
    ):
        self.ensemble = ensemble
        self.gamma = gamma
        self.beta = beta
        self.target_tau = target_tau
        self.variance_floor = variance_floor
        self.max_weight = max_weight
        self.device = torch.device(device) if device is not None else ensemble.device
        self.ensemble.to(self.device)
        self.optimizers = [
            torch.optim.Adam(network.parameters(), lr=learning_rate)
            for network in self.ensemble.networks
        ]
        self.update_count = 0

    def update(self, replay_buffer, *, batch_size: int) -> RFEExplorationStats:
        """Update one ensemble member from a replay minibatch."""
        rows = replay_buffer.sample(batch_size)
        network_idx = self.update_count % self.ensemble.ensemble_size
        optimizer = self.optimizers[network_idx]
        stage_batches = self._group_rows_by_stage(rows)

        self.ensemble.train()
        optimizer.zero_grad()

        losses = []
        uncertainty_values = []
        intrinsic_values = []
        bonus_values = []
        total_rows = 0

        for stage_rows in stage_batches.values():
            batch_obs = stack_observations(
                [transition.observation for transition in stage_rows]
            )
            next_batch_obs = stack_observations(
                [transition.next_observation for transition in stage_rows]
            )
            actions = np.array(
                [transition.action for transition in stage_rows], dtype=np.int64
            )
            done = torch.as_tensor(
                [transition.done for transition in stage_rows],
                dtype=torch.float32,
                device=self.device,
            )

            with torch.no_grad():
                target_stack = self.ensemble.q_values_stack_batch(
                    batch_obs, use_target=True
                )
                actions_tensor = torch.as_tensor(
                    actions, dtype=torch.long, device=self.device
                ).view(1, -1, 1)
                selected_target_values = target_stack.gather(
                    2,
                    actions_tensor.expand(self.ensemble.ensemble_size, -1, -1),
                ).squeeze(-1)
                variance = selected_target_values.var(dim=0, unbiased=False)
                uncertainty = variance.sqrt()
                intrinsic_reward = (1.0 - self.gamma) * uncertainty
                bonus = self.beta * uncertainty

                next_target_stack = self.ensemble.q_values_stack_batch(
                    next_batch_obs, use_target=True
                )
                next_mean_q = next_target_stack.mean(dim=0)
                next_max_q = next_mean_q.max(dim=1).values
                next_max_q = torch.where(done > 0.0, torch.zeros_like(next_max_q), next_max_q)

                target = intrinsic_reward + bonus + self.gamma * next_max_q
                weights = torch.clamp(
                    1.0 / (variance + self.variance_floor), max=self.max_weight
                )

            predicted = self.ensemble.networks[network_idx].evaluate_actions_batch(
                batch_obs, actions
            )
            loss = torch.mean(weights * (predicted - target) ** 2)
            losses.append(loss)

            uncertainty_values.append(float(uncertainty.mean().item()))
            intrinsic_values.append(float(intrinsic_reward.mean().item()))
            bonus_values.append(float(bonus.mean().item()))
            total_rows += len(stage_rows)

        total_loss = torch.stack(losses).mean()
        total_loss.backward()
        nn.utils.clip_grad_norm_(
            self.ensemble.networks[network_idx].parameters(), max_norm=10.0
        )
        optimizer.step()
        self.ensemble.soft_update_target(network_idx, self.target_tau)
        self.update_count += 1

        return RFEExplorationStats(
            updated_network=network_idx,
            num_transitions=total_rows,
            mean_loss=float(total_loss.item()),
            mean_uncertainty=float(np.mean(uncertainty_values)),
            mean_intrinsic_reward=float(np.mean(intrinsic_values)),
            mean_bonus=float(np.mean(bonus_values)),
        )

    @staticmethod
    def _group_rows_by_stage(rows: Iterable) -> dict[int, list]:
        grouped: dict[int, list] = {}
        for row in rows:
            grouped.setdefault(int(row.stage), []).append(row)
        return grouped


class OfflinePlanningTrainer:
    """
    Offline planner trained on reward-free replay labelled after collection.

    This first implementation uses Monte Carlo terminal labels rather than TD
    bootstrapping. That keeps the objective aligned with the current PPO target:
    each transition predicts the terminal payoff of the acting player.
    """

    def __init__(
        self,
        model,
        optimizer: torch.optim.Optimizer,
        *,
        device: str | torch.device | None = None,
    ):
        self.model = model
        self.optimizer = optimizer
        self.device = torch.device(device) if device is not None else model.device
        self.model.to(self.device)

    def update(
        self,
        transitions,
        *,
        epochs: int = 20,
        minibatch_size: int = 128,
    ) -> OfflinePlanningStats:
        """Fit the planner Q-network to acting-player terminal payoff labels."""
        rows = list(transitions)
        if not rows:
            raise ValueError("No transitions provided for offline planning.")

        total_loss = 0.0
        total_minibatches = 0
        self.model.train()

        for _ in range(epochs):
            shuffled = rows.copy()
            np.random.shuffle(shuffled)

            for start in range(0, len(shuffled), minibatch_size):
                minibatch_rows = shuffled[start : start + minibatch_size]
                stage_batches = self._group_rows_by_stage(minibatch_rows)

                for stage_rows in stage_batches.values():
                    batch_obs = stack_observations(
                        [transition.observation for transition in stage_rows]
                    )
                    actions = np.array(
                        [transition.action for transition in stage_rows],
                        dtype=np.int64,
                    )
                    targets = torch.as_tensor(
                        [transition.planning_return for transition in stage_rows],
                        dtype=torch.float32,
                        device=self.device,
                    )

                    predicted = self.model.evaluate_actions_batch(batch_obs, actions)
                    loss = torch.mean((predicted - targets) ** 2)

                    self.optimizer.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=10.0)
                    self.optimizer.step()

                    total_loss += float(loss.item())
                    total_minibatches += 1

        return OfflinePlanningStats(
            num_transitions=len(rows),
            num_minibatches=total_minibatches,
            mean_loss=total_loss / total_minibatches,
        )

    @staticmethod
    def _group_rows_by_stage(rows: Iterable) -> dict[int, list]:
        grouped: dict[int, list] = {}
        for row in rows:
            grouped.setdefault(int(row.stage), []).append(row)
        return grouped
