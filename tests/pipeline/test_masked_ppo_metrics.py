import pytest
import torch

from roll.pipeline.base_worker import masked_ppo_clip_fractions


def test_ppo_clip_fractions_ignore_padded_tokens():
    clipped_low = torch.tensor([[0.0, 1.0, 1.0, 1.0]])
    clipped_high = torch.tensor([[1.0, 0.0, 1.0, 1.0]])
    response_mask = torch.tensor([[1, 1, 0, 0]])

    metrics = masked_ppo_clip_fractions(
        clipped_low=clipped_low,
        clipped_high=clipped_high,
        response_mask=response_mask,
    )

    assert metrics["actor/ppo_ratio_high_clipfrac"] == pytest.approx(0.5)
    assert metrics["actor/ppo_ratio_low_clipfrac"] == pytest.approx(0.5)
    assert metrics["actor/ppo_ratio_clipfrac"] == pytest.approx(1.0)
