"""
Stage-aware actor-critic model for negotiation RL.

This is the first trainable policy/value scaffold on top of the staged env:
- one shared encoder over public state and actor-conditioned context
- one partner-selection head
- one offer-selection head
- one shared scalar critic predicting the acting player's terminal payoff
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch
from torch import nn
from torch.distributions import Categorical

from rl.observation import OFFER_SELECTION_STAGE, PARTNER_SELECTION_STAGE

MASKED_LOGIT_FLOOR = -1e9


def _as_tensor(value, *, dtype=None, device=None):
    """Convert numpy arrays or tensors to tensors on the target device."""
    if isinstance(value, torch.Tensor):
        tensor = value
        if device is not None:
            tensor = tensor.to(device)
        if dtype is not None:
            tensor = tensor.to(dtype=dtype)
        return tensor
    return torch.as_tensor(value, dtype=dtype, device=device)


def _ensure_batch_dim(tensor: torch.Tensor) -> torch.Tensor:
    """Promote a single example tensor to batch-first form when needed."""
    if tensor.dim() == 0:
        return tensor.unsqueeze(0)
    return tensor


def stack_observations(observations: list[dict]) -> dict:
    """Stack a list of observation dicts into one batched dict."""
    if not observations:
        raise ValueError("Cannot stack an empty observation list.")

    batch = {}
    keys = observations[0].keys()
    for key in keys:
        values = [obs[key] for obs in observations]
        first_value = values[0]
        if isinstance(first_value, torch.Tensor):
            batch[key] = torch.stack(values, dim=0)
        else:
            batch[key] = np.stack(values, axis=0)
    return batch


@dataclass
class ModelStep:
    """Output bundle for one policy step."""

    action: int
    log_prob: float
    value: float


class StageAwareActorCritic(nn.Module):
    """Shared actor-critic with separate partner and offer heads."""

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

        self.partner_pair_mlp = nn.Sequential(
            nn.Linear(hidden_dim + player_feature_dim + 1, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

        self.offer_mlp = nn.Sequential(
            nn.Linear(hidden_dim + offer_feature_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

        self.value_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, 1),
        )

    def encode_context(self, observation: dict) -> torch.Tensor:
        """Build a batch of actor-conditioned context embeddings."""
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

        feature_dim = player_features.shape[-1]
        actor_features = player_features[
            torch.arange(batch_size, device=self.device), acting_player
        ]

        active_counts = player_active_mask.sum(dim=1, keepdim=True).clamp_min(1.0)
        global_features = (
            player_features * player_active_mask.unsqueeze(-1)
        ).sum(dim=1) / active_counts

        partner_features = torch.zeros(
            (batch_size, feature_dim), dtype=torch.float32, device=self.device
        )
        valid_partner = (selected_partner >= 0) & (stage == OFFER_SELECTION_STAGE)
        if valid_partner.any():
            partner_indices = selected_partner[valid_partner]
            partner_features[valid_partner] = player_features[
                torch.arange(batch_size, device=self.device)[valid_partner],
                partner_indices,
            ]

        stage_one_hot = torch.nn.functional.one_hot(stage, num_classes=3).float()
        scalar_context = torch.cat(
            [
                turn_index,
                turns_remaining,
                proposer_num_actions,
                partner_num_actions,
            ],
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

    def partner_logits(self, observation: dict) -> torch.Tensor:
        """Score each partner slot under the partner-selection head."""
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

        batch_size = player_features.shape[0]
        repeated_context = context.unsqueeze(1).expand(-1, self.max_players, -1)
        mask_feature = partner_mask.unsqueeze(-1)
        pair_input = torch.cat([repeated_context, player_features, mask_feature], dim=-1)
        logits = self.partner_pair_mlp(pair_input).squeeze(-1)
        return logits.masked_fill(partner_mask <= 0, MASKED_LOGIT_FLOOR)

    def offer_logits(self, observation: dict) -> torch.Tensor:
        """Score each offer candidate under the offer-selection head."""
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

        repeated_context = context.unsqueeze(1).expand(-1, self.max_candidate_offers, -1)
        offer_input = torch.cat([repeated_context, offer_actions], dim=-1)
        logits = self.offer_mlp(offer_input).squeeze(-1)
        return logits.masked_fill(offer_mask <= 0, MASKED_LOGIT_FLOOR)

    def value(self, observation: dict) -> torch.Tensor:
        """Predict the acting player's terminal payoff from the current stage."""
        context = self.encode_context(observation)
        return self.value_head(context).squeeze(-1)

    def action_distribution(self, observation: dict) -> Categorical:
        """Return the masked categorical distribution for the active stage."""
        stage = int(np.asarray(observation["stage"]).reshape(-1)[0])
        if stage == PARTNER_SELECTION_STAGE:
            logits = self.partner_logits(observation)
        elif stage == OFFER_SELECTION_STAGE:
            logits = self.offer_logits(observation)
        else:
            raise ValueError(f"Unsupported stage id: {stage}")

        if logits.dim() == 2 and logits.shape[0] == 1:
            logits = logits.squeeze(0)
        return Categorical(logits=logits)

    def action_distribution_batch(self, observation_batch: dict) -> Categorical:
        """Return a masked categorical distribution for a same-stage batch."""
        stage_values = np.asarray(observation_batch["stage"]).reshape(-1)
        unique_stages = np.unique(stage_values)
        if len(unique_stages) != 1:
            raise ValueError("Batched action evaluation requires a single stage.")

        stage = int(unique_stages[0])
        if stage == PARTNER_SELECTION_STAGE:
            logits = self.partner_logits(observation_batch)
        elif stage == OFFER_SELECTION_STAGE:
            logits = self.offer_logits(observation_batch)
        else:
            raise ValueError(f"Unsupported stage id: {stage}")

        return Categorical(logits=logits)

    def evaluate_actions_batch(
        self,
        observation_batch: dict,
        actions,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """
        Evaluate batched actions for PPO updates.

        Returns ``(log_probs, entropies, values)`` for a same-stage batch.
        """
        actions_tensor = _as_tensor(actions, dtype=torch.long, device=self.device).view(-1)
        dist = self.action_distribution_batch(observation_batch)
        log_probs = dist.log_prob(actions_tensor)
        entropies = dist.entropy()
        values = self.value(observation_batch).view(-1)
        return log_probs, entropies, values

    @property
    def device(self):
        """Current module device."""
        return next(self.parameters()).device


class TorchPolicyAdapter:
    """Policy wrapper exposing the collector-compatible ``act`` API."""

    def __init__(self, model: StageAwareActorCritic):
        self.model = model

    def act(self, observation: dict) -> ModelStep:
        """Sample one action and return PPO-relevant metadata."""
        self.model.eval()
        with torch.no_grad():
            dist = self.model.action_distribution(observation)
            action = dist.sample()
            value = self.model.value(observation)

        action_int = int(action.item())
        log_prob = float(dist.log_prob(action).item())
        if value.dim() > 0:
            value_scalar = float(value.reshape(-1)[0].item())
        else:
            value_scalar = float(value.item())
        return ModelStep(action=action_int, log_prob=log_prob, value=value_scalar)
