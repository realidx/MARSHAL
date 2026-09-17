"""ROLL reward worker using the same native parser as the working vLLM service."""
import json
from pathlib import Path
import torch
from roll.distributed.executor.worker import Worker
from roll.distributed.scheduler.protocol import DataProto
from roll.distributed.scheduler.decorator import register, Dispatch
from roll.models.model_providers import default_tokenizer_provider
from training.b_sft.social_b_grpo import parse_completion
from training.b_sft.social_b_rl import reward
from training.b_sft.social_b_evaluation import score_attempt
from training.b_sft.social_b_training_data import diagnostics


class SocialBRewardWorker(Worker):
    def __init__(self,worker_config):
        super().__init__(worker_config=worker_config)
        self.rank_info.dp_rank=self.rank_info.rank;self.rank_info.dp_size=self.rank_info.world_size
        self.tokenizer=default_tokenizer_provider(model_args=worker_config.model_args)
        from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
        self.parser=Hermes2ProToolParser(self.tokenizer)

    @register(dispatch_mode=Dispatch.ONE_TO_ALL)
    def initialize(self,pipeline_config):
        self.pipeline_config=pipeline_config
        self.audit_dir=Path(pipeline_config.output_dir)/'native_reward_calls'
        self.audit_dir.mkdir(parents=True,exist_ok=True)

    @register(dispatch_mode=Dispatch.DP_MP_COMPUTE,clear_cache=False)
    def compute_rewards(self,data:DataProto):
        values=[]; diagnostic_rows=[]
        eos=self.tokenizer.eos_token_id
        eos_ids=set(eos if isinstance(eos,list) else [eos])
        for response,answer in zip(data.batch['responses'],data.non_tensor_batch['ground_truth']):
            t=json.loads(answer) if isinstance(answer,str) else answer
            ids=response.tolist()
            # Generated arrays are right padded; include EOS when present.
            end=next((i+1 for i,v in enumerate(ids) if v in eos_ids),None)
            if end is not None:ids=ids[:end]
            else:
                while ids and ids[-1]==self.tokenizer.pad_token_id:ids.pop()
            truncated=end is None and len(ids)>=self.pipeline_config.actor_infer.generating_args.max_new_tokens
            if not ids or end is None and not truncated:
                raise RuntimeError('Missing EOS below token limit: generation/termination cannot be audited')
            text=self.tokenizer.decode(ids,skip_special_tokens=False)
            completion=parse_completion(self.parser,text,t['tools'],truncated=truncated)
            r=reward(t,completion)
            if r['reward'] is None:raise RuntimeError('Infrastructure failures cannot enter GRPO reward groups')
            values.append(r['reward'])
            score=score_attempt(t,completion)
            diagnostic_rows.append(diagnostics(t,score))
            record=dict(global_step=data.meta_info.get('global_step'),checkpoint=t['id'],family=t['family'],category_queries=t['category_queries'],
                        evaluation_phase=data.meta_info.get('evaluation_phase'),
                        evaluated_optimizer_steps=data.meta_info.get('evaluated_optimizer_steps'),
                        curriculum=t.get('curriculum'),training_unit=t.get('training_unit'),
                        token_ids=ids,raw_text=text,completion=completion,score=score,reward=r)
            with (self.audit_dir/f'{self.rank_info.rank}.jsonl').open('a') as f:f.write(json.dumps(record,ensure_ascii=False)+'\n')
        scores=torch.tensor(values,dtype=torch.float32)
        tensors=dict(token_level_rewards=torch.zeros_like(data.batch['responses'],dtype=torch.float32),
                     response_level_rewards=scores,scores=scores.clone())
        keys=set().union(*(row.keys() for row in diagnostic_rows))
        # Fixed keys across workers, including batches where every output fails.
        for key in keys:
            tensors['b_'+key]=torch.tensor([row.get(key,0) for row in diagnostic_rows],dtype=torch.float32)
        return DataProto.from_dict(tensors=tensors)
