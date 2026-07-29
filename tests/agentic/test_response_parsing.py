from roll.agentic.response_parsing import generation_limit_status


def test_4096_token_limit_detects_incomplete_near_cap_responses():
    assert generation_limit_status("<think>unfinished", 4096, 4096) == (True, True)
    assert generation_limit_status("<think>trimmed</think>", 4080, 4096) == (True, True)
    assert generation_limit_status("<think>short", 4079, 4096) == (False, False)


def test_4096_token_limit_does_not_mark_a_closed_answer_truncated():
    response = "<think>long</think><answer>O(0,0)</answer>"

    assert generation_limit_status(response, 4096, 4096) == (True, False)
