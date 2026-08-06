import copy
import re
import time
import traceback
from contextlib import nullcontext
from dataclasses import dataclass, field, asdict
from itertools import zip_longest
from threading import Thread, Lock
from typing import Dict, List, Optional, Union, Tuple

import PIL
import numpy as np
import random
import ray
import torch
from ray.util.queue import Queue, Empty
from tensordict import TensorDict
from transformers import AutoTokenizer, PreTrainedTokenizer, ProcessorMixin

from roll.agentic.env import REGISTERED_ENVS, REGISTERED_ENV_CONFIGS
from roll.agentic.response_parsing import generation_limit_status, has_closed_answer
from roll.distributed.scheduler.generate_scheduler import GlobalCounter, RequestScheduler
from roll.distributed.scheduler.protocol import DataProto
from roll.pipeline.agentic.agentic_config import EnvManagerConfig, AgenticConfig
from roll.utils.constants import RAY_NAMESPACE
from roll.utils.functionals import pad_to_length
from roll.utils.logging import get_logger

"""
base agentic codes reference: https://github.com/RAGEN-AI/RAGEN/blob/main/ragen/llm_agent/es_manager.py
"""

index_table = {
    1: "first",
    2: "second",
    3: "third",
    4: "fourth",
    5: "fifth",
    6: "sixth",
    7: "seventh",
    8: "eighth",
    9: "ninth",
    10: "tenth",
    11: "eleventh",
    12: "twelfth",
    13: "thirteenth",
    14: "fourteenth",
    15: "fifteenth",
    16: "sixteenth",
    17: "seventeenth",
    18: "eighteenth",
    19: "nineteenth",
    20: "twentieth",
}


@dataclass
class EnvStatus:
    """Status of an environment"""

    truncated: bool = False  # done but not success
    terminated: bool = False  # done and success
    num_actions: int = 0  # current action step (single action)
    generation_attempts: int = 0
    retry_attempts: int = 0
    rewards: List[float] = field(default_factory=list)  # rewards for each turn
    seed: Optional[int] = None  # what seed is used to reset this environment
    step: int = 0  # current step (single step)

    @property
    def done(self):
        return self.truncated or self.terminated


def get_masks_and_scores(
    input_ids: torch.Tensor,
    tokenizer: AutoTokenizer,
    all_scores: List[List[float]] = None,
    use_turn_scores: bool = False,
    all_turn_steps: Optional[List[List[int]]] = None,
    all_return_boundaries: Optional[List[List[bool]]] = None,
    game_step_discount: Optional[float] = None,
):
    """
    input_ids: shape (bsz, seq_len)
    all_scores: list[list[float], 存储每个env每轮的reward
    Get loss mask that only learns between <|im_start|>assistant and <|im_end|>. Currently only supports qwen.
    NOTE: important! This assumes that the input_ids starts with system and then user & assistant in alternative ways
    NOTE: important! input_ids is left pad
    """
    # TODO: special tokens add to config
    assistant_turn_start_tokens = tokenizer.encode("<|im_start|>assistant\n")
    turn_start_token = assistant_turn_start_tokens[0]
    turn_starts = torch.where(input_ids == turn_start_token, 1, 0)
    turn_indicators = torch.cumsum(turn_starts, dim=-1)

    response_mask = (turn_indicators % 2 == 1) & (turn_indicators > 1)  # only learns all assistant turns
    non_prompt_mask = turn_indicators > 2  # learns everything after system prompt + user prompts

    # turn text: '<|im_start|>assistant\n<answer>Right</answer><|im_end|>'
    # <|im_start|>assistant\n 应该mask掉才对，保留<|im_end|>
    for idx, scores in enumerate(zip_longest(*all_scores, fillvalue=0)):
        """
        system, user, assistant, user, assistant, user, assistant
        1,2,3,3,4,5,6
        assistant位于第3,5,7...
        """
        turn_indicator = idx * 2 + 3  # 0: pad. 1: system. 2+2n: user. 3+2n: assistant
        turn_start_position = (input_ids == turn_start_token) & (turn_indicators == turn_indicator)
        batch_size, seq_len = input_ids.shape
        num_tokens = len(assistant_turn_start_tokens)
        turn_start_indices = turn_start_position.nonzero(as_tuple=True)
        mask_matrix = torch.zeros((batch_size, seq_len), dtype=torch.bool, device=input_ids.device)
        for batch_idx, start_idx in zip(turn_start_indices[0], turn_start_indices[1]):
            end_idx = start_idx + num_tokens
            if end_idx <= seq_len:
                mask_matrix[batch_idx, start_idx:end_idx] = True
        response_mask[mask_matrix] = False
        if idx == 0:
            non_prompt_mask[mask_matrix] = False

    # TODO: special tokens add to config
    reward_token = tokenizer.encode("<|im_end|>")[0]
    score_tensor = torch.zeros_like(input_ids, dtype=torch.float32)
    
    # 新增：记录每个turn结尾位置的变量
    turn_end_positions = torch.zeros_like(input_ids, dtype=torch.bool)
    continuation_discounts = torch.ones_like(input_ids, dtype=torch.float32)
    
    if use_turn_scores:
        for idx, scores in enumerate(zip_longest(*all_scores, fillvalue=0)):
            scores = torch.tensor(scores, dtype=torch.float32)
            turn_indicator = idx * 2 + 3  # 0: pad. 1: system. 2+2n: user. 3+2n: assistant
            reward_position = (input_ids == reward_token) & (turn_indicators == turn_indicator)
            # Set the last token of the rows where all positions are False to True
            reward_position[~reward_position.any(dim=-1), -1] = True
            # 记录当前turn的结尾位置
            turn_end_positions = turn_end_positions | reward_position
            score_tensor[reward_position] = scores
            if game_step_discount is not None:
                if all_turn_steps is None:
                    raise ValueError("all_turn_steps is required when game_step_discount is set")
                turn_steps = torch.tensor(
                    tuple(zip_longest(*all_turn_steps, fillvalue=1))[idx],
                    dtype=torch.float32,
                    device=input_ids.device,
                )
                continuation_discounts[reward_position] = game_step_discount ** turn_steps
                if all_return_boundaries is not None:
                    return_boundaries = torch.tensor(
                        tuple(zip_longest(*all_return_boundaries, fillvalue=False))[idx],
                        dtype=torch.bool,
                        device=input_ids.device,
                    )
                    continuation_discounts[reward_position] = torch.where(
                        return_boundaries,
                        torch.zeros_like(turn_steps),
                        continuation_discounts[reward_position],
                    )
    else:
        scores = [sum(i) for i in all_scores]
        score_tensor[:, -1] = torch.tensor(scores, dtype=torch.float32)
        # 在非turn_scores模式下，所有turn的结尾位置都在序列末尾
        turn_end_positions[:, -1] = True

    return non_prompt_mask, score_tensor, response_mask, turn_end_positions, continuation_discounts



def select_prompt_history(
    history: List[Dict],
    prepare_for_update: bool,
    use_raw_llm_response: bool,
    markovian_turn_context: bool,
) -> List[Dict]:
    """Select history without mutating the rollout cache."""
    if prepare_for_update and markovian_turn_context:
        raise ValueError(
            "markovian_turn_context cannot reconstruct an on-policy training sample; "
            "disable it or emit each decision as a separate rollout"
        )
    selected = history
    if prepare_for_update and selected and "reward" not in selected[-1]:
        selected = selected[:-1]
    if not prepare_for_update and markovian_turn_context:
        selected = selected[-1:]
    return selected


def mask_untrainable_response_turns(
    input_ids: torch.Tensor,
    response_mask: torch.Tensor,
    non_prompt_mask: torch.Tensor,
    tokenizer: AutoTokenizer,
    turn_indices: List[int],
) -> Tuple[torch.Tensor, torch.Tensor]:
    """Mask assistant turns that were synthesized by the runtime."""
    if not turn_indices:
        return response_mask, non_prompt_mask
    assistant_start_token = tokenizer.encode("<|im_start|>assistant\n")[0]
    turn_indicators = torch.cumsum(input_ids == assistant_start_token, dim=-1)
    for turn_index in turn_indices:
        turn_indicator = turn_index * 2 + 3
        synthetic_turn = turn_indicators == turn_indicator
        response_mask[synthetic_turn] = False
        non_prompt_mask[synthetic_turn] = False
    return response_mask, non_prompt_mask


def compute_game_step_turn_returns(
    turn_scores: List[float],
    turn_steps: List[int],
    discount: float,
    return_boundaries: Optional[List[bool]] = None,
) -> List[float]:
    """Compute diagnostic return-to-go values at player decision boundaries."""
    if len(turn_scores) != len(turn_steps):
        raise ValueError("turn_scores and turn_steps must have the same length")
    if return_boundaries is None:
        return_boundaries = [False] * len(turn_scores)
    if len(return_boundaries) != len(turn_scores):
        raise ValueError("return_boundaries and turn_scores must have the same length")
    returns_reversed = []
    continuation = 0.0
    for score, step_count, stop_return in reversed(
        tuple(zip(turn_scores, turn_steps, return_boundaries))
    ):
        if step_count < 0:
            raise ValueError(f"Environment step count cannot be negative, got {step_count}")
        continuation = score if stop_return else score + discount**step_count * continuation
        returns_reversed.append(continuation)
    return list(reversed(returns_reversed))


