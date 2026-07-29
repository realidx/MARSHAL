import importlib.util
import math
from pathlib import Path


MODULE_PATH = Path(__file__).parents[3] / "roll/agentic/env/tictactoe/minimax.py"
SPEC = importlib.util.spec_from_file_location("tictactoe_minimax", MODULE_PATH)
MINIMAX = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MINIMAX)

EMPTY_BOARD = MINIMAX.EMPTY_BOARD
ExactTicTacToeEvaluator = MINIMAX.ExactTicTacToeEvaluator
apply_action = MINIMAX.apply_action
current_player = MINIMAX.current_player
is_terminal = MINIMAX.is_terminal
terminal_utility = MINIMAX.terminal_utility


def test_exact_values_are_zero_sum_and_bellman_consistent():
    evaluator = ExactTicTacToeEvaluator(discount=0.9)
    evaluator.precompute()

    for board in evaluator.reachable_boards():
        if is_terminal(board):
            assert evaluator.value(board, 0) == 0
            assert evaluator.value(board, 1) == 0
            continue

        assert math.isclose(
            evaluator.value(board, 0),
            -evaluator.value(board, 1),
            abs_tol=1e-12,
        )
        acting_player = current_player(board)
        action_values = evaluator.action_values(board, acting_player)
        assert math.isclose(
            evaluator.value(board, acting_player),
            max(action_values.values()),
            abs_tol=1e-12,
        )


def test_immediate_terminal_action_has_undiscounted_utility():
    # X X .
    # O O .
    # . . .
    board = (1, 1, 0, -1, -1, 0, 0, 0, 0)
    evaluator = ExactTicTacToeEvaluator(discount=0.9)

    assert evaluator.action_value(board, action=2, perspective=0) == 1
    assert evaluator.action_value(board, action=2, perspective=1) == -1


def test_shaped_rewards_telescope_for_both_fixed_player_perspectives():
    evaluator = ExactTicTacToeEvaluator(discount=0.9)
    actions = (0, 3, 1, 4, 2)  # player 0 wins

    for perspective in (0, 1):
        board = EMPTY_BOARD
        shaped_rewards = []
        environment_rewards = []

        for action in actions:
            value_before = evaluator.value(board, perspective)
            next_board = apply_action(board, action)
            environment_reward = terminal_utility(next_board, perspective) if is_terminal(next_board) else 0.0
            value_after = evaluator.value(next_board, perspective)
            shaped_rewards.append(2 * environment_reward + evaluator.discount * value_after - value_before)
            environment_rewards.append(environment_reward)
            board = next_board

        shaped_return = sum(evaluator.discount**step * reward for step, reward in enumerate(shaped_rewards))
        environment_return = sum(evaluator.discount**step * reward for step, reward in enumerate(environment_rewards))
        expected = 2 * environment_return - evaluator.value(EMPTY_BOARD, perspective)
        assert math.isclose(shaped_return, expected, abs_tol=1e-12)
