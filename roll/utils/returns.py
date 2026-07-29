"""Return estimators that do not depend on the rest of the training stack."""

from typing import Optional

import torch


def compute_reinforce_return(
    token_level_rewards: torch.Tensor,
    gamma: torch.Tensor,
    lambd: torch.Tensor,
    continuation_discounts: Optional[torch.Tensor] = None,
):
    """Compute REINFORCE returns with optional position-specific discounts."""
    del lambd  # Kept in the signature for estimator API compatibility.
    with torch.no_grad():
        if continuation_discounts is not None and continuation_discounts.shape != token_level_rewards.shape:
            raise ValueError(
                "continuation_discounts must have the same shape as token_level_rewards, "
                f"got {continuation_discounts.shape} and {token_level_rewards.shape}"
            )
        advantages_reversed = []
        cumulative_reward = 0
        for index in reversed(range(token_level_rewards.shape[-1])):
            local_reward = token_level_rewards[:, index]
            continuation_discount = continuation_discounts[:, index] if continuation_discounts is not None else gamma
            cumulative_reward = local_reward + continuation_discount * cumulative_reward
            advantages_reversed.append(cumulative_reward)
        advantages = torch.stack(advantages_reversed[::-1], dim=1)
        returns = advantages
    return advantages, returns
