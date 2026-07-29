from roll.agentic.response_parsing import generation_limit_status


def test_2046_token_limit_detects_incomplete_near_cap_responses():
    assert generation_limit_status("<think>unfinished", 2046, 2046) == (True, True)
    assert generation_limit_status("<think>trimmed</think>", 2030, 2046) == (True, True)
    assert generation_limit_status("<think>short", 2029, 2046) == (False, False)


def test_2046_token_limit_does_not_mark_a_closed_answer_truncated():
    response = "<think>long</think><answer>O(0,0)</answer>"

    assert generation_limit_status(response, 2046, 2046) == (True, False)
