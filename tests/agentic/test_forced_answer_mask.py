import pytest
import torch
from threading import Lock
from types import SimpleNamespace
from roll.agentic.rollout.env_manager import (
    EnvManager,
    EnvStatus,
    get_masks_and_scores,
    select_prompt_history,
    mask_untrainable_response_turns,
    compute_game_step_turn_returns,
)


class _Tokenizer:
    def encode(self, text, add_special_tokens=True):
        if text == "<|im_start|>assistant\n":
            return [99, 42]
        if text == "<|im_end|>":
            return [100]
        raise AssertionError(text)



def test_markovian_generation_selects_only_the_current_state():
    history = [
        {"state": "old", "llm_raw_response": "private reasoning", "reward": 0.0},
        {"state": "current", "legal_actions": {0: "X(0,0)"}},
    ]

    selected = select_prompt_history(
        history,
        prepare_for_update=False,
        use_raw_llm_response=False,
        markovian_turn_context=True,
    )

    assert selected == [history[-1]]
    assert "llm_raw_response" not in selected[0]
    assert history[0]["llm_raw_response"] == "private reasoning"


def test_markovian_training_context_fails_instead_of_silently_mismatching_rollout():
    history = [
        {"state": "old", "llm_raw_response": "private reasoning", "reward": 0.0},
        {"state": "current", "legal_actions": {0: "X(0,0)"}},
    ]

    with pytest.raises(ValueError, match="on-policy training sample"):
        select_prompt_history(
            history,
            prepare_for_update=True,
            use_raw_llm_response=False,
            markovian_turn_context=True,
        )


class _ChatTokenizer:
    def apply_chat_template(self, messages, add_generation_prompt, tokenize):
        suffix = "<assistant>" if add_generation_prompt else ""
        return repr(messages) + suffix


class _PromptEnv:
    include_opponent_turn = "full"

    def get_prompt(self, mode, think, player_id):
        return {"system": "system", "user": "instructions"}


def test_rollout_formatting_excludes_nullable_terminal_state_for_raw_text():
    decision = {
        "player": 0,
        "state": "___\n___\n___",
        "legal_actions": {0: "X(0,0)"},
        "actions": "X(0,0)",
        "llm_raw_response": "<think>brief</think><answer>X(0,0)</answer>",
        "reward": 1.0,
    }
    terminal_state = {"player": None, "state": None, "legal_actions": None}
    manager = EnvManager.__new__(EnvManager)
    manager.rollout_cache = {"history": [decision, terminal_state]}
    manager.pipeline_config = SimpleNamespace(
        markovian_turn_context=False, enable_think=True, use_reason_answer_format=False
    )
    manager.env_entry = {"env": _PromptEnv()}
    manager.processor = None
    manager.tokenizer = _ChatTokenizer()

    _, messages_list = manager._format_messages(
        prepare_for_update=True,
        use_raw_llm_response=True,
        player_id=0,
    )

    messages = messages_list[0]
    assert [message["role"] for message in messages] == ["system", "user", "assistant"]
    assert "X(0,0)" in messages[1]["content"]

def test_reason_answer_generation_has_no_assistant_prefill():
    state = {"player": 0, "state": "___\n___\n___", "legal_actions": {0: "X(0,0)"}}
    manager = EnvManager.__new__(EnvManager)
    manager.rollout_cache = {"history": [state]}
    manager.pipeline_config = SimpleNamespace(
        markovian_turn_context=True, enable_think=False, use_reason_answer_format=True
    )
    manager.env_entry = {"env": _PromptEnv()}
    manager.processor = None
    manager.tokenizer = _ChatTokenizer()

    texts, _ = manager._format_messages(
        prepare_for_update=False,
        use_raw_llm_response=False,
        player_id=0,
    )

    assert texts[0].endswith("<assistant>")
    assert not texts[0].endswith("<think>\n")
    assert not texts[0].endswith("<answer>")

def _reason_answer_manager():
    manager = EnvManager.__new__(EnvManager)
    manager.pipeline_config = SimpleNamespace(
        use_reason_answer_format=True,
        enable_think=False,
        action_sep="||",
        special_token_list=[
            "<reason>",
            "</reason>",
            "<answer>",
            "</answer>",
            "<|im_start|>",
            "<|im_end|>",
        ],
    )
    return manager


