import math

import pytest


pytest.importorskip("pyspiel")

from roll.agentic.env.tictactoe import TicTacToe, TicTacToeConfig


def test_environment_shaped_rewards_telescope():
    discount = 0.9
    env = TicTacToe(
        TicTacToeConfig(
            built_in_opponent="none",
            reward_mode="minimax_shaped",
            minimax_discount=discount,
            precompute_minimax=True,
        )
    )
    env.reset(seed=0)
    initial_values = [env.minimax_evaluator.value((0,) * 9, perspective) for perspective in (0, 1)]

    shaped_rewards = [[], []]
    canonical_rewards = [[], []]
    for action in (0, 3, 1, 4, 2):
        result = env.step(action)[0]
        for perspective in (0, 1):
            shaped_rewards[perspective].append(result["rewards"][perspective])
            canonical_rewards[perspective].append(result["info"][f"canonical_reward_player_{perspective}"])

    assert result["done"]
    assert result["info"]["success"]
    for perspective in (0, 1):
        shaped_return = sum(discount**step * reward for step, reward in enumerate(shaped_rewards[perspective]))
        canonical_return = sum(discount**step * reward for step, reward in enumerate(canonical_rewards[perspective]))
        assert math.isclose(
            shaped_return,
            2 * canonical_return - initial_values[perspective],
            abs_tol=1e-12,
        )


def test_invalid_response_is_not_canonical_game_utility():
    env = TicTacToe(
        TicTacToeConfig(
            built_in_opponent="none",
            reward_mode="minimax_shaped",
            minimax_discount=0.9,
            precompute_minimax=True,
        )
    )
    env.reset(seed=0)
    env.step(0)

    board = env._render_text()
    values_before = [
        env.minimax_evaluator.value(
            tuple(0 if cell == "_" else 1 if cell == "X" else -1 for cell in board.replace("\n", "")),
            perspective,
        )
        for perspective in (0, 1)
    ]
    result = env.get_losing_state(player_id=1)[0]

    assert result["info"]["canonical_reward_player_0"] == 0.0
    assert result["info"]["canonical_reward_player_1"] == 0.0
    assert result["info"]["winner"] == -1
    assert result["info"]["minimax_valid_action"] == 0.0
    assert result["rewards"] == [-values_before[0], -values_before[1]]
