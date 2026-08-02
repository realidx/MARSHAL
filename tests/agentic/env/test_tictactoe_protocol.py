from roll.agentic.tictactoe_protocol import (
    action_to_string,
    recover_action,
    string_to_action,
)
from roll.agentic.env.tictactoe.config import TicTacToeConfig
from roll.agentic.env.tictactoe.env import TicTacToe


def test_tictactoe_uses_simple_canonical_action_strings():
    assert action_to_string(0, 0) == "X(0,0)"
    assert action_to_string(1, 8) == "O(2,2)"
    assert string_to_action("X(0,0)") == 0
    assert string_to_action("<O(2,2)>") == 8


def test_tictactoe_uses_compact_reason_answer_prompt():
    env = TicTacToe.__new__(TicTacToe)
    env.config = TicTacToeConfig(response_token_limit=600)

    prefix = env._get_prefix_prompt(player_id=1)
    turn = env.format_turn_prompt(
        state="_X_\n_O_\nX__",
        legal_actions={0: "O(0,0)", 2: "O(0,2)", 8: "O(2,2)"},
        player_id=1,
    )

    assert prefix["system"] == "You are playing Tic-Tac-Toe."
    assert (
        "Analyze the strategy as concisely as possible and choose exactly one legal action."
        in prefix["user"]
    )
    assert "<reason>one brief reason</reason>" in prefix["user"]
    assert "<answer><SYMBOL(row,column)></answer>" in prefix["user"]
    assert "horizontal" not in prefix["user"]
    assert "You are player O." in turn
    assert "  0 1 2" in turn
    assert "0 . X ." in turn
    assert "Legal moves:\nO(0,0), O(0,2), O(2,2)" in turn



def test_tictactoe_recovers_known_format_variants():
    legal_actions = {0: "O(0,0)", 4: "O(1,1)"}

    assert recover_action(
        "<think>Choose the corner.</think><answer>O(0,0)</answer>",
        legal_actions,
    ) == "O(0,0)"
    assert recover_action(
        "<think>Choose the corner.</think><answer><O(0,0)></answer>",
        legal_actions,
    ) == "O(0,0)"
    assert recover_action(
        "<think>Choose the corner.</think><O(0,0)>",
        legal_actions,
    ) is None


def test_tictactoe_does_not_recover_ambiguous_or_illegal_actions():
    legal_actions = {0: "O(0,0)", 4: "O(1,1)"}

    assert recover_action(
        "<answer>O(0,0) or O(1,1)</answer>",
        legal_actions,
    ) is None
    assert recover_action("<answer>O(2,2)</answer>", legal_actions) is None
    assert recover_action(
        "<reason>O(0,0) is strongest.</reason>", legal_actions
    ) is None
