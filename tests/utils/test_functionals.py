from typing import Tuple

import numpy as np
import pytest
import torch

from roll.utils.functionals import (
    agg_loss,
    combine_counterfactual_game_and_auxiliary_advantages,
    divide_by_chunk_size,
    masked_whiten,
    pad_to_length,
    traverse_obj,
)


def visitor(obj: object, path: Tuple):
    if torch.is_tensor(obj):
        print(f"Tensor found: {obj}, shape: {obj.shape}, dtype: {obj.dtype}")
        return True
    return False


def test_traverse_obj():
    class CustomObject2:
        def __init__(self):
            self.attr1 = torch.tensor([1, 2, 3])
            self.attr2 = {
                "nested_key1": torch.tensor([[1, 2], [3, 4]]),
                "nested_key2": [torch.tensor(5), np.array([6, 7])],
            }
    class CustomObject:
        def __init__(self):
            self.attr1 = torch.tensor([1, 2, 3])
            self.attr2 = {
                "nested_key1": torch.tensor([[1, 2], [3, 4]]),
                "nested_key2": [torch.tensor(5), np.array([6, 7])],
            }
            self.attr3 = CustomObject2()

    custom_obj = CustomObject()

    traverse_obj(custom_obj, visitor, path=(str(custom_obj),))


def test_divide_by_chunk_size_valid():
    array = np.arange(51)
    chunk_sizes = [7, 7, 7, 7, 7, 7, 7, 2]
    result = divide_by_chunk_size(array, chunk_sizes)

    assert len(result) == len(chunk_sizes)
    assert all(isinstance(chunk, np.ndarray) for chunk in result)
    assert [len(chunk) for chunk in result] == chunk_sizes


def test_pad_to_length():
    tensor = torch.tensor([[1, 2, 3, 4, 5, 6, 7], [4, 5, 6, 1, 2, 3, 7]])
    length = 5
    pad_value = 0

    padded_tensor = pad_to_length(tensor, length, pad_value, dim=-1)
    print(padded_tensor)


def test_seq_mean_token_mean_gives_equal_sequence_weight_without_double_division():
    losses = torch.tensor([[2.0, 2.0, 0.0, 0.0], [4.0, 4.0, 4.0, 4.0]])
    mask = torch.tensor([[1, 1, 0, 0], [1, 1, 1, 1]], dtype=torch.bool)

    result = agg_loss(losses, mask, "seq-mean-token-mean")

    assert result.item() == pytest.approx(3.0)


def test_seq_mean_token_sum_sums_tokens_before_averaging_sequences():
    losses = torch.tensor([[2.0, 2.0, 0.0, 0.0], [4.0, 4.0, 4.0, 4.0]])
    mask = torch.tensor([[1, 1, 0, 0], [1, 1, 1, 1]], dtype=torch.bool)

    result = agg_loss(losses, mask, "seq-mean-token-sum")

    assert result.item() == pytest.approx(10.0)


def test_masked_whiten_constant_negative_advantages_returns_zero_without_nan():
    """An all-invalid rollout batch must not produce a policy-gradient update."""
    mask = torch.arange(8).unsqueeze(0) < torch.arange(1, 33).remainder(8).add(1).unsqueeze(1)
    advantages = torch.where(mask, -1.5, 0.0)

    whitened = masked_whiten(advantages, mask)

    assert torch.isfinite(whitened).all()
    assert torch.count_nonzero(whitened * mask) == 0


def test_counterfactual_game_credit_is_preserved_while_auxiliary_controls_are_centered():
    response_mask = torch.tensor(
        [[1, 1, 0, 0], [1, 1, 1, 1], [1, 1, 1, 0]], dtype=torch.bool
    )
    game_advantages = torch.tensor(
        [[-1.0, -1.0, 0.0, 0.0], [-0.5, -0.5, -0.5, -0.5], [1.0, 1.0, 1.0, 0.0]]
    )
    auxiliary_rewards = torch.tensor(
        [[0.0, -1.5, 0.0, 0.0], [0.0, 0.0, 0.0, -1.5], [0.0, 0.0, 0.5, 0.0]]
    )
    valid_actions = torch.tensor([False, False, True])

    combined, game, auxiliary, skipped = combine_counterfactual_game_and_auxiliary_advantages(
        game_advantages, auxiliary_rewards, valid_actions, response_mask
    )

    assert not skipped
    assert torch.count_nonzero(game[:2]) == 0
    assert torch.equal(game[2], game_advantages[2])
    assert auxiliary[0, 0].item() == pytest.approx(-2.0 / 3.0)
    assert auxiliary[1, 0].item() == pytest.approx(-2.0 / 3.0)
    assert auxiliary[2, 0].item() == pytest.approx(4.0 / 3.0)
    assert torch.equal(combined, (game + auxiliary) * response_mask)


def test_zero_valid_batch_has_zero_policy_gradient_even_if_auxiliary_values_differ():
    response_mask = torch.tensor([[1, 1, 0], [1, 1, 1]], dtype=torch.bool)
    game_advantages = torch.full((2, 3), -1.0)
    auxiliary_rewards = torch.tensor([[0.0, -1.5, 0.0], [0.0, 0.0, -1.0]])

    combined, game, auxiliary, skipped = combine_counterfactual_game_and_auxiliary_advantages(
        game_advantages,
        auxiliary_rewards,
        torch.tensor([False, False]),
        response_mask,
    )

    assert skipped
    assert torch.count_nonzero(combined) == 0
    assert torch.count_nonzero(game) == 0
    assert torch.count_nonzero(auxiliary) == 0


if __name__ == "__main__":
    pytest.main()
