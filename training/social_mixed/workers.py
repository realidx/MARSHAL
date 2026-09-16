"""Reuse ROLL's Megatron/vLLM strategies with raw native generation evidence."""
import numpy as np
import torch

from roll.distributed.scheduler.decorator import register, Dispatch
from roll.distributed.scheduler.protocol import DataProto
from roll.pipeline.base_worker import ActorWorker
from roll.utils.context_managers import state_offload_manger
from roll.utils.offload_states import OffloadStateType


def object_array(values):
    result = np.empty(len(values), dtype=object)
    result[:] = values
    return result


def weighted_objective(log_probs, old, reference, advantage, mask, weights, clip, kl_coef):
    ratio = (log_probs-old).exp()
    pg = -torch.minimum(ratio*advantage, ratio.clamp(1-clip, 1+clip)*advantage)
    delta = reference-log_probs
    kl = delta.exp()-delta-1
    lengths = mask.sum(-1).clamp_min(1)
    pg_rows = (pg*mask).sum(-1)/lengths
    kl_rows = (kl*mask).sum(-1)/lengths
    return ((pg_rows+kl_coef*kl_rows)*weights).mean(), pg_rows, kl_rows


class SocialWorker(ActorWorker):
    @register(dispatch_mode=Dispatch.ONE_TO_ALL)
    def initialize(self, pipeline_config):
        if self.worker_config.strategy_args.strategy_name == 'hf_infer':
            self.worker_config.model_args.device_map = f'cuda:{self.local_rank}'
        return super().initialize(pipeline_config)

    @register(dispatch_mode=Dispatch.DP_MP_COMPUTE, clear_cache=False)
    @torch.no_grad()
    def generate_native(self, data):
        from vllm import SamplingParams
        requests = data.non_tensor_batch['requests'].tolist()
        if self.worker_config.strategy_args.strategy_name != 'vllm':
            raise ValueError('Native generation requires vLLM')
        params = [SamplingParams(n=1, temperature=1.0, top_p=1.0, top_k=-1,
                                 repetition_penalty=1.0, max_tokens=1024, logprobs=0,
                                 seed=int(r['seed']), stop_token_ids=[self.tokenizer.eos_token_id])
                  for r in requests]
        metrics = {}
        # Keep vLLM awake across decision waves. The pipeline sleeps it once
        # before reference/actor computation, not after each game turn.
        with state_offload_manger(self.strategy, metrics, 'social/generate', is_offload_states=False):
            outputs = self.strategy.model.generate(prompts=[{'prompt_token_ids':r['prompt_ids']} for r in requests],
                                                   sampling_params=params, use_tqdm=False)
        records = []
        for request, output in zip(requests, outputs):
            if list(output.prompt_token_ids) != request['prompt_ids'] or len(output.outputs)!=1:
                raise RuntimeError('Native generation prompt/replica mismatch')
            sample = output.outputs[0]
            ids = list(sample.token_ids)
            if sample.finish_reason not in ('stop','length') or not 0<len(ids)<=1024:
                raise RuntimeError(f'Unscorable native generation: {sample.finish_reason}')
            if sample.logprobs is None or len(sample.logprobs)!=len(ids):
                raise RuntimeError('Missing behavior token log probabilities')
            logprobs = [float(item[token].logprob) for token,item in zip(ids,sample.logprobs)]
            if not np.isfinite(logprobs).all():
                raise RuntimeError('Nonfinite behavior log probability')
            records.append(dict(prompt_ids=request['prompt_ids'], response_ids=ids,
                                behavior_log_probs=logprobs, finish_reason=sample.finish_reason,
                                text=self.tokenizer.decode(ids, skip_special_tokens=False)))
        if len(records)!=len(requests):
            raise RuntimeError('Missing generation outputs')
        return DataProto.from_dict(tensors={'index':torch.arange(len(records))},
                                   non_tensors={'records':object_array(records)}, meta_info={'metrics':metrics})

    @register(dispatch_mode=Dispatch.DP_MP_COMPUTE, clear_cache=False)
    @torch.no_grad()
    def diagnostic_prompt_log_probs(self, data):
        """Teacher-force identical full token sequences through vLLM prefill."""
        from vllm import SamplingParams
        requests=data.non_tensor_batch['requests'].tolist()
        with state_offload_manger(self.strategy, {}, 'diagnostic/prompt', is_offload_states=False):
            self.strategy.model.reset_prefix_cache()
            outputs=self.strategy.model.generate(
                prompts=[{'prompt_token_ids':r['prompt_ids']+r['response_ids']} for r in requests],
                sampling_params=SamplingParams(max_tokens=1,temperature=1.,prompt_logprobs=0),
                use_tqdm=False)
        if len(outputs)!=len(requests):raise RuntimeError('Diagnostic output count mismatch')
        records=[]
        for r,o in zip(requests,outputs):
            ids=r['prompt_ids']+r['response_ids']; n=len(r['prompt_ids'])
            if list(o.prompt_token_ids)!=ids:raise RuntimeError('Diagnostic prompt mismatch')
            if o.prompt_logprobs is None or len(o.prompt_logprobs)!=len(ids):
                raise RuntimeError('Missing diagnostic prompt logprobs')
            values=[float(o.prompt_logprobs[i][ids[i]].logprob) for i in range(n,len(ids))]
            if not np.isfinite(values).all():raise RuntimeError('Nonfinite diagnostic logprobs')
            records.append(values)
        return DataProto.from_dict(tensors={'index':torch.arange(len(records))},
                                   non_tensors={'records':object_array(records)})

    def forward_func_log_probs(self, data, output_tensor):
        # This experiment has no entropy bonus. Avoid a second vocabulary-wide
        # softmax/allocation just to log an unused entropy tensor.
        log_probs = self.strategy.op_compute_log_probs(logits=output_tensor,
                    input_ids=data.batch['input_ids'], attention_mask=data.batch['response_mask'])
        width=data.meta_info.get('social_original_width',data.batch['input_ids'].shape[1])-1
        log_probs=torch.nn.functional.pad(log_probs,(0,width-log_probs.shape[1]))
        # Megatron's forward-only scheduler scales the first return value in place.
        # Clone the recorded result so scheduler bookkeeping cannot divide it by
        # the number of microbatches through shared tensor storage.
        return log_probs, {'log_probs':log_probs.detach().clone(), 'entropy':torch.zeros_like(log_probs)}

    def loss_func(self, data, output_tensor):
        mask = data.batch['response_mask'][:,1:].float()
        log_probs = self.strategy.op_compute_log_probs(logits=output_tensor,
                    input_ids=data.batch['input_ids'], attention_mask=data.batch['response_mask'])
        loss, pg, kl = weighted_objective(log_probs, data.batch['old_log_probs'], data.batch['ref_log_probs'],
                    data.batch['advantages'], mask, data.batch['loss_weight'], self.pipeline_config.pg_clip,
                    self.pipeline_config.kl_loss_coef)
        if not torch.isfinite(loss):
            raise FloatingPointError('Nonfinite policy loss')
        return loss, {'actor/loss':loss.detach().item(), 'actor/pg_loss':pg.mean().detach().item(),
                      'actor/kl':kl.mean().detach().item()}

    @register(dispatch_mode=Dispatch.DP_MP_DISPATCH_FIRST)
    def train_social(self, data):
        if self.worker_config.strategy_args.strategy_name != 'megatron_train':
            raise ValueError('Production training requires Megatron')
        data = self.strategy.get_data_input(data)
        count = len(data)
        micro=self.worker_config.training_args.per_device_train_batch_size
        padded=((count+micro-1)//micro)*micro
        if padded>count:
            from training.social_mixed.batching import pad_weights
            weights=pad_weights(data.batch["loss_weight"],padded)
            data=DataProto.concat([data]+[data[[-1]] for _ in range(padded-count)])
            data.batch["loss_weight"]=weights
        data.meta_info["social_trim_padding"]=True
        metrics = {}
        before = self.strategy.scheduler.state_dict()
        # Variable decision count, but exactly one optimizer update per complete
        # collected batch. Megatron accumulates all microbatches before stepping.
        self.strategy.megatron_train_args.gradient_accumulation_steps = padded//micro
        self.worker_config.training_args.gradient_accumulation_steps = padded//micro
        with state_offload_manger(self.strategy, metrics, 'social/train', is_offload_states=True,
                                 load_kwargs={'include':[OffloadStateType.model_params, OffloadStateType.other_params]}):
            data.to('cuda')
            self.strategy.seq_length = data.batch['input_ids'].shape[1]
            witnesses = []
            if int(data.meta_info.get('global_step',0)) == 0:
                for model in self.strategy.models_unwrapped:
                    for name, parameter in model.named_parameters():
                        if 'norm' in name and parameter.numel():
                            view=parameter.detach().flatten()[:256]
                            witnesses.append((name,parameter,view.cpu().clone()))
            output = self.strategy.train_step(data, self.loss_func)
            if witnesses:
                changed=sum(not torch.equal(before_value,parameter.detach().flatten()[:256].cpu())
                            for _,parameter,before_value in witnesses)
                metrics['actor/first_update_changed_norm_tensors']=float(changed)
                metrics['actor/first_update_checked_norm_tensors']=float(len(witnesses))
            data.to('cpu')
        after = self.strategy.scheduler.state_dict()
        if before == after:
            raise RuntimeError('Megatron scheduler did not advance with optimizer update')
        metrics.update(output)
        metrics['actor/optimizer_steps_per_rollout'] = 1.0
        metrics['actor/accumulated_decisions'] = float(count)
        metrics['actor/microbatch_size'] = float(micro)
        metrics['actor/zero_weight_padding_rows'] = float(padded-count)
        return DataProto(meta_info={'metrics':metrics})