def distribute_token_local_length_penalty(
    score_tensor: torch.Tensor,
    response_mask: torch.Tensor,
    soft_budget: int,
    sequence_penalties: List[float],
    generated_token_lengths: Optional[List[int]] = None,
) -> torch.Tensor:
    """Place a sequence length penalty on the policy-token suffix beyond a soft budget.

    ``generated_token_lengths`` refers to the original inference tokenization.  It
    can differ from the policy mask length when a legacy sample was decoded and
    retokenized.  In that case, map the same over-budget fraction onto the tail of
    the policy tokens while preserving the scalar sequence penalty exactly.
    """
    if generated_token_lengths is not None and len(generated_token_lengths) != len(
        sequence_penalties
    ):
        raise ValueError("generated_token_lengths and sequence_penalties must have the same length")
    result = score_tensor.clone()
    token_ordinals = torch.cumsum(response_mask.long(), dim=-1)
    for row, penalty in enumerate(sequence_penalties):
        if penalty == 0:
            continue
        row_mask = response_mask[row].bool()
        policy_token_count = int(row_mask.sum().item())
        if policy_token_count == 0:
            raise ValueError("non-zero length penalty has no trainable response tokens")

        if generated_token_lengths is None:
            positions = row_mask & (token_ordinals[row] > soft_budget)
        else:
            generated_length = max(int(generated_token_lengths[row]), 1)
            generated_excess = max(generated_length - soft_budget, 0)
            # A non-zero penalty should imply generated_excess > 0.  Retain a
            # safe one-token fallback so malformed legacy metadata cannot abort
            # a long training run.
            tail_count = max(
                1,
                (policy_token_count * generated_excess + generated_length - 1)
                // generated_length,
            )
            tail_count = min(tail_count, policy_token_count)
            policy_positions = row_mask.nonzero(as_tuple=True)[0]
            positions = torch.zeros_like(row_mask)
            positions[policy_positions[-tail_count:]] = True

        count = int(positions.sum().item())
        if count == 0:
            # This remains useful for callers without generation-token metadata.
            positions = torch.zeros_like(row_mask)
            positions[row_mask.nonzero(as_tuple=True)[0][-1]] = True
            count = 1
        result[row, positions] += float(penalty) / count
    return result