def test_reason_answer_parser_extracts_actions_only_from_answer():
    manager = _reason_answer_manager()
    response = "<reason>Center controls the most lines.</reason><answer>X(1,1)</answer>"
    processed, actions, valid = manager._parse_response(response)

    assert actions == ["X(1,1)"]
    assert valid is True
    assert processed == response

    _, actions, valid = manager._parse_response("<answer>X(1,1)</answer>")
    assert actions == ["X(1,1)"]
    assert valid is False

    _, actions, valid = manager._parse_response("<reason>Play X(1,1).</reason>")
    assert actions == [] and valid is False

    long_reason = " ".join(["word"] * 21)
    _, actions, valid = manager._parse_response(
        f"<reason>{long_reason}</reason><answer>X(1,1)</answer>"
    )
    assert actions == ["X(1,1)"]

    assert valid is True


def test_generation_context_limit_uses_actor_inference_config():
    manager = EnvManager.__new__(EnvManager)
    manager.worker_config = SimpleNamespace(strategy_args=None)
    manager.pipeline_config = SimpleNamespace(
        sequence_length=8192,
        actor_infer=SimpleNamespace(
            strategy_args=SimpleNamespace(strategy_config={"max_model_len": 2048})
        ),
    )

    assert manager._generation_context_limit() == 2048

def test_policy_response_mask_keeps_reason_and_answer_tokens():
    input_ids = torch.tensor([[99, 1, 99, 2, 99, 42, 10, 11, 12, 13, 100]])
    _, _, response_mask, _, _ = get_masks_and_scores(
        input_ids=input_ids,
        tokenizer=_Tokenizer(),
        all_scores=[[1.0]],
    )

    assert response_mask[0, 6:8].tolist() == [True, True]
    assert response_mask[0, 8:10].tolist() == [True, True]



def test_retry_boundary_sets_zero_token_continuation():
    input_ids = torch.tensor([[99, 1, 99, 2, 99, 42, 10, 100, 99, 2, 99, 42, 11, 100]])
    _, _, _, _, continuation_discounts = get_masks_and_scores(
        input_ids=input_ids,
        tokenizer=_Tokenizer(),
        all_scores=[[-0.1, 0.5]],
        use_turn_scores=True,
        all_turn_steps=[[0, 1]],
        all_return_boundaries=[[True, False]],
        game_step_discount=0.9,
    )

    assert continuation_discounts[0, 7] == 0.0
    assert torch.isclose(continuation_discounts[0, 13], torch.tensor(0.9))



def test_runtime_synthetic_response_turn_is_not_trainable():
    input_ids = torch.tensor([[99, 1, 99, 2, 99, 3, 4, 99, 5, 99, 6]])
    response_mask = torch.ones_like(input_ids, dtype=torch.bool)
    non_prompt_mask = torch.ones_like(input_ids, dtype=torch.bool)

    response_mask, non_prompt_mask = mask_untrainable_response_turns(
        input_ids,
        response_mask,
        non_prompt_mask,
        _Tokenizer(),
        [1],
    )

    assert response_mask[0, 4:7].tolist() == [True, True, True]
    assert response_mask[0, 10:].tolist() == [False]
    assert non_prompt_mask[0, 10:].tolist() == [False]


class _ArtificialTerminalEnv:
    def get_losing_state(self, player_id, overlong_response, overlong_sequence):
        assert player_id == 0
        assert overlong_response is False
        assert overlong_sequence is True
        return [
            {
                "current_player": 0,
                "action": "",
                "rewards": [0.0, 0.0],
                "done": True,
                "info": {"success": False, "minimax_valid_action": 0.0, "artificial_truncation": 1.0},
                "next_player": None,
                "observation": None,
                "legal_actions": None,
            }
        ]


def test_failed_generation_closes_episode_and_records_masked_artificial_turn():
    state = {"player": 0, "state": "___\n___\n___", "legal_actions": {0: "X(0,0)"}}
    manager = EnvManager.__new__(EnvManager)
    manager.rollout_cache = {
        "current_player": 0,
        "history": [state.copy()],
        "player_0_history": [state.copy()],
        "player_1_history": [],
        "terminal_info": {},
    }
    manager.env_entry = {
        "env": _ArtificialTerminalEnv(),
        "status": EnvStatus(),
        "max_actions_per_traj": 10,
    }
    manager.pipeline_config = SimpleNamespace(
        sequence_length=100,
        actor_infer=SimpleNamespace(
            strategy_args=SimpleNamespace(strategy_config={"max_model_len": 100})
        ),
    )
    manager.worker_config = SimpleNamespace(
        enable_length_penalty=False,
        minimax_length_penalty_beta=0.1,
        minimax_length_soft_budget=200,
        minimax_length_hard_budget=600,
        format_penalty=-0.1,
        strategy_args=None,
    )
    manager.internal_lock = Lock()

    status = manager._terminate_failed_generation(current_sequence_length=100)

    assert status.done
    assert status.truncated
    assert status.step == 0
    assert status.num_actions == 0
    turn = manager.rollout_cache["player_0_history"][0]
    assert turn["reward"] == -0.1
    assert turn["skip_policy_response"] is True
    assert turn["valid_action"] is False
    assert turn["transition_rewards"] == []
    assert turn["return_boundary"] is True
    assert manager.rollout_cache["terminal_info"]["generation_failed"] == 1.0


