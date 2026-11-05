"""
Stage-aware Q networks for reward-free exploration.

This module mirrors the PPO actor-critic shape in ``rl.model`` but changes the
semantics from policy logits/value baselines to masked action-value estimates.
The ensemble wrapper follows the practical GFA-RFE recipe: uncertainty is
estimated from disagreement across target Q networks.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from rl.model import MASKED_LOGIT_FLOOR, _as_tensor
from rl.observation import OFFER_SELECTION_STAGE, PARTNER_SELECTION_STAGE


@dataclass
class QPolicyStep:
    """One Q-policy action-selection result."""

    action: int
    q_value: float
    uncertainty: float = 0.0
    random_action: bool = False


class StageAwareQNetwork(nn.Module):
    """Shared staged MLP producing masked Q-values for the active decision head."""

    def __init__(
        self,
        *,
        player_feature_dim: int,
        max_players: int,
        max_candidate_offers: int,
        offer_feature_dim: int,
        hidden_dim: int = 256,
    ):
        super().__init__()
        self.player_feature_dim = player_feature_dim
        self.max_players = max_players
        self.max_candidate_offers = max_candidate_offers
        self.offer_feature_dim = offer_feature_dim
        self.hidden_dim = hidden_dim

        context_input_dim = (3 * player_feature_dim) + 7
        self.context_encoder = nn.Sequential(
            nn.Linear(context_input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
        )

        self.partner_q_head = nn.Sequential(
            nn.Linear(hidden_dim + player_feature_dim + 1, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

        self.offer_q_head = nn.Sequential(
            nn.Linear(hidden_dim + offer_feature_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    @property
    def device(self):
        """Current module device."""
        return next(self.parameters()).device

    def encode_context(self, observation: dict) -> torch.Tensor:
        """Build actor-conditioned context embeddings."""
        player_features = _as_tensor(
            observation["player_features"], dtype=torch.float32, device=self.device
        )
        player_active_mask = _as_tensor(
            observation["player_active_mask"], dtype=torch.float32, device=self.device
        )
        acting_player = _as_tensor(
            observation["acting_player"], dtype=torch.long, device=self.device
        )
        selected_partner = _as_tensor(
            observation["selected_partner"], dtype=torch.long, device=self.device
        )
        stage = _as_tensor(observation["stage"], dtype=torch.long, device=self.device)
        turn_index = _as_tensor(
            observation["turn_index"], dtype=torch.float32, device=self.device
        )
        turns_remaining = _as_tensor(
            observation["turns_remaining"], dtype=torch.float32, device=self.device
        )
        proposer_num_actions = _as_tensor(
            observation["proposer_num_actions"], dtype=torch.float32, device=self.device
        )
        partner_num_actions = _as_tensor(
            observation["partner_num_actions"], dtype=torch.float32, device=self.device
        )

        if player_features.dim() == 2:
            player_features = player_features.unsqueeze(0)
        if player_active_mask.dim() == 1:
            player_active_mask = player_active_mask.unsqueeze(0)

        batch_size = player_features.shape[0]
        acting_player = acting_player.view(batch_size)
        selected_partner = selected_partner.view(batch_size)
        stage = stage.view(batch_size)
        turn_index = turn_index.view(batch_size, 1)
        turns_remaining = turns_remaining.view(batch_size, 1)
        proposer_num_actions = proposer_num_actions.view(batch_size, 1)
        partner_num_actions = partner_num_actions.view(batch_size, 1)

        actor_features = player_features[
            torch.arange(batch_size, device=self.device), acting_player
        ]
        active_counts = player_active_mask.sum(dim=1, keepdim=True).clamp_min(1.0)
        global_features = (
            player_features * player_active_mask.unsqueeze(-1)
        ).sum(dim=1) / active_counts

        partner_features = torch.zeros(
            (batch_size, player_features.shape[-1]),
            dtype=torch.float32,
            device=self.device,
        )
        valid_partner = (selected_partner >= 0) & (stage == OFFER_SELECTION_STAGE)
        if valid_partner.any():
            partner_features[valid_partner] = player_features[
                torch.arange(batch_size, device=self.device)[valid_partner],
                selected_partner[valid_partner],
            ]

        stage_one_hot = torch.nn.functional.one_hot(stage, num_classes=3).float()
        scalar_context = torch.cat(
            [turn_index, turns_remaining, proposer_num_actions, partner_num_actions],
            dim=1,
        )
        context_input = torch.cat(
            [
                actor_features,
                partner_features,
                global_features,
                stage_one_hot,
                scalar_context,
            ],
            dim=1,
        )
        return self.context_encoder(context_input)

    def partner_q_values(self, observation: dict) -> torch.Tensor:
        """Return masked Q-values for partner selection."""
        context = self.encode_context(observation)
        player_features = _as_tensor(
            observation["player_features"], dtype=torch.float32, device=self.device
        )
        partner_mask = _as_tensor(
            observation["partner_mask"], dtype=torch.float32, device=self.device
        )

        if player_features.dim() == 2:
            player_features = player_features.unsqueeze(0)
        if partner_mask.dim() == 1:
            partner_mask = partner_mask.unsqueeze(0)

        repeated_context = context.unsqueeze(1).expand(-1, self.max_players, -1)
        pair_input = torch.cat(
            [repeated_context, player_features, partner_mask.unsqueeze(-1)], dim=-1
        )
        q_values = self.partner_q_head(pair_input).squeeze(-1)
        return q_values.masked_fill(partner_mask <= 0, MASKED_LOGIT_FLOOR)

    def offer_q_values(self, observation: dict) -> torch.Tensor:
        """Return masked Q-values for offer selection."""
        context = self.encode_context(observation)
        offer_actions = _as_tensor(
            observation["offer_actions"], dtype=torch.float32, device=self.device
        )
        offer_mask = _as_tensor(
            observation["offer_mask"], dtype=torch.float32, device=self.device
        )

        if offer_actions.dim() == 2:
            offer_actions = offer_actions.unsqueeze(0)
        if offer_mask.dim() == 1:
            offer_mask = offer_mask.unsqueeze(0)

        repeated_context = context.unsqueeze(1).expand(
            -1, self.max_candidate_offers, -1
        )
        offer_input = torch.cat([repeated_context, offer_actions], dim=-1)
        q_values = self.offer_q_head(offer_input).squeeze(-1)
        return q_values.masked_fill(offer_mask <= 0, MASKED_LOGIT_FLOOR)

    def q_values(self, observation: dict) -> torch.Tensor:
        """Return masked Q-values for the active stage."""
        stage = int(np.asarray(observation["stage"]).reshape(-1)[0])
        if stage == PARTNER_SELECTION_STAGE:
            values = self.partner_q_values(observation)
        elif stage == OFFER_SELECTION_STAGE:
            values = self.offer_q_values(observation)
        else:
            raise ValueError(f"Unsupported stage id: {stage}")

        if values.dim() == 2 and values.shape[0] == 1:
            values = values.squeeze(0)
        return values

    def q_values_batch(self, observation_batch: dict) -> torch.Tensor:
        """Return masked Q-values for a same-stage batch."""
        stage_values = np.asarray(observation_batch["stage"]).reshape(-1)
        unique_stages = np.unique(stage_values)
        if len(unique_stages) != 1:
            raise ValueError("Batched Q evaluation requires a single stage.")

        stage = int(unique_stages[0])
        if stage == PARTNER_SELECTION_STAGE:
            return self.partner_q_values(observation_batch)
        if stage == OFFER_SELECTION_STAGE:
            return self.offer_q_values(observation_batch)
        raise ValueError(f"Unsupported stage id: {stage}")

    def evaluate_actions_batch(self, observation_batch: dict, actions) -> torch.Tensor:
        """Gather Q-values for selected actions in a same-stage batch."""
        actions_tensor = _as_tensor(actions, dtype=torch.long, device=self.device).view(
            -1, 1
        )
        q_values = self.q_values_batch(observation_batch)
        return q_values.gather(1, actions_tensor).squeeze(1)


class StageAwareQEnsemble(nn.Module):
    """Ensemble of staged Q networks plus slowly updated target copies."""

    def __init__(
        self,
        *,
        ensemble_size: int,
        player_feature_dim: int,
        max_players: int,
        max_candidate_offers: int,
        offer_feature_dim: int,
        hidden_dim: int = 256,
    ):
        super().__init__()
        if ensemble_size < 2:
            raise ValueError("GFA-RFE uncertainty estimation requires ensemble_size >= 2.")

        network_kwargs = {
            "player_feature_dim": player_feature_dim,
            "max_players": max_players,
            "max_candidate_offers": max_candidate_offers,
            "offer_feature_dim": offer_feature_dim,
            "hidden_dim": hidden_dim,
        }
        self.networks = nn.ModuleList(
            [StageAwareQNetwork(**network_kwargs) for _ in range(ensemble_size)]
        )
        self.target_networks = nn.ModuleList(
            [StageAwareQNetwork(**network_kwargs) for _ in range(ensemble_size)]
        )
        self.ensemble_size = ensemble_size
        self.hard_update_targets()

    @property
    def device(self):
        """Current ensemble device."""
        return self.networks[0].device

    def hard_update_targets(self):
        """Copy online networks into target networks."""
        for target, online in zip(self.target_networks, self.networks):
            target.load_state_dict(online.state_dict())

    @torch.no_grad()
    def soft_update_target(self, index: int, tau: float):
        """Soft-update one target network."""
        target = self.target_networks[index]
        online = self.networks[index]
        for target_param, online_param in zip(target.parameters(), online.parameters()):
            target_param.data.mul_(1.0 - tau).add_(online_param.data, alpha=tau)

    def q_values_stack(self, observation: dict, *, use_target: bool = False) -> torch.Tensor:
        """Return stacked Q-values with shape ``(ensemble, actions)`` or batched."""
        networks = self.target_networks if use_target else self.networks
        values = [network.q_values(observation) for network in networks]
        return torch.stack(values, dim=0)

    def q_values_stack_batch(
        self, observation_batch: dict, *, use_target: bool = False
    ) -> torch.Tensor:
        """Return stacked batched Q-values with shape ``(ensemble, batch, actions)``."""
        networks = self.target_networks if use_target else self.networks
        values = [network.q_values_batch(observation_batch) for network in networks]
        return torch.stack(values, dim=0)

    def mean_and_uncertainty(
        self, observation: dict, *, use_target_for_uncertainty: bool = True
    ) -> tuple[torch.Tensor, torch.Tensor]:
        """Return mean online Q-values and target-ensemble uncertainty."""
        online_values = self.q_values_stack(observation, use_target=False)
        uncertainty_values = self.q_values_stack(
            observation, use_target=use_target_for_uncertainty
        )
        return online_values.mean(dim=0), uncertainty_values.var(dim=0, unbiased=False).sqrt()


class RFEExplorationPolicy:
    """Masked epsilon-greedy exploration policy for the Q ensemble."""

    def __init__(
        self,
        ensemble: StageAwareQEnsemble,
        *,
        epsilon: float = 0.2,
        beta: float = 1.0,
        rng: np.random.Generator | None = None,
    ):
        self.ensemble = ensemble
        self.epsilon = epsilon
        self.beta = beta
        self.rng = rng if rng is not None else np.random.default_rng()

    def act(self, observation: dict) -> QPolicyStep:
        """Choose a legal action by random exploration or optimistic Q scoring."""
        stage = int(observation["stage"][0])
        if stage == PARTNER_SELECTION_STAGE:
            mask = observation["partner_mask"]
        elif stage == OFFER_SELECTION_STAGE:
            mask = observation["offer_mask"]
        else:
            raise ValueError(f"Unsupported stage id for RFE policy: {stage}")

        legal_actions = np.flatnonzero(mask == 1)
        if legal_actions.size == 0:
            raise ValueError("No legal actions available for RFEExplorationPolicy.")

        if self.rng.random() < self.epsilon:
            action = int(self.rng.choice(legal_actions))
            return QPolicyStep(action=action, q_value=0.0, random_action=True)

        self.ensemble.eval()
        with torch.no_grad():
            mean_q, uncertainty = self.ensemble.mean_and_uncertainty(observation)
            scores = mean_q + self.beta * uncertainty
            illegal_mask = torch.ones_like(scores, dtype=torch.bool)
            illegal_mask[legal_actions] = False
            scores = scores.masked_fill(illegal_mask, MASKED_LOGIT_FLOOR)
            action_tensor = torch.argmax(scores).reshape(())

        action = int(action_tensor.item())
        return QPolicyStep(
            action=action,
            q_value=float(mean_q[action].item()),
            uncertainty=float(uncertainty[action].item()),
            random_action=False,
        )


class GreedyQPolicy:
    """Deterministic policy that argmaxes masked Q-values."""

    def __init__(self, model: StageAwareQNetwork):
        self.model = model

    def act(self, observation: dict) -> QPolicyStep:
        """Choose the legal action with highest Q-value."""
        self.model.eval()
        with torch.no_grad():
            q_values = self.model.q_values(observation)
            action = torch.argmax(q_values).reshape(())
        action_int = int(action.item())
        return QPolicyStep(action=action_int, q_value=float(q_values[action_int].item()))
