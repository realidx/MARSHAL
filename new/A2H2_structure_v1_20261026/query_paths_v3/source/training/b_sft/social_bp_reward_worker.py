"""B/P binary outcome reward, preserving original generated token evidence."""
import json
from pathlib import Path

import torch

from roll.distributed.executor.worker import Worker
from roll.distributed.scheduler.protocol import DataProto
from roll.distributed.scheduler.decorator import register, Dispatch
from roll.models.model_providers import default_tokenizer_provider
from training.b_sft.social_b_grpo import parse_completion
from training.b_sft.social_bp_training import reward


def decode_ids(response, token_count, finish_reason, max_tokens):
    if finish_reason not in ('stop','length') or not 0 < token_count <= min(len(response),max_tokens):
        raise RuntimeError('Incomplete native generation cannot enter an optimizer group')
    return list(response[:token_count]), finish_reason == 'length'


class SocialBPRewardWorker(Worker):
    def __init__(self, worker_config):
        super().__init__(worker_config=worker_config)
        self.rank_info.dp_rank = self.rank_info.rank; self.rank_info.dp_size = self.rank_info.world_size
        self.tokenizer = default_tokenizer_provider(model_args=worker_config.model_args)
        from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
        self.parser = Hermes2ProToolParser(self.tokenizer)

    @register(dispatch_mode=Dispatch.ONE_TO_ALL)
    def initialize(self, pipeline_config):
        self.pipeline_config = pipeline_config
        self.audit_dir = Path(pipeline_config.output_dir)/'native_reward_calls'; self.audit_dir.mkdir(parents=True, exist_ok=True)

    @register(dispatch_mode=Dispatch.DP_MP_COMPUTE, clear_cache=False)
    def compute_rewards(self, data: DataProto):
        values = []; statuses = []; fullsets = []; exclusions = []; formats = []; investigations = []
        limit = data.meta_info.get('generation_config', {}).get('max_new_tokens', self.pipeline_config.actor_infer.generating_args.max_new_tokens)
        for i, (response, answer) in enumerate(zip(data.batch['responses'], data.non_tensor_batch['ground_truth'])):
            task = json.loads(answer) if isinstance(answer, str) else answer
            ids, truncated = decode_ids(response.tolist(), int(data.non_tensor_batch['bp_token_count'][i]),
                                        data.non_tensor_batch['bp_finish_reason'][i], limit)
            text = self.tokenizer.decode(ids, skip_special_tokens=False)
            completion = parse_completion(self.parser, text, task['tools'], truncated=truncated)
            scored = reward(task, completion)
            if scored['reward'] is None: raise RuntimeError('Infrastructure failure cannot enter a GRPO group')
            values.append(scored['reward']); statuses.append(scored['status'] == 'truncated')
            fullsets.append(scored.get('predicted_full_set', False))
            exclusions.append(scored.get('false_exclusions', 0)); formats.append(scored['status']=='format_failure')
            investigations.append(scored.get('investigated',False))
            record = dict(global_step=data.meta_info.get('global_step'), checkpoint=task['id'], family=task['family'],
                task_kind=task['task'], pool=task['pool'], stage=task['stage'],
                evaluation_phase=data.meta_info.get('evaluation_phase'), evaluated_optimizer_steps=data.meta_info.get('evaluated_optimizer_steps'),
                token_ids=ids, raw_text=text, completion=completion, score=scored)
            with (self.audit_dir/f'{self.rank_info.rank}.jsonl').open('a') as f: f.write(json.dumps(record)+'\n')
        scores = torch.tensor(values, dtype=torch.float32)
        return DataProto.from_dict(tensors=dict(token_level_rewards=torch.zeros_like(data.batch['responses'], dtype=torch.float32),
            response_level_rewards=scores, scores=scores.clone(),
            bp_truncated=torch.tensor(statuses, dtype=torch.float32), bp_fullset=torch.tensor(fullsets, dtype=torch.float32),
            bp_exclusions=torch.tensor(exclusions,dtype=torch.float32), bp_format=torch.tensor(formats,dtype=torch.float32),
            bp_investigated=torch.tensor(investigations,dtype=torch.float32)))