def test_retry_boundary_stops_future_return():
    returns = compute_game_step_turn_returns(
        turn_scores=[-0.1, 0.5],
        turn_steps=[0, 1],
        discount=0.9,
        return_boundaries=[True, False],
    )
    assert returns == [-0.1, 0.5]


def test_minimax_soft_length_penalty_matches_formula():
    manager = EnvManager.__new__(EnvManager)
    manager.worker_config = SimpleNamespace(
        minimax_length_penalty_beta=0.1,
        minimax_length_soft_budget=200,
        minimax_length_hard_budget=600,
    )
    optimal = {"minimax_valid_action": 1.0, "minimax_optimal_action": 1.0}
    suboptimal = {"minimax_valid_action": 1.0, "minimax_optimal_action": 0.0}

    assert manager.compute_minimax_length_penalty(50, optimal, True) == 0.0
    assert manager.compute_minimax_length_penalty(200, optimal, True) == 0.0
    assert manager.compute_minimax_length_penalty(300, optimal, True) == -0.025
    assert manager.compute_minimax_length_penalty(600, optimal, True) == -0.1
    assert manager.compute_minimax_length_penalty(900, optimal, True) == -0.1
    assert manager.compute_minimax_length_penalty(300, suboptimal, True) == -0.025
    assert manager.compute_minimax_length_penalty(300, optimal, False) == 0.0



def test_retry_logging_is_zero_step_and_does_not_update_opponent_history():
    manager = EnvManager.__new__(EnvManager)
    manager.internal_lock = Lock()
    manager.worker_config = SimpleNamespace(
        enable_length_penalty=False,
        minimax_length_penalty_beta=0.1,
        minimax_length_soft_budget=200,
        minimax_length_hard_budget=600,
    )
    manager.env_entry = {"status": EnvStatus(), "max_actions_per_traj": 9}
    initial = {"player": 0, "state": "___\n___\n___", "legal_actions": {0: "X(0,0)"}}
    opponent = {"player": 1, "state": "old", "legal_actions": {}}
    manager.rollout_cache = {
        "history": [initial.copy()],
        "player_0_history": [initial.copy()],
        "player_1_history": [opponent.copy()],
        "terminal_info": {},
    }
    retry_result = [{
        "current_player": 0,
        "action": "",
        "rewards": [0.0, 0.0],
        "done": False,
        "info": {"retry_attempt": 1.0, "minimax_valid_action": 0.0},
        "next_player": 0,
        "observation": "corrective prompt\n\n___\n___\n___",
        "legal_actions": {0: "X(0,0)"},
    }]
    env_input = {
        "llm_response": "<answer>INVALID</answer>",
        "llm_raw_response": "invalid",
        "current_sequence_length": 100,
        "token_length": 10,
        "token_left": 1900,
        "effective_max_new_tokens": 600,
        "hit_token_limit": False,
        "has_closing_answer_tag": False,
        "valid_action": False,
        "overlong_response": False,
        "overlong_sequence": False,
        "retry_attempt_index": 0,
        "decision_index": 0,
        "retry_scheduled": True,
    }

    manager._log_env_state(retry_result, current_player=0, format_reward=-0.1, env_input=env_input)

    assert manager.env_entry["status"].step == 0
    assert manager.env_entry["status"].num_actions == 0
    assert manager.rollout_cache["history"][0]["transition_rewards"] == []
    assert manager.rollout_cache["history"][0]["auxiliary_reward"] == -0.1
    assert manager.rollout_cache["history"][0]["return_boundary"] is True
    assert len(manager.rollout_cache["player_0_history"]) == 2
    assert manager.rollout_cache["player_1_history"] == [opponent]
