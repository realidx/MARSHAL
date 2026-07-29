from roll.agentic.tictactoe_protocol import (
    action_to_string,
    recover_action,
    string_to_action,
)


def test_tictactoe_uses_simple_canonical_action_strings():
    assert action_to_string(0, 0) == "X(0,0)"
    assert action_to_string(1, 8) == "O(2,2)"
    assert string_to_action("X(0,0)") == 0
    assert string_to_action("<O(2,2)>") == 8


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
    ) == "O(0,0)"


def test_tictactoe_does_not_recover_ambiguous_or_illegal_actions():
    legal_actions = {0: "O(0,0)", 4: "O(1,1)"}

    assert recover_action(
        "<answer>O(0,0) or O(1,1)</answer>",
        legal_actions,
    ) is None
    assert recover_action("<answer>O(2,2)</answer>", legal_actions) is None
