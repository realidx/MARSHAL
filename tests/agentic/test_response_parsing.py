from roll.agentic.response_parsing import generation_limit_status, has_closed_answer


def test_600_token_limit_only_counts_an_actual_cap_hit():
    assert generation_limit_status("<reason>unfinished", 599, 600) == (False, False)
    assert generation_limit_status("<reason>unfinished", 600, 600) == (True, True)


def test_cap_hit_with_a_closed_answer_is_not_invalidated():
    response = "<reason>blocks the fork</reason><answer>O(0,0)</answer>"

    assert generation_limit_status(response, 600, 600) == (True, False)


def test_closed_answer_requires_both_answer_tags_at_the_end():
    assert has_closed_answer("<reason>wins now</reason><answer>X(1,1)</answer>")
    assert not has_closed_answer("<reason>done</reason></answer>")
    assert not has_closed_answer("<answer>X(1,1)</answer> trailing")