class EnvManager:
    def __init__(
        self,
        worker_config: EnvManagerConfig,
        pipeline_config: AgenticConfig,
        env_config: Dict,
        tokenizer: PreTrainedTokenizer,
        generate_scheduler,
        input_queue: Queue,
        output_queue: Queue,
        thread_lock: Lock,
        processor: Optional[ProcessorMixin] = None,
        collator: Optional[callable] = None,
        mode="train",
    ):
        """
        1. 一个EnvManager持有一个env实例: 执行env.reset, env.step, 管理rollout的状态
            group trajectory表达: group内的init state一致，依赖env_config 中的seed来控制, 一个group内env 对应episode的seed一致
            EnvWorker持有多个EnvManager，通过线程的方式实现EnvWorker内部并行
        2. run_rollout_loop, 持续rollout trajectory, 将done的trajectory回传到output_queue
        TODO:
            1. special tokens add to config
            2. ray max_concurrency 描述多线程是否会更好？
        """
        self.logger = get_logger()
        self.worker_config: EnvManagerConfig = worker_config
        self.pipeline_config = pipeline_config
        self.env_config: Dict = env_config
        self.tokenizer: PreTrainedTokenizer = tokenizer
        self.processor: ProcessorMixin = processor
        self.collator = collator
        self.env_entry = None
        self.output_queue = output_queue
        self.input_queue = input_queue
        self.mode = mode
        self.generate_scheduler: RequestScheduler = generate_scheduler
        self.rollout_cache = None
        self.group_seed = None
        self.episode_id = 0
        self.process_input_queue_thread = None
        self.running = False
        self.use_thread_lock = self.env_config.get(
            "use_thread_lock", True
        )  # 避免同时执行大量cpu操作, 可以通过env_config配置
        self.thread_lock = thread_lock if self.use_thread_lock else nullcontext()
        
        # 新增：保护EnvManager内部状态的锁
        from threading import Lock
        self.internal_lock = Lock()

        self.env_entry = copy.deepcopy(self.env_config)
        self.env_entry["env"] = REGISTERED_ENVS[self.env_entry["env_class"]](self.env_entry["config"])
        self.env_entry["status"] = EnvStatus()
        env_reward_mode = getattr(self.env_entry["env"], "reward_mode", None)
        env_discount = getattr(getattr(self.env_entry["env"], "config", None), "minimax_discount", None)
        if env_reward_mode == "minimax_shaped":
            if self.pipeline_config.game_step_discount is None:
                raise ValueError("minimax_shaped rewards require game_step_discount")
            if abs(self.pipeline_config.game_step_discount - env_discount) > 1e-12:
                raise ValueError(
                    "game_step_discount must match the Tic-Tac-Toe minimax_discount "
                    f"({self.pipeline_config.game_step_discount} != {env_discount})"
                )

        self.request_counter = GlobalCounter.options(
            name=f"EnvManagerRequestCounter",
            get_if_exists=True,
            namespace=RAY_NAMESPACE,
        ).remote()
        self.request_id: Optional[str] = None

        # Template modification to render thinking state in previous rounds...

        template = '{%- if tools %}\n    {{- \'<|im_start|>system\\n\' }}\n    {%- if messages[0][\'role\'] == \'system\' %}\n        {{- messages[0][\'content\'] }}\n    {%- else %}\n        {{- \'You are a helpful assistant.\' }}\n    {%- endif %}\n    {{- "\\n\\n# Tools\\n\\nYou may call one or more functions to assist with the user query.\\n\\nYou are provided with function signatures within <tools></tools> XML tags:\\n<tools>" }}\n    {%- for tool in tools %}\n        {{- "\\n" }}\n        {{- tool | tojson }}\n    {%- endfor %}\n    {{- "\\n</tools>\\n\\nFor each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:\\n<tool_call>\\n{\\"name\\": <function-name>, \\"arguments\\": <args-json-object>}\\n</tool_call><|im_end|>\\n" }}\n{%- else %}\n    {%- if messages[0][\'role\'] == \'system\' %}\n        {{- \'<|im_start|>system\\n\' + messages[0][\'content\'] + \'<|im_end|>\\n\' }}\n    {%- else %}\n        {{- \'<|im_start|>system\\nYou are a helpful assistant.<|im_end|>\\n\' }}\n    {%- endif %}\n{%- endif %}\n{%- for message in messages %}\n    {%- if (message.role == "user") or (message.role == "system" and not loop.first) or (message.role == "assistant" and not message.tool_calls) %}\n        {{- \'<|im_start|>\' + message.role + \'\\n\' + message.content + \'<|im_end|>\' + \'\\n\' }}\n    {%- elif message.role == "assistant" %}\n        {{- \'<|im_start|>\' + message.role }}\n        {%- if message.content %}\n            {{- \'\\n\' + message.content }}\n        {%- endif %}\n        {%- for tool_call in message.tool_calls %}\n            {%- if tool_call.function is defined %}\n                {%- set tool_call = tool_call.function %}\n            {%- endif %}\n            {{- \'\\n<tool_call>\\n{"name": "\' }}\n            {{- tool_call.name }}\n            {{- \'", "arguments": \' }}\n            {{- tool_call.arguments | tojson }}\n            {{- \'}\\n</tool_call>\' }}\n        {%- endfor %}\n        {{- \'<|im_end|>\\n\' }}\n    {%- elif message.role == "tool" %}\n        {%- if (loop.index0 == 0) or (messages[loop.index0 - 1].role != "tool") %}\n            {{- \'<|im_start|>user\' }}\n        {%- endif %}\n        {{- \'\\n<tool_response>\\n\' }}\n        {{- message.content }}\n        {{- \'\\n</tool_response>\' }}\n        {%- if loop.last or (messages[loop.index0 + 1].role != "tool") %}\n            {{- \'<|im_end|>\\n\' }}\n        {%- endif %}\n    {%- endif %}\n{%- endfor %}\n{%- if add_generation_prompt %}\n    {{- \'<|im_start|>assistant\\n\' }}\n{%- endif %}\n'
        if self.tokenizer:
            self.tokenizer.chat_template = template
        if self.processor:
            self.processor.chat_template = template

        self.length_reward_scale = {
            "upper": 0.0,
            "lower": 0.5,
            "min_len": 11,
            "max_len": 2048,
            "coef": 1,
        }

        print(f"Length reward scale: {self.length_reward_scale}")  # For debugging

    def reset(self):
        entry = self.env_entry
        is_self_play = entry["env"].built_in_opponent == "none"
        current_player = 0 if is_self_play else 1 - entry["env"].opponent_player
        
        # 使用内部锁保护rollout_cache的初始化
        with self.internal_lock:
            self.rollout_cache = {
                "env_id": entry["env_id"],
                "history": [],
                "player_0_history": [],
                "player_1_history": [],
                "group_id": entry["group_id"],
                "tag": entry["tag"],
                "penalty": 0,
                "frames": [],
                "terminal_info": {},
                "is_self_play": is_self_play,
                "current_player": current_player,
                "invalid_retries_for_decision": 0,
            }

        seed = self.group_seed + self.episode_id
        entry["status"] = EnvStatus(seed=seed)

        with self.thread_lock:
            initial_observation, execute_results = entry["env"].reset(seed=seed)

        initial_state_entry = {
            "player": 0,
            "state": initial_observation['observation'],
            "legal_actions": initial_observation['legal_actions'],
        }

        # update rollout cache
        self.rollout_cache["history"] = self._update_cache_history(
            self.rollout_cache["history"],
            num_actions_info=None,
            next_state_entry=initial_state_entry,
        )
        
        # For self-play, also initialize player 0 history
        # Note: player 1 history is not initialized here, because the starting state is only for player 0
        self.rollout_cache["player_0_history"] = self._update_cache_history(
            self.rollout_cache["player_0_history"],
            num_actions_info=None,
            next_state_entry=initial_state_entry,
        )

        # log first turn by the built-in opponent (if opponent goes first)
        if execute_results:
            self._log_env_state(execute_results=execute_results, current_player=0)

        self.episode_id += 1
        return self.rollout_cache

    def compute_length_penalty(self, token_length: int) -> float:
        # (tzy) according to orignal design in kimi-1.5, it is better to use a batch of samples to compute min/max length.
        # however, we don't have a batch of samples. moreover, we just want to penalize the length of the response to avoid overthinking.
        # reward = 0.5 - (token_length - min_len) / (max_len - min_len)

        # for response in format: `<answer>X({i},{j})</answer><|im_end|>`(0<=i,j<3), the minimum length is 11.
        min_len = self.length_reward_scale["min_len"]
        max_len = self.length_reward_scale["max_len"]
        reward = 0.0
        # penalize the length of the response
        reward = self.length_reward_scale["coef"] - (token_length - min_len) / (max_len - min_len)

        if reward > 0:
            reward *= self.length_reward_scale["upper"]  # scale to make it comparable with the winning rewards

        if reward < 0:
            reward *= self.length_reward_scale["lower"]  # scale to make it comparable with the winning rewards

        return reward


    def compute_minimax_length_penalty(
        self, token_length: int, decision_info: Dict, valid_action: bool
    ) -> float:
        """Penalize response length independently of action validity or quality."""
        del decision_info, valid_action
        beta = float(self.worker_config.minimax_length_penalty_beta)
        soft_budget = int(self.worker_config.minimax_length_soft_budget)
        hard_budget = int(self.worker_config.minimax_length_hard_budget)
        if beta <= 0:
            return 0.0
        if hard_budget <= soft_budget:
            raise ValueError("minimax_length_hard_budget must exceed minimax_length_soft_budget")
        excess_fraction = (float(token_length) - soft_budget) / (hard_budget - soft_budget)
        return -beta * min(1.0, max(0.0, excess_fraction))


    def step(self, llm_output: DataProto, current_sequence_length: int):
        env_input, overlong_response, overlong_sequence = self.get_env_input(llm_output, current_sequence_length)
        entry = self.env_entry

        # execute actions in env
        current_player = self.rollout_cache['current_player']
        legal_actions = self.rollout_cache["history"][-1]["legal_actions"]
        valid_actions, lose_for_wrong_format = self._extract_map_valid_actions(
            entry,
            env_input["actions"],
            legal_actions,
        )
        format_valid = env_input["envelope_valid"] and not lose_for_wrong_format
        action_recovered = False
        if lose_for_wrong_format:
            recover_action = getattr(entry["env"], "recover_action", None)
            recovered_action = (
                recover_action(env_input["llm_raw_response"], legal_actions)
                if callable(recover_action)
                else None
            )
            if recovered_action is not None:
                valid_actions = [recovered_action]
                action_recovered = True

        semantic_action_valid = len(valid_actions) == 1
        env_input["valid_action"] = (
            format_valid and semantic_action_valid and not overlong_response and not overlong_sequence
        )
        env_input["overlong_response"] = overlong_response
        env_input["overlong_sequence"] = overlong_sequence
        retry_attempt_index = int(self.rollout_cache.get("invalid_retries_for_decision", 0))
        env_input["retry_attempt_index"] = retry_attempt_index
        env_input["decision_index"] = int(entry["status"].num_actions)
        entry["status"].generation_attempts += 1
        invalid_response = not env_input["valid_action"]
        if invalid_response:
            max_retries = int(self.worker_config.max_invalid_retries_per_decision)
            if retry_attempt_index < max_retries:
                execute_results = entry["env"].get_retry_state(
                    current_player,
                    hit_token_limit=bool(env_input["hit_token_limit"]),
                )
                self.rollout_cache["invalid_retries_for_decision"] = retry_attempt_index + 1
                entry["status"].retry_attempts += 1
                env_input["retry_scheduled"] = True
            else:
                execute_results = entry["env"].get_losing_state(
                    current_player, overlong_response, overlong_sequence
                )
                env_input["retry_scheduled"] = False
        else:
            with self.thread_lock:
                execute_results = entry["env"].step(valid_actions[0])
            self.rollout_cache["invalid_retries_for_decision"] = 0
            env_input["retry_scheduled"] = False
        format_reward = (
            min(self.worker_config.format_penalty, 0.0)
            if invalid_response
            else max(self.worker_config.format_penalty, 0.0)
        )
        execute_results[0]["info"].update(
            {
                "format_valid": float(format_valid),
                "semantic_action_valid": float(semantic_action_valid),
                "action_recovered": float(action_recovered),
                "near_generation_limit": float(env_input["near_generation_limit"]),
                "response_truncated": float(overlong_response or overlong_sequence),
            }
        )

        # log the processed env state
        self._log_env_state(
            execute_results=execute_results,
            format_reward=format_reward,
            current_player=current_player,
            env_input=env_input,
        )

        # 保护玩家切换操作
        if self.rollout_cache['is_self_play']:
            with self.internal_lock:
                self.rollout_cache["current_player"] = entry["env"].current_player

        if self.mode == "val":
            frame = entry["env"].render(mode="rgb_array")
            if isinstance(frame, np.ndarray):
                self.rollout_cache["frames"].append(frame)
        return entry["status"]

    def _generate_once(self, lm_input: DataProto, generation_config: Dict) -> Optional[DataProto]:
        gen_batch = lm_input.pop(
            batch_keys=["input_ids", "attention_mask", "position_ids"],
            non_tensor_batch_keys=(["multi_modal_data"] if "multi_modal_data" in lm_input.non_tensor_batch else []),
        )
        gen_batch.meta_info["generation_config"] = generation_config
        gen_batch.meta_info["response_callback_fn"] = self.generate_scheduler.report_response.remote
        self.request_id = str(ray.get(self.request_counter.get_value.remote()))
        gen_batch.meta_info["request_id"] = self.request_id
        gen_batch.meta_info["src_rank"] = self.env_config["env_id"]
        lm_output: DataProto = ray.get(self.generate_scheduler.generate_one_request.remote(data=gen_batch))

        if lm_output is not None:
            gen_batch.meta_info.pop("generation_config")
            lm_input = lm_input.repeat(repeat_times=generation_config["num_return_sequences"])
            lm_output.union(lm_input)
        return lm_output

    def _generation_context_limit(self) -> int:
        strategy_args = getattr(self.pipeline_config.actor_infer, "strategy_args", None)
        strategy_config = getattr(strategy_args, "strategy_config", None) or {}
        max_model_len = strategy_config.get("max_model_len", self.pipeline_config.sequence_length)
        return min(int(max_model_len), int(self.pipeline_config.sequence_length))

    def generate(self, env_output: Dict):
        lm_input: DataProto = self.get_lm_input(env_output, prepare_for_update=False)
        current_sequence_length = lm_input.batch["input_ids"].shape[1]
        token_left = self._generation_context_limit() - current_sequence_length
        generation_config = self.worker_config.generating_args.to_dict()
        generation_config["max_new_tokens"] = max(
            min(generation_config["max_new_tokens"], token_left),
            1,
        )

        if generation_config["max_new_tokens"] <= 1:
            self.logger.warning(
                f"inference sequence limit = {self._generation_context_limit()} input_ids length = {current_sequence_length}"
            )
            return None, current_sequence_length

        return self._generate_once(lm_input, generation_config), current_sequence_length

    def run_rollout_loop(self, data: DataProto):
        """
        1. 每次调用run_rollout_loop,
            会持续的play episode, 直到收到采集完成的command
            需要重置seed, 确保每个group的seed一致
            episode_id 置0
        seed更新逻辑:
            group_seed = seed + group_seed
            episode_seed = group_seed + episode_id

        trajectory_id: f"{group_id}_{episode_id}_{episode_seed}"
        """

        self.start_input_queue_process()
        self.running = True
        self.num_states = [0, 0]  # Track state transitions for each player
        self.episode_id = 0

        self.group_seed = data.meta_info["seed"] + self.env_entry["group_seed"]
        env_output = self.reset()

        while self.running:
            lm_output, current_sequence_length = self.generate(env_output)

            status = EnvStatus(truncated=True, terminated=True)
            if lm_output is not None:
                status: EnvStatus = self.step(lm_output, current_sequence_length)
            else:
                status = self._terminate_failed_generation(current_sequence_length)

            if status.done and self.running:
                rollouts = self.formulate_rollouts()
                for rollout in rollouts:
                    traj_group_id = f"{self.env_entry['group_id']}_{self.episode_id}_{self.group_seed}"
                    sample_suffix = rollout.non_tensor_batch.get("sample_suffix")
                    if sample_suffix is not None:
                        traj_group_id = f"{traj_group_id}{sample_suffix[0]}"
                    # For self-play, append player info to trajectory group ID
                    elif len(rollouts) > 1:  # Self-play mode
                        player_id = rollout.non_tensor_batch.get("group_ids", [""])[0].split("_p")[-1]
                        if player_id.isdigit():
                            traj_group_id = f"{traj_group_id}_p{player_id}"
                    
                    rollout.non_tensor_batch["traj_group_id"] = np.array([traj_group_id], dtype=object)
                    self.output_queue.put_nowait(rollout)
                
                self.rollout_cache = None
                if self.episode_id >= self.worker_config.max_traj_per_env:
                    self.logger.debug(
                        f"env_id: {self.env_config['env_id']} max_traj_per_env {self.worker_config.max_traj_per_env} reached, stopping rollout loop"
                    )
                    break
                env_output = self.reset()

        self.process_input_queue_thread.join()

    def _terminate_failed_generation(self, current_sequence_length: int) -> EnvStatus:
        """Close an episode when no model response can be generated.

        The empty assistant turn is retained only to align the artificial
        terminal reward with the conversation. It is masked from policy
        training because the model did not generate it.
        """
        current_player = self.rollout_cache["current_player"]
        execute_results = self.env_entry["env"].get_losing_state(
            current_player,
            overlong_response=False,
            overlong_sequence=True,
        )
        execute_results[0]["info"].update(
            {
                "format_valid": 0.0,
                "semantic_action_valid": 0.0,
                "action_recovered": 0.0,
                "near_generation_limit": 0.0,
                "response_truncated": 1.0,
                "generation_failed": 1.0,
            }
        )
        env_input = {
            "llm_response": "",
            "llm_raw_response": "",
            "current_sequence_length": current_sequence_length,
            "token_length": 0,
            "token_left": self._generation_context_limit() - current_sequence_length,
            "effective_max_new_tokens": 0,
            "hit_token_limit": False,
            "has_closing_answer_tag": False,
            "valid_action": False,
            "overlong_response": False,
            "overlong_sequence": True,
            "skip_policy_response": True,
        }
        self._log_env_state(
            execute_results=execute_results,
            current_player=current_player,
            format_reward=min(self.worker_config.format_penalty, 0.0),
            env_input=env_input,
        )
        return self.env_entry["status"]

    def get_lm_input(self, env_output, prepare_for_update: bool) -> DataProto:
        llm_input_texts, messages_list = self._format_messages(
            prepare_for_update=prepare_for_update,
            use_raw_llm_response=False,
            player_id=env_output["current_player"],
        )
        # print(f"player_id: {env_output['current_player']}, lm_input_texts: {llm_input_texts}")
        inputs = self.tokenizer(
            llm_input_texts, return_tensors="pt", padding=True, padding_side="left", truncation=False
        )  # do not truncate here. Process later at TODO
        input_ids, attention_mask = inputs.input_ids, inputs.attention_mask
        position_ids = attention_mask.cumsum(dim=-1)
        llm_inputs = DataProto()
        llm_inputs.batch = TensorDict(
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
            },
            batch_size=input_ids.shape[0],
        )
        llm_inputs.non_tensor_batch.update(
            {
                "env_ids": np.array([env_output["env_id"]], dtype=object),
                "group_ids": np.array([env_output["group_id"]], dtype=object),
                "llm_input_texts": np.array(llm_input_texts, dtype=object),
                "messages_list": np.array(messages_list, dtype=object),
                "tags": np.array([env_output["tag"]], dtype=object),
            }
        )
        return llm_inputs

    def get_env_input(self, lm_output: DataProto, current_sequence_length: int) -> Dict:
        if lm_output.batch is not None and "responses" in lm_output.batch.keys():
            generated_response_token_ids = []
            generated_prompt_token_ids = []
            if all(
                key in lm_output.batch.keys()
                for key in ("input_ids", "attention_mask", "response_mask")
            ):
                for input_row, attention_row, response_row in zip(
                    lm_output.batch["input_ids"],
                    lm_output.batch["attention_mask"],
                    lm_output.batch["response_mask"],
                ):
                    attended = attention_row.bool()
                    response_tokens = attended & response_row.bool()
                    prompt_tokens = attended & ~response_row.bool()
                    generated_response_token_ids.append(input_row[response_tokens].tolist())
                    generated_prompt_token_ids.append(input_row[prompt_tokens].tolist())
            else:
                generated_response_token_ids = [
                    row.tolist() for row in lm_output.batch["responses"]
                ]
                generated_prompt_token_ids = [None] * len(generated_response_token_ids)
            responses = self.tokenizer.batch_decode(
                generated_response_token_ids, skip_special_tokens=True
            )
            token_lengths = list(map(len, generated_response_token_ids))
        else:  # dataproto has textual responses
            responses = lm_output.non_tensor_batch["response_texts"]
            token_lengths = list(map(lambda x: len(self.tokenizer.encode(x)) + 1, responses))  # + 1 for eos token
            generated_response_token_ids = [None] * len(responses)
            generated_prompt_token_ids = [None] * len(responses)

        if not self.pipeline_config.use_reason_answer_format:
            responses = [
                "<think>\n" + response if self.pipeline_config.enable_think else "<answer>" + response
                for response in responses
            ]

        env_ids = lm_output.non_tensor_batch["env_ids"]
        env_id = env_ids[0]
        response = responses[0]
        token_length = token_lengths[0]
        llm_response, actions, envelope_valid = self._parse_response(response)
        generation_messages = copy.deepcopy(lm_output.non_tensor_batch["messages_list"][0])
        if isinstance(generation_messages, np.ndarray):
            generation_messages = generation_messages.tolist()
        env_input = {
            "env_id": env_id,
            "llm_raw_response": response,
            "llm_response": llm_response,
            "actions": actions,
            "envelope_valid": envelope_valid,
            # Preserve the exact prompt messages used for this generation. A
            # Markovian training rollout is built from this snapshot instead
            # of reconstructing a different, full-episode conversation.
            "generation_messages": generation_messages,
            # Preserve the inference tokenization for exact on-policy Markovian
            # samples.  Decoding and retokenizing is not guaranteed to round-trip.
            "generated_prompt_token_ids": generated_prompt_token_ids[0],
            "generated_response_token_ids": generated_response_token_ids[0],
            # (tzy) use the token length information to compute length penalty reward.
            "current_sequence_length": current_sequence_length,
            "token_length": token_length,
            "token_left": self._generation_context_limit() - current_sequence_length - token_length,
        }
        effective_max_new_tokens = max(
            min(
                self.worker_config.generating_args.max_new_tokens,
                self._generation_context_limit() - current_sequence_length,
            ),
            1,
        )
        hit_token_limit, overlong_response = generation_limit_status(
            response,
            token_length,
            effective_max_new_tokens,
        )
        env_input["effective_max_new_tokens"] = effective_max_new_tokens
        env_input["near_generation_limit"] = hit_token_limit
        env_input["hit_token_limit"] = hit_token_limit
        env_input["has_closing_answer_tag"] = has_closed_answer(response)
        overlong_sequence = env_input["token_left"] < 0
        return env_input, overlong_response, overlong_sequence

    def formulate_rollouts(self):
        """
        1. 每个env的trajectory 应该是一个rollout
        2. 每个rollout 应该是一个List[Dict]
        3. 每个Dict 应该是一个step的信息
        4. For self-play mode, generate separate trajectories for both players
        
        Returns:
            For single-agent mode: Single DataProto object (for backward compatibility)
            For self-play mode: List of DataProto objects (one for each player)
        """
        # print("env_status: ", self.env_entry["status"])
        # print("rollout cache: ", self.rollout_cache)
        
        # 保护rollout_cache的读取
        with self.internal_lock:
            if self.mode == "train" and self.pipeline_config.markovian_turn_context:
                rollouts = []
                player_ids = (
                    [0, 1]
                    if self.rollout_cache["is_self_play"]
                    else [self.rollout_cache["current_player"]]
                )
                attempts = []
                for player_id in player_ids:
                    history_key = f"player_{player_id}_history"
                    player_history = self.rollout_cache[history_key]
                    if not player_history:
                        continue
                    turn_returns = self._compute_player_turn_returns(player_history)
                    for turn_index, (turn, turn_return) in enumerate(
                        zip(player_history, turn_returns)
                    ):
                        if "llm_raw_response" not in turn or turn.get(
                            "skip_policy_response", False
                        ):
                            continue
                        attempts.append(
                            (player_id, turn_index, turn, turn_return)
                        )
                    self.num_states[player_id] += len(player_history)
                attempts.sort(
                    key=lambda item: (
                        int(item[2].get("decision_index", item[1])),
                        int(item[2].get("retry_attempt_index", 0)),
                        item[0],
                    )
                )
                for player_id, turn_index, turn, turn_return in attempts:
                    rollouts.append(
                        self._formulate_markovian_attempt_rollout(
                            player_id=player_id,
                            turn_index=turn_index,
                            turn=turn,
                            turn_return=turn_return,
                        )
                    )
                return rollouts

            if self.rollout_cache["is_self_play"]:
                # Self-play mode
                rollouts = []
                for player_id in [0, 1]:
                    history_key = f"player_{player_id}_history"
                    if len(self.rollout_cache[history_key]) > 0:
                        rollouts.append(self._formulate_single_rollout(player_id=player_id))
                        self.num_states[player_id] += len(self.rollout_cache[history_key])
                return rollouts
            else:
                # Single agent mode - return single rollout
                return [self._formulate_single_rollout(player_id=self.rollout_cache["current_player"])]


    def _compute_player_turn_returns(self, player_history: List[Dict]) -> List[float]:
        """Combine game return-to-go with auxiliary reward from the same attempt."""
        if self.pipeline_config.game_step_discount is None:
            return [float(turn["reward"]) for turn in player_history]

        discount = self.pipeline_config.game_step_discount
        transition_rewards = [
            turn.get("transition_rewards", [turn["reward"]]) for turn in player_history
        ]
        game_turn_scores = [
            sum(discount ** offset * reward for offset, reward in enumerate(rewards))
            for rewards in transition_rewards
        ]
        game_returns = compute_game_step_turn_returns(
            turn_scores=game_turn_scores,
            turn_steps=[len(rewards) for rewards in transition_rewards],
            discount=discount,
            return_boundaries=[bool(turn.get("return_boundary", False)) for turn in player_history],
        )
        return [
            game_return + float(turn.get("auxiliary_reward", 0.0))
            for game_return, turn in zip(game_returns, player_history)
        ]

    def _format_markovian_attempt(self, turn: Dict) -> Tuple[List[str], List[List[Dict]]]:
        """Format one response with the exact messages used to generate it."""
        if not turn.get("generation_messages"):
            raise ValueError("Markovian attempt is missing its generation_messages snapshot")
        messages = copy.deepcopy(turn["generation_messages"])
        if self.processor:
            prompt_text = self.processor.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        else:
            prompt_text = self.tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        text = prompt_text + turn["llm_raw_response"]
        messages.append({"role": "assistant", "content": turn["llm_raw_response"]})
        return [text.replace("<|im_end|>\n", "<|im_end|>")], [messages]

    def _formulate_markovian_attempt_rollout(
        self,
        player_id: int,
        turn_index: int,
        turn: Dict,
        turn_return: float,
    ) -> DataProto:
        """Create one on-policy training sample for one generation attempt."""
        llm_input_texts, messages_list = self._format_markovian_attempt(turn)
        prompt_token_ids = turn.get("generated_prompt_token_ids")
        response_token_ids = turn.get("generated_response_token_ids")
        if prompt_token_ids is not None and response_token_ids is not None:
            input_ids = torch.tensor(
                [list(prompt_token_ids) + list(response_token_ids)], dtype=torch.long
            )
            attention_mask = torch.ones_like(input_ids)
        else:
            inputs = self.tokenizer(
                llm_input_texts,
                return_tensors="pt",
                padding=True,
                padding_side="left",
                truncation=False,
            )
            input_ids, attention_mask = inputs.input_ids, inputs.attention_mask
        position_ids = attention_mask.cumsum(dim=-1)

        soft_length_penalty = float(turn.get("soft_length_penalty", 0.0))
        base_turn_return = turn_return - soft_length_penalty
        non_prompt_mask, score_tensor, response_mask, turn_end_positions, _ = get_masks_and_scores(
            input_ids,
            self.tokenizer,
            [[base_turn_return]],
            use_turn_scores=True,
        )
        non_prompt_mask = torch.logical_and(non_prompt_mask, attention_mask)
        response_mask = torch.logical_and(response_mask, attention_mask)
        score_tensor = distribute_token_local_length_penalty(
            score_tensor=score_tensor,
            response_mask=response_mask,
            soft_budget=int(self.worker_config.minimax_length_soft_budget),
            sequence_penalties=[soft_length_penalty],
            generated_token_lengths=[int(turn.get("token_length", response_mask.sum().item()))],
        )
        response_length = response_mask.sum(dim=-1).float().mean().item()

        sequence_length = self.pipeline_config.sequence_length
        input_ids = pad_to_length(input_ids, length=sequence_length, pad_value=self.tokenizer.pad_token_id)
        attention_mask = pad_to_length(attention_mask, length=sequence_length, pad_value=0)
        position_ids = pad_to_length(position_ids, length=sequence_length, pad_value=0)
        response_mask = pad_to_length(response_mask, length=sequence_length, pad_value=0)
        non_prompt_mask = pad_to_length(non_prompt_mask, length=sequence_length, pad_value=0)
        score_tensor = pad_to_length(score_tensor, length=sequence_length, pad_value=0)
        turn_end_positions = pad_to_length(turn_end_positions, length=sequence_length, pad_value=0)

        prompt_start = non_prompt_mask.int().argmax(dim=1)
        no_response = ~non_prompt_mask.any(dim=1)
        prompt_start[no_response] = non_prompt_mask.size(1)
        positions = torch.arange(sequence_length, device=non_prompt_mask.device).unsqueeze(0)
        prompt_mask = positions < prompt_start.unsqueeze(1)

        llm_inputs = DataProto()
        llm_inputs.batch = TensorDict(
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
                "penalty": torch.tensor([self.rollout_cache["penalty"]], dtype=torch.float32),
                "llm_response_mask": response_mask,
                "non_prompt_mask": non_prompt_mask,
                "response_mask": response_mask if self.pipeline_config.enable_response_mask else non_prompt_mask,
                "prompt_mask": prompt_mask,
                "scores": score_tensor,
                "turn_end_positions": turn_end_positions,
            },
            batch_size=input_ids.shape[0],
        )

        env_id = self.rollout_cache["env_id"]
        group_id = self.rollout_cache["group_id"]
        sample_suffix = f"_p{player_id}_a{turn_index}"
        decision_info = turn.get("decision_info", turn.get("info", {}))
        decision_record = self._make_minimax_decision_record(turn, player_id, turn_index)
        preflight_record = self._make_preflight_turn_record(turn, player_id, turn_index)

        llm_inputs.non_tensor_batch.update(
            {
                "env_ids": np.array([f"{env_id}{sample_suffix}"], dtype=object),
                "group_ids": np.array([f"{group_id}_p{player_id}"], dtype=object),
                "sample_suffix": np.array([sample_suffix], dtype=object),
                "messages_list": np.array(messages_list, dtype=object),
                "tags": np.array([self.rollout_cache["tag"]], dtype=object),
                "frames": self._object_row([]),
                "turn_scores": self._object_row([turn_return]),
                "transition_rewards": self._object_row(
                    [turn.get("transition_rewards", [turn["reward"]])]
                ),
                "auxiliary_rewards": self._object_row([turn.get("auxiliary_reward", 0.0)]),
                "minimax_decision_records": self._object_row(
                    [decision_record] if decision_record else []
                ),
                "preflight_turn_records": self._object_row([preflight_record]),
                "terminal_info": self._object_row(self.rollout_cache.get("terminal_info", {})),
                "game_step_returns": self._object_row([turn_return]),
                "episode_scores": np.array([turn_return], dtype=object),
                "llm_raw_text_list": np.array([turn["llm_raw_response"]], dtype=object),
                "transition_infos": self._object_row(
                    [turn.get("transition_infos", [turn.get("info", {})])]
                ),
            }
        )

        tag = self.env_entry["tag"]
        metrics = {
            f"env/{tag}/response_length": response_length,
            f"env/{tag}/response_length_per_turn": float(turn.get("token_length", 0)),
            f"env/{tag}/response_length_player_{player_id}": response_length,
            f"env/{tag}/attempt_return": float(turn_return),
            f"env/{tag}/attempt_return_player_{player_id}": float(turn_return),
            f"env/{tag}/game_return_to_go": float(
                turn_return - turn.get("auxiliary_reward", 0.0)
            ),
            f"env/{tag}/game_return_to_go_player_{player_id}": float(
                turn_return - turn.get("auxiliary_reward", 0.0)
            ),
            f"env/{tag}/auxiliary_reward": float(turn.get("auxiliary_reward", 0.0)),
            f"env/{tag}/auxiliary_reward_player_{player_id}": float(
                turn.get("auxiliary_reward", 0.0)
            ),
            f"env/{tag}/soft_length_penalty": soft_length_penalty,
            f"env/{tag}/soft_length_penalty_player_{player_id}": soft_length_penalty,
            f"env/{tag}/validity_and_legacy_penalty": float(
                turn.get("auxiliary_reward", 0.0) - soft_length_penalty
            ),
            f"env/{tag}/validity_and_legacy_penalty_player_{player_id}": float(
                turn.get("auxiliary_reward", 0.0) - soft_length_penalty
            ),
            f"env/{tag}/valid_action_player_{player_id}": float(
                bool(turn.get("valid_action", False))
            ),
            f"env/{tag}/response_truncated_player_{player_id}": float(
                bool(turn.get("overlong_response", False))
                or bool(turn.get("overlong_sequence", False))
            ),
            f"env/{tag}/generation_policy_token_gap_player_{player_id}": float(
                turn.get("token_length", 0) - response_length
            ),
        }
        for key, value in decision_info.items():
            if key.startswith("minimax_") or key == "success" or isinstance(value, str):
                continue
            metrics[f"env/{tag}/{key}"] = float(value)
        llm_inputs.meta_info = {"metrics": metrics}
        return llm_inputs

    @staticmethod
    def _object_row(value) -> np.ndarray:
        result = np.empty(1, dtype=object)
        result[0] = value
        return result

    @staticmethod
    def _make_minimax_decision_record(
        turn: Dict, player_id: int, turn_index: int
    ) -> Optional[Dict]:
        info = turn.get("decision_info", turn.get("info", {}))
        if "minimax_valid_action" not in info:
            return None
        record = {
            "turn_index": turn_index,
            "player_id": player_id,
            "action": turn.get("actions", ""),
            "valid": float(info["minimax_valid_action"]),
            "format_valid": float(info.get("format_valid", 1.0)),
            "semantic_action_valid": float(info.get("semantic_action_valid", 1.0)),
            "action_recovered": float(info.get("action_recovered", 0.0)),
            "near_generation_limit": float(info.get("near_generation_limit", 0.0)),
            "response_truncated": float(info.get("response_truncated", 0.0)),
        }
        if record["valid"]:
            record.update(
                {
                    "spread": float(info["minimax_decision_spread"]),
                    "regret": float(info["minimax_normalized_regret"]),
                    "optimal": float(info["minimax_optimal_action"]),
                }
            )
        return record

    @staticmethod
    def _make_preflight_turn_record(turn: Dict, player_id: int, turn_index: int) -> Dict:
        info = turn.get("decision_info", turn.get("info", {}))
        return {
            "turn_index": turn_index,
            "player_id": player_id,
            "board": turn.get("state", ""),
            "legal_actions": turn.get("legal_actions", {}),
            "parsed_action": turn.get("actions", ""),
            "raw_response": turn["llm_raw_response"],
            "processed_response": turn.get("llm_response", ""),
            "token_length": int(turn.get("token_length", 0)),
            "effective_max_new_tokens": int(turn.get("effective_max_new_tokens", 0)),
            "hit_token_limit": bool(turn.get("hit_token_limit", False)),
            "has_closing_answer_tag": bool(turn.get("has_closing_answer_tag", False)),
            "valid_action": bool(turn.get("valid_action", False)),
            "overlong_response": bool(turn.get("overlong_response", False)),
            "overlong_sequence": bool(turn.get("overlong_sequence", False)),
            "missing_answer": not bool(turn.get("has_closing_answer_tag", False)),
            "capped_without_answer": bool(turn.get("hit_token_limit", False))
            and not bool(turn.get("has_closing_answer_tag", False)),
            "minimax_valid_action": bool(info.get("minimax_valid_action", False)),
            "minimax_optimal_action": bool(info.get("minimax_optimal_action", False)),
            "retry_attempt_index": int(turn.get("retry_attempt_index", 0)),
            "decision_index": int(turn.get("decision_index", 0)),
            "retry_scheduled": bool(turn.get("retry_scheduled", False)),
            "auxiliary_reward": float(turn.get("auxiliary_reward", 0.0)),
            "soft_length_penalty": float(turn.get("soft_length_penalty", 0.0)),
            "return_boundary": bool(turn.get("return_boundary", False)),
        }

    def _formulate_single_rollout(self, player_id=0):
        """Generate a single rollout trajectory, optionally for a specific player in self-play mode"""
        is_self_play = self.rollout_cache["is_self_play"]
        history_key = f"player_{player_id}_history"
            
        llm_input_texts, messages_list = self._format_messages(
            prepare_for_update=True,
            use_raw_llm_response=False,
            player_id=player_id,
            force_full_history_for_reporting=(
                self.mode != "train" and self.pipeline_config.markovian_turn_context
            ),
        )
        # # DEBUG
        # print(f"=====================DEBUG Begin=====================\n")
        # print("llm_input_texts: ", llm_input_texts)
        # # print("messages_list: ", messages_list)
        # print(f"is_self_play: {is_self_play}, player_id: {player_id}, messages_list: {messages_list}")
        # print("env_status: ", self.env_entry["status"])
        # print(f"State:{self.env_entry['env'].render()}")
        # print(f"Info: {self.env_entry['env']._get_info()}\n")
        # print(f"=====================DEBUG End=====================\n")

        inputs = self.tokenizer(
            llm_input_texts, return_tensors="pt", padding=True, padding_side="left", truncation=False
        )
        input_ids, attention_mask = inputs.input_ids, inputs.attention_mask
        position_ids = attention_mask.cumsum(dim=-1)
        llm_inputs = DataProto()
        llm_inputs.batch = TensorDict(
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
            },
            batch_size=input_ids.shape[0],
        )
        return_boundaries = [[
            bool(turn.get("return_boundary", False))
            for turn in self.rollout_cache[history_key]
        ]]
        try:
            if self.pipeline_config.game_step_discount is None:
                scores = [[i["reward"] for i in self.rollout_cache[history_key]]]
                turn_steps = None
            else:
                discount = self.pipeline_config.game_step_discount
                transition_rewards = [
                    turn.get("transition_rewards", [turn["reward"]])
                    for turn in self.rollout_cache[history_key]
                ]
                scores = [[
                    sum(discount ** offset * reward for offset, reward in enumerate(rewards))
                    + turn.get("auxiliary_reward", 0.0)
                    for turn, rewards in zip(self.rollout_cache[history_key], transition_rewards)
                ]]
                turn_steps = [[len(rewards) for rewards in transition_rewards]]
        except:
            print("rollout_cache: ", self.rollout_cache)
            print("history_key: ", history_key)
            raise ValueError("reward not found in rollout_cache")
        # print("scores: ", scores)
        if self.pipeline_config.game_step_discount is None:
            turn_returns = None
            episode_scores = [sum(i) for i in scores]
        else:
            turn_returns = [
                compute_game_step_turn_returns(
                    sample_scores,
                    sample_steps,
                    self.pipeline_config.game_step_discount,
                    sample_boundaries,
                )
                for sample_scores, sample_steps, sample_boundaries in zip(
                    scores, turn_steps, return_boundaries
                )
            ]
            episode_scores = [returns[0] if returns else 0.0 for returns in turn_returns]
        penalty = self.rollout_cache["penalty"]

        non_prompt_mask, score_tensor, response_mask, turn_end_positions, continuation_discounts = get_masks_and_scores(
            input_ids,
            self.tokenizer,
            scores,
            use_turn_scores=self.pipeline_config.use_turn_scores,
            all_turn_steps=turn_steps,
            all_return_boundaries=return_boundaries,
            game_step_discount=self.pipeline_config.game_step_discount,
        )
        untrainable_turn_indices = [
            turn_index
            for turn_index, turn in enumerate(self.rollout_cache[history_key])
            if turn.get("skip_policy_response", False)
        ]
        response_mask, non_prompt_mask = mask_untrainable_response_turns(
            input_ids,
            response_mask,
            non_prompt_mask,
            self.tokenizer,
            untrainable_turn_indices,
        )
        non_prompt_mask = torch.logical_and(non_prompt_mask, attention_mask)
        response_mask = torch.logical_and(response_mask, attention_mask)
        response_length = response_mask.sum(dim=-1).float().mean().item()
        response_length_per_turn = [i["token_length"] for i in self.rollout_cache[history_key]]

        input_ids = pad_to_length(
            input_ids, length=self.pipeline_config.sequence_length, pad_value=self.tokenizer.pad_token_id
        )
        attention_mask = pad_to_length(attention_mask, length=self.pipeline_config.sequence_length, pad_value=0)
        position_ids = pad_to_length(position_ids, length=self.pipeline_config.sequence_length, pad_value=0)
        response_mask = pad_to_length(response_mask, length=self.pipeline_config.sequence_length, pad_value=0)
        non_prompt_mask = pad_to_length(non_prompt_mask, length=self.pipeline_config.sequence_length, pad_value=0)
        score_tensor = pad_to_length(score_tensor, length=self.pipeline_config.sequence_length, pad_value=0)
        turn_end_positions = pad_to_length(turn_end_positions, length=self.pipeline_config.sequence_length, pad_value=0)
        continuation_discounts = pad_to_length(
            continuation_discounts,
            length=self.pipeline_config.sequence_length,
            pad_value=1,
        )

        llm_inputs.batch.update(
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "position_ids": position_ids,
                "penalty": torch.Tensor([penalty]),
            }
        )
        
        # Create trajectory group ID that includes player info for self-play
        env_id = self.rollout_cache["env_id"]
        group_id = self.rollout_cache["group_id"]
        if is_self_play and player_id is not None:
            # Add player suffix to differentiate trajectories
            env_id = f"{env_id}_p{player_id}"
            group_id = f"{group_id}_p{player_id}"
        
        llm_inputs.non_tensor_batch.update(
            {
                "env_ids": np.array([env_id], dtype=object),
                "group_ids": np.array([group_id], dtype=object),
                "messages_list": np.array(messages_list, dtype=object),
                "tags": np.array([self.rollout_cache["tag"]], dtype=object),
                "frames": np.array([self.rollout_cache["frames"]], dtype=object),
            }
        )
        # pad to response length
        llm_inputs.batch["llm_response_mask"] = response_mask
        llm_inputs.batch["non_prompt_mask"] = non_prompt_mask
        llm_inputs.batch["response_mask"] = non_prompt_mask
        if self.pipeline_config.enable_response_mask:
            # 只使用llm的response mask，不包含环境的state
            llm_inputs.batch["response_mask"] = response_mask
        first_true_indices = non_prompt_mask.int().argmax(dim=1)
        no_true_mask = ~non_prompt_mask.any(dim=1)
        first_true_indices[no_true_mask] = non_prompt_mask.size(1)
        batch_size, seq_len = non_prompt_mask.size()
        arange = torch.arange(seq_len, device=non_prompt_mask.device).unsqueeze(0).expand(batch_size, -1)
        prompt_mask = arange < first_true_indices.unsqueeze(1)
        llm_inputs.batch["prompt_mask"] = prompt_mask
        llm_inputs.batch["scores"] = score_tensor
        llm_inputs.batch["turn_end_positions"] = turn_end_positions
        if self.pipeline_config.game_step_discount is not None:
            llm_inputs.batch["continuation_discounts"] = continuation_discounts
        # for llm raw response
        llm_raw_text_list, _ = self._format_messages(
            prepare_for_update=True,
            use_raw_llm_response=True,
            player_id=player_id,
            force_full_history_for_reporting=(
                self.mode != "train" and self.pipeline_config.markovian_turn_context
            ),
        )
        # print("llm_raw_text_list: ", llm_raw_text_list)
        llm_inputs.non_tensor_batch["turn_scores"] = np.array(scores, dtype=object)
        llm_inputs.non_tensor_batch["transition_rewards"] = np.array(
            [[turn.get("transition_rewards", [turn["reward"]]) for turn in self.rollout_cache[history_key]]],
            dtype=object,
        )
        llm_inputs.non_tensor_batch["auxiliary_rewards"] = np.array(
            [[turn.get("auxiliary_reward", 0.0) for turn in self.rollout_cache[history_key]]],
            dtype=object,
        )
        transition_infos = np.empty(1, dtype=object)
        transition_infos[0] = [
            turn.get("transition_infos", [turn.get("info", {})])
            for turn in self.rollout_cache[history_key]
        ]
        llm_inputs.non_tensor_batch["transition_infos"] = transition_infos

        minimax_decision_records = []
        for turn_index, turn in enumerate(self.rollout_cache[history_key]):
            decision_info = turn.get("decision_info", turn.get("info", {}))
            if "minimax_valid_action" not in decision_info:
                continue
            record = {
                "turn_index": turn_index,
                "player_id": player_id,
                "action": turn.get("actions", ""),
                "valid": float(decision_info["minimax_valid_action"]),
                "format_valid": float(decision_info.get("format_valid", 1.0)),
                "semantic_action_valid": float(decision_info.get("semantic_action_valid", 1.0)),
                "action_recovered": float(decision_info.get("action_recovered", 0.0)),
                "near_generation_limit": float(decision_info.get("near_generation_limit", 0.0)),
                "response_truncated": float(decision_info.get("response_truncated", 0.0)),
            }
            if record["valid"]:
                record.update(
                    {
                        "spread": float(decision_info["minimax_decision_spread"]),
                        "regret": float(decision_info["minimax_normalized_regret"]),
                        "optimal": float(decision_info["minimax_optimal_action"]),
                    }
                )
            minimax_decision_records.append(record)
        decision_records_array = np.empty(1, dtype=object)
        decision_records_array[0] = minimax_decision_records
        llm_inputs.non_tensor_batch["minimax_decision_records"] = decision_records_array

        if turn_returns is not None:
            llm_inputs.non_tensor_batch["game_step_returns"] = np.array(turn_returns, dtype=object)
        llm_inputs.non_tensor_batch["episode_scores"] = np.array(episode_scores, dtype=object)
        llm_inputs.non_tensor_batch["llm_raw_text_list"] = np.array(llm_raw_text_list, dtype=object)

        entry = self.env_entry
        status = entry["status"]
        env_metric = {
            "success": float(status.terminated and (not status.truncated)),
            "num_actions": status.num_actions,
            "generation_attempts": status.generation_attempts,
            "retry_attempts": status.retry_attempts,
        }
        preflight_turn_records = []
        for turn_index, turn in enumerate(self.rollout_cache[history_key]):
            if "llm_raw_response" not in turn:
                continue
            decision_info = turn.get("decision_info", turn.get("info", {}))
            preflight_turn_records.append(
                {
                    "turn_index": turn_index,
                    "player_id": player_id,
                    "board": turn.get("state", ""),
                    "legal_actions": turn.get("legal_actions", {}),
                    "parsed_action": turn.get("actions", ""),
                    "raw_response": turn["llm_raw_response"],
                    "processed_response": turn.get("llm_response", ""),
                    "token_length": int(turn.get("token_length", 0)),
                    "effective_max_new_tokens": int(turn.get("effective_max_new_tokens", 0)),
                    "hit_token_limit": bool(turn.get("hit_token_limit", False)),
                    "has_closing_answer_tag": bool(turn.get("has_closing_answer_tag", False)),
                    "valid_action": bool(turn.get("valid_action", False)),
                    "overlong_response": bool(turn.get("overlong_response", False)),
                    "overlong_sequence": bool(turn.get("overlong_sequence", False)),
                    "missing_answer": not bool(turn.get("has_closing_answer_tag", False)),
                    "capped_without_answer": bool(turn.get("hit_token_limit", False)) and not bool(turn.get("has_closing_answer_tag", False)),
                    "minimax_valid_action": bool(decision_info.get("minimax_valid_action", False)),
                    "minimax_optimal_action": bool(decision_info.get("minimax_optimal_action", False)),
                    "retry_attempt_index": int(turn.get("retry_attempt_index", 0)),
                    "decision_index": int(turn.get("decision_index", 0)),
                    "retry_scheduled": bool(turn.get("retry_scheduled", False)),
                    "auxiliary_reward": float(turn.get("auxiliary_reward", 0.0)),
                    "soft_length_penalty": float(turn.get("soft_length_penalty", 0.0)),
                    "return_boundary": bool(turn.get("return_boundary", False)),
                }
            )
        preflight_records_array = np.empty(1, dtype=object)
        preflight_records_array[0] = preflight_turn_records
        llm_inputs.non_tensor_batch["preflight_turn_records"] = preflight_records_array
        terminal_info_array = np.empty(1, dtype=object)
        terminal_info_array[0] = self.rollout_cache.get("terminal_info", {})
        llm_inputs.non_tensor_batch["terminal_info"] = terminal_info_array

        
        # Calculate generic per-trajectory metrics from the decisions generated
        # by this player's tokens. Minimax diagnostics are aggregated from
        # decision records after batch collection so rates use a global
        # valid-action denominator rather than episode sums.
        custom_metric = {}
        for turn in self.rollout_cache[history_key]:
            decision_info = turn.get("decision_info", turn.get("info", {}))
            for k, v in decision_info.items():
                if k == "success":
                    env_metric[k] = float(v)
                    continue
                if k.startswith("minimax_"):
                    continue
                if isinstance(v, str):
                    continue
                if k not in custom_metric:
                    custom_metric[k] = []
                custom_metric[k].append(float(v))

        for k, v in custom_metric.items():
            # env_metric[k] = np.sum(v) / len(player_rollout_cache['history'])
            env_metric[k] = np.sum(v)

        # Terminal outcome information belongs to the episode, not to whichever
        # player happened to generate the final action. Attach it once to both
        # fixed-player rollouts without overwriting their decision diagnostics.
        for k, v in self.rollout_cache.get("terminal_info", {}).items():
            if k.startswith("minimax_") or isinstance(v, str):
                continue
            env_metric[k] = float(v)

        if len(self.rollout_cache[history_key]) > 0:
            self.rollout_cache[history_key][-1]["metrics"] = custom_metric

        env_metric = {f"env/{entry['tag']}/{k}": v for k, v in env_metric.items()}
        env_metric[f"env/{entry['tag']}/response_length"] = response_length
        
        # Add per-turn response length metrics
        env_metric[f"env/{entry['tag']}/response_length_per_turn"] = np.mean(response_length_per_turn)
        for turn_idx, turn_length in enumerate(response_length_per_turn):
            env_metric[f"env/{entry['tag']}/response_length_turn_{turn_idx}"] = turn_length
        # Add player-specific response length metrics for self-play mode
        if is_self_play:
            env_metric[f"env/{entry['tag']}/response_length_player_{player_id}"] = response_length
            # Also add per-turn metrics for each player
            env_metric[f"env/{entry['tag']}/response_length_per_turn_player_{player_id}"] = np.mean(response_length_per_turn)
            for turn_idx, turn_length in enumerate(response_length_per_turn):
                env_metric[f"env/{entry['tag']}/response_length_player_{player_id}_turn_{turn_idx}"] = turn_length
        self.rollout_cache["metrics"] = env_metric
        llm_inputs.meta_info = {"metrics": env_metric}
        return llm_inputs
    
    def _update_player_history(self, player_id: int = None, num_actions_info=None, next_state_entry=None):
        """Update history for a specific player, with thread safety"""
        if player_id is None:
            # Special case: update main history in self-play mode
            history_key = "history"
        else:
            history_key = f"player_{player_id}_history"
        
        self._update_cache_history(
            self.rollout_cache[history_key],
            num_actions_info=num_actions_info,
            next_state_entry=next_state_entry,
        )

    def _update_cache_history(
        self, history: List[Dict], num_actions_info: Optional[Dict] = None, next_state_entry: Optional[Dict] = None
    ):
        """
        Update last step info and append state to history
        """
        if num_actions_info is not None:  # update last step info
            assert len(history), "History should not be empty"
            num_actions_info = num_actions_info.copy()
            for k, v in num_actions_info.items():
                if k == "reward" and k in history[-1]:
                    history[-1][k] += v
                elif k == "transition_rewards" and k in history[-1]:
                    history[-1][k].extend(v)
                elif k == "transition_infos" and k in history[-1]:
                    history[-1][k].extend(v)
                elif k == "auxiliary_reward" and k in history[-1]:
                    history[-1][k] += v
                else:
                    history[-1][k] = v
        if next_state_entry is not None:
            next_state_entry = next_state_entry.copy()
            history.append(next_state_entry)
        return history

    def _extract_map_valid_actions(self, entry: Dict, actions: List[str], legal_actions: Dict[int,str]):
        """extract valid actions from the action lookup table (if exists)"""
        mapped_actions = []
        action_lookup = getattr(entry["env"].config, "action_lookup", None)
        if action_lookup is None:
            mapped_actions = actions
        else:  # the envs have pre-defined action lookup
            rev_action_lookup = {v.lower(): k for k, v in action_lookup.items()}
            actions = [action.lower() for action in actions]
            mapped_actions = [rev_action_lookup[action] for action in actions if action in rev_action_lookup]

        mapped_actions = [action for action in mapped_actions if action in legal_actions.values()]
        illegal_actions = [action for action in actions if action not in legal_actions.values()]
        lose_for_wrong_format = False
        if len(mapped_actions) != 1 or len(illegal_actions) > 0:
            lose_for_wrong_format = True
            # print(f"Invalid actions: {actions}, mapped actions: {mapped_actions}, legal actions: {legal_actions}")
        return mapped_actions, lose_for_wrong_format

    def _log_env_state(
        self, execute_results: Tuple[Dict], current_player: int, format_reward: float = 0, env_input: Dict = None
    ):
        assert execute_results[0]["current_player"] == current_player, (
            f"current_player: {current_player}, execute_results: {execute_results}"
        )
        for idx, turn in enumerate(execute_results):
            current_player = turn["current_player"]
            is_retry = bool(turn["info"].get("retry_attempt", 0.0))
            is_artificial_truncation = bool(turn["info"].get("artificial_truncation", 0.0))
            is_game_transition = not is_retry and not is_artificial_truncation

            if is_game_transition:
                self.env_entry["status"].step += 1
                self.env_entry["status"].num_actions += 1
                self.env_entry["status"].rewards.append(turn["rewards"])
            if turn["done"]:
                self.env_entry["status"].terminated = True
                self.env_entry["status"].truncated = not turn["info"].get("success", False)
                self.rollout_cache["terminal_info"] = turn["info"]
            if (
                is_game_transition
                and self.env_entry["status"].step >= self.env_entry["max_actions_per_traj"]
                and not turn["done"]
            ):
                self.env_entry["status"].truncated = True
                self.env_entry["status"].terminated = True

            actions_left = self.env_entry["max_actions_per_traj"] - self.env_entry["status"].num_actions
            num_actions_info = {
                "actions": turn["action"],
                "reward": turn["rewards"][current_player] if is_game_transition else 0.0,
                "transition_rewards": [turn["rewards"][current_player]] if is_game_transition else [],
                "auxiliary_reward": 0.0,
                "return_boundary": False,
                "info": turn["info"],
                "decision_info": turn["info"],
                "transition_infos": [turn["info"]] if is_game_transition else [],
                "actions_left": actions_left,
            }
            next_state_entry = {
                "player": turn["next_player"],
                "state": turn["observation"],
                "legal_actions": turn["legal_actions"],
            }
            if idx == 0 and env_input is not None:
                legacy_length_penalty = (
                    self.compute_length_penalty(env_input["token_length"])
                    if self.worker_config.enable_length_penalty
                    else 0.0
                )
                soft_length_penalty = self.compute_minimax_length_penalty(
                    env_input["token_length"], turn["info"], env_input["valid_action"]
                )
                auxiliary_reward = format_reward + legacy_length_penalty + soft_length_penalty
                num_actions_info["reward"] += auxiliary_reward
                num_actions_info["auxiliary_reward"] += auxiliary_reward
                num_actions_info["return_boundary"] = not env_input["valid_action"]
                num_actions_info["soft_length_penalty"] = soft_length_penalty
                num_actions_info.update({
                    "llm_response": env_input["llm_response"],
                    "llm_raw_response": env_input["llm_raw_response"],
                    "generated_prompt_token_ids": env_input.get("generated_prompt_token_ids"),
                    "generated_response_token_ids": env_input.get("generated_response_token_ids"),
                    "current_sequence_length": env_input["current_sequence_length"],
                    "token_length": env_input["token_length"],
                    "token_left": env_input["token_left"],
                    "effective_max_new_tokens": env_input["effective_max_new_tokens"],
                    "hit_token_limit": env_input["hit_token_limit"],
                    "has_closing_answer_tag": env_input["has_closing_answer_tag"],
                    "valid_action": env_input["valid_action"],
                    "overlong_response": env_input["overlong_response"],
                    "overlong_sequence": env_input["overlong_sequence"],
                    "skip_policy_response": env_input.get("skip_policy_response", False),
                    "generation_messages": copy.deepcopy(env_input.get("generation_messages", [])),
                    "retry_attempt_index": int(env_input.get("retry_attempt_index", 0)),
                    "decision_index": int(env_input.get("decision_index", 0)),
                    "retry_scheduled": bool(env_input.get("retry_scheduled", False)),
                })

            with self.internal_lock:
                self._update_player_history(None, num_actions_info, next_state_entry)
                self._update_player_history(current_player, num_actions_info, None)

                if is_game_transition:
                    opponent_player = 1 - current_player
                    if len(self.rollout_cache[f"player_{opponent_player}_history"]) > 0:
                        self._update_player_history(
                            opponent_player,
                            {
                                "reward": turn["rewards"][opponent_player],
                                "transition_rewards": [turn["rewards"][opponent_player]],
                                "transition_infos": [turn["info"]],
                            },
                            None,
                        )

                if not self.env_entry["status"].terminated and not self.env_entry["status"].truncated:
                    self._update_player_history(turn["next_player"], None, next_state_entry)

    def _format_messages(
        self,
        prepare_for_update: bool,
        use_raw_llm_response: bool,
        player_id: int = 0,
        force_full_history_for_reporting: bool = False,
    ):
        history_key = "history"

        prompt_history = select_prompt_history(
            self.rollout_cache[history_key],
            prepare_for_update=prepare_for_update,
            use_raw_llm_response=use_raw_llm_response,
            markovian_turn_context=(
                self.pipeline_config.markovian_turn_context
                and not force_full_history_for_reporting
            ),
        )

        prefix_prompt = self.env_entry["env"].get_prompt(
            mode="prefix", 
            think=self.pipeline_config.enable_think,
            player_id=player_id,
        )
        messages = [
            {"role": "system", "content": prefix_prompt["system"]},
            {"role": "user", "content": prefix_prompt["user"]},
        ]

        for idx, content in enumerate(prompt_history):
            if messages[-1]["role"] != "user":
                # ensure the last message is user message.
                messages.append({"role": "user", "content": ""})

            # Original logic for single-agent mode against built-in opponent
            turn_idx = idx + 1
            is_opponent_turn = content["player"] != player_id
            state = content.get("state")
            legal_actions = content.get("legal_actions") or {}
            chosen_action = content.get("actions", "")
            if is_opponent_turn:
                if self.env_entry["env"].include_opponent_turn == "full":
                    turn_idx_content = (
                        f"Information of Turn-{turn_idx}:\n\n"
                        "This is the other player's turn. "
                        "The game state, legal actions, as well as the chosen action of the other player for this turn are provided below.\n\n"
                    )
                elif self.env_entry["env"].include_opponent_turn == "action_full":
                    turn_idx_content = (
                        f"Information of Turn-{turn_idx}:\n\n"
                        "This is the other player's turn. The game state for this turn is not available to you. "
                        "The legal actions and chosen action of the other player for this turn are provided below.\n\n"
                    )
                elif self.env_entry["env"].include_opponent_turn == "action":
                    turn_idx_content = (
                        f"Information of Turn-{turn_idx}:\n\n"
                        "This is the other player's turn. The game state for this turn is not available to you. "
                        "The chosen action of the other player for this turn is provided below.\n\n"
                    )
                elif self.env_entry["env"].include_opponent_turn == "none":
                    continue
            else:
                turn_formatter = getattr(self.env_entry["env"], "format_turn_prompt", None)
                if callable(turn_formatter) and state is not None:
                    turn_idx_content = turn_formatter(
                        state=state,
                        legal_actions=legal_actions,
                        player_id=player_id,
                    )
                    state = None
                else:
                    turn_idx_content = (
                        f"Information of Turn-{turn_idx}:\n\n"
                        "This is your turn. The game state and legal actions for this turn are provided below. "
                        "Please choose your action and strictly follow the given output format in the response instructions.\n\n"
                    )
            messages[-1]["content"] += turn_idx_content
            if state is not None:
                if is_opponent_turn:
                    if self.env_entry["env"].include_opponent_turn == "full":
                        messages[-1]["content"] += (
                            f"GAME STATE:\n{state}\n\n"
                            f"LEGAL ACTIONS:\n{', '.join(legal_actions.values())}.\n\n"
                        )
                    elif self.env_entry["env"].include_opponent_turn == "action_full":
                        messages[-1]["content"] += (
                            f"LEGAL ACTIONS:\n{', '.join(legal_actions.values())}.\n\n"
                        )
                    if chosen_action:
                        messages[-1]["content"] += f"CHOSEN ACTION:\n{chosen_action}\n"
                else:
                    messages[-1]["content"] += (
                        f"GAME STATE:\n{state}\n\n"
                        f"LEGAL ACTIONS:\n{', '.join(legal_actions.values())}.\n\n"
                    )
            if "llm_raw_response" in content and not is_opponent_turn:
                messages.append(
                    {
                        "role": "assistant",
                        # "content": content["llm_response"] if not use_raw_llm_response else content["llm_raw_response"],
                        "content": content["llm_raw_response"],
                    }
                )

        # NOTE: this assertion is important for loss mask computation
        assert all(msg["role"] == "assistant" for msg in messages[2::2])

        if self.processor:
            # processor.chat_template might be different with tokenizer
            # can also set tokenizer.chat_template to processor.chat_template
            text = self.processor.apply_chat_template(
                messages, add_generation_prompt=(not prepare_for_update), tokenize=False
            )
        else:
            text = self.tokenizer.apply_chat_template(
                messages, add_generation_prompt=(not prepare_for_update), tokenize=False
            )
        if use_raw_llm_response:
            prompt_messages = messages[:2]
            if self.processor:
                prompt_text = self.processor.apply_chat_template(
                    prompt_messages, add_generation_prompt=False, tokenize=False
                )
            else:
                prompt_text = self.tokenizer.apply_chat_template(
                    prompt_messages, add_generation_prompt=False, tokenize=False
                )
            text = text[len(prompt_text) :]
        if not prepare_for_update and not self.pipeline_config.use_reason_answer_format:
            if self.pipeline_config.enable_think:
                text += "<think>\n"  # force the LLM to think before answering
            else:
                text += "<answer>"  # force the LLM to answer

        # TODO: 应该没有必要，注意处理mask
        # TODO: special tokens add to config
        text = text.replace("<|im_end|>\n", "<|im_end|>")
        return [text], [messages]

    def _parse_response(self, response: str) -> Tuple[str, List[str], bool]:
        if self.pipeline_config.use_reason_answer_format:
            return self._parse_reason_answer_response(response)

        pattern = (
            r"^<think>(.*?)</think>\s*<answer>(.*?)</answer>$"
            if self.pipeline_config.enable_think
            else r"^<answer>(.*?)</answer>$"
        )
        match = re.search(pattern, response, re.DOTALL)
        envelope_valid = match is not None
        if not match:
            think_content, action_content, actions = "INVALID", "INVALID", []  # 如何更好的处理invalid response?
            # print(f"Invalid response format: {response}")
            # yali: this may be cause potential crash
            # llm_response, actions = response, []
        else:
            if self.pipeline_config.enable_think:
                think_content, action_content = match.group(1), match.group(2)
            else:
                think_content, action_content = "", match.group(1)

            for special_token in self.pipeline_config.special_token_list:
                action_content = action_content.replace(special_token, "").strip()
                think_content = think_content.replace(special_token, "").strip()

            actions = [
                action.strip() for action in action_content.split(self.pipeline_config.action_sep) if action.strip()
            ]
            max_actions = 1

            if len(actions) > max_actions:
                actions = actions[:max_actions]  # Only the first MAX_ACTIONS actions are kept in the rollout.
                action_content = (" " + self.pipeline_config.action_sep + " ").join(actions)

        llm_response = (
            f"<think>\n{think_content}\n</think><answer>{action_content}</answer>"
            if self.pipeline_config.enable_think
            else f"<answer>{action_content}</answer>"
        )
        return llm_response, actions, envelope_valid

    def _parse_reason_answer_response(self, response: str) -> Tuple[str, List[str], bool]:
        reason_match = re.search(r"<reason>(.*?)</reason>", response, re.DOTALL | re.IGNORECASE)
        answer_match = re.search(r"<answer>(.*?)</answer>", response, re.DOTALL | re.IGNORECASE)
        full_match = re.fullmatch(
            r"\s*<reason>(.*?)</reason>\s*<answer>(.*?)</answer>\s*",
            response,
            re.DOTALL | re.IGNORECASE,
        )

        reason_content = reason_match.group(1).strip() if reason_match else ""
        action_content = answer_match.group(1).strip() if answer_match else "INVALID"
        envelope_valid = full_match is not None

        if answer_match is None:
            actions = []
        else:
            for special_token in self.pipeline_config.special_token_list:
                action_content = action_content.replace(special_token, "").strip()
                reason_content = reason_content.replace(special_token, "").strip()

            actions = [
                action.strip()
                for action in action_content.split(self.pipeline_config.action_sep)
                if action.strip()
            ]
            envelope_valid = envelope_valid and len(actions) == 1
            if len(actions) > 1:
                actions = actions[:1]
                action_content = actions[0]

        if reason_match is not None:
            llm_response = (
                f"<reason>{reason_content}</reason>"
                f"<answer>{action_content}</answer>"
            )
        else:
            llm_response = f"<answer>{action_content}</answer>"
        return llm_response, actions, envelope_valid

    def start_input_queue_process(self):
        def process_input_queue(input_queue):
            while True:
                try:
                    command = input_queue.get_nowait()
                except Empty:
                    time.sleep(1)
                    continue
                if command == "stop":
                    self.logger.debug(f"{self.env_config['env_id']} stopped, episode_id: {self.episode_id}")
                    self.running = False
                    ray.get(
                        self.generate_scheduler.abort_request.remote(
                            DataProto(meta_info={"request_id": self.request_id})
                        )
                    )
                    self.request_id = None
                    break

        self.process_input_queue_thread = Thread(target=process_input_queue, args=(self.input_queue,))
        self.process_input_queue_thread.start()
