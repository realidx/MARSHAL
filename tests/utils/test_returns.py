import torch

from roll.utils.returns import compute_reinforce_return


def test_environment_step_discounts_are_invariant_to_turn_token_length():
    discount = 0.9
    first_turn_reward = 0.4
    second_turn_reward = -0.2
    expected_first_return = first_turn_reward + discount**2 * second_turn_reward

    short_rewards = torch.tensor([[0.0, first_turn_reward, 0.0, second_turn_reward]])
    short_discounts = torch.ones_like(short_rewards)
    short_discounts[0, 1] = discount**2
    short_returns, _ = compute_reinforce_return(
        short_rewards,
        gamma=1.0,
        lambd=1.0,
        continuation_discounts=short_discounts,
    )

    long_rewards = torch.tensor([[0.0, 0.0, 0.0, first_turn_reward, 0.0, 0.0, 0.0, 0.0, second_turn_reward]])
    long_discounts = torch.ones_like(long_rewards)
    long_discounts[0, 3] = discount**2
    long_returns, _ = compute_reinforce_return(
        long_rewards,
        gamma=1.0,
        lambd=1.0,
        continuation_discounts=long_discounts,
    )

    assert torch.isclose(short_returns[0, 1], torch.tensor(expected_first_return))
    assert torch.isclose(long_returns[0, 3], torch.tensor(expected_first_return))


def test_grouped_turn_rewards_match_flat_environment_step_return():
    discount = 0.9
    transition_rewards = [0.2, -0.3, 0.5, 0.1, -0.4]
    grouped_rewards = [
        transition_rewards[0] + discount * transition_rewards[1],
        transition_rewards[2] + discount * transition_rewards[3],
        transition_rewards[4],
    ]
    rewards = torch.tensor([grouped_rewards])
    continuation_discounts = torch.tensor([[discount**2, discount**2, discount]])

    returns, _ = compute_reinforce_return(
        rewards,
        gamma=1.0,
        lambd=1.0,
        continuation_discounts=continuation_discounts,
    )
    expected = sum(discount**step * reward for step, reward in enumerate(transition_rewards))
    assert torch.isclose(returns[0, 0], torch.tensor(expected))
