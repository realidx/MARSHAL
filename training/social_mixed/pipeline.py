"""Unified social GRPO loop atop the existing ROLL distributed strategies."""
from copy import deepcopy
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import signal
import time

import numpy as np
import torch
from roll.distributed.executor.cluster import Cluster
from roll.distributed.scheduler.protocol import DataProto
from roll.pipeline.base_pipeline import BasePipeline
from roll.models.model_providers import default_tokenizer_provider
from roll.utils.functionals import reduce_metrics
from training.social_mixed.core import Collector, load_data
from training.social_mixed.workers import object_array


def make_batch(rows, pad_id, tp_multiple=2):
    longest = max(len(r['prompt_ids'])+len(r['response_ids']) for r in rows)
    width = math.ceil(longest/tp_multiple)*tp_multiple
    ids = torch.full((len(rows),width), pad_id, dtype=torch.long)
    attention = torch.zeros_like(ids)
    mask = torch.zeros_like(ids)
    advantages = torch.zeros((len(rows),width-1), dtype=torch.float32)
    behavior = torch.zeros_like(advantages)
    for i,r in enumerate(rows):
        prompt, response = r['prompt_ids'],r['response_ids']
        n, end = len(prompt),len(prompt)+len(response)
        if n<1 or not response:
            raise ValueError('Empty prompt/response')
        ids[i,:end] = torch.tensor(prompt+response)
        attention[i,:end] = 1
        mask[i,n:end] = 1
        advantages[i,n-1:end-1] = r['advantage']
        behavior[i,n-1:end-1] = torch.tensor(r['behavior_log_probs'])
    positions = (attention.cumsum(-1)-1).clamp_min(0)
    return DataProto.from_dict(tensors=dict(input_ids=ids, attention_mask=attention, position_ids=positions,
                response_mask=mask, advantages=advantages, behavior_log_probs=behavior,
                loss_weight=torch.tensor([r['loss_weight'] for r in rows],dtype=torch.float32)))


class SocialPipeline(BasePipeline):
    def __init__(self, config, options):
        # BasePipeline uses class-level registries; isolate this experiment.
        self.model_update_groups, self.checkpoint_clusters = [], []
        super().__init__(config)
        self.options = options
        self.root = Path(config.output_dir)
        self.stop_requested = False
        signal.signal(signal.SIGUSR1, self.request_stop)
        signal.signal(signal.SIGTERM, self.request_stop)
        self.tokenizer = default_tokenizer_provider(config.actor_train.model_args)
        try:
            from vllm.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
        except ModuleNotFoundError as exc:
            # vLLM <=0.8 kept the parser under the OpenAI entrypoint.
            if not (exc.name or "").startswith("vllm.tool_parsers"):
                raise
            from vllm.entrypoints.openai.tool_parsers.hermes_tool_parser import Hermes2ProToolParser
        self.parser = Hermes2ProToolParser(self.tokenizer)
        for role in ('actor_train','actor_infer','reference'):
            worker = getattr(config,role)
            setattr(self, role, Cluster(name=worker.name, worker_cls=worker.worker_cls,
                                      resource_manager=self.resource_manager, worker_config=worker))
        # Match the successful SoC actor-first order; never restore the frozen
        # reference from a trained actor checkpoint.
        for role in ('actor_train','actor_infer','reference'):
            cfg = deepcopy(config)
            if role!='actor_train': cfg.resume_from_checkpoint = False
            with self.phase(f'initialize/{role}'):
                getattr(self,role).initialize(pipeline_config=cfg, blocking=True)
        self.set_model_update_pair(self.actor_train,self.actor_infer,frequency=1)
        self.set_checkpoint_clusters(self.actor_train)
        self.collector = Collector(load_data(), self.generate, seed=config.seed,
                                   concurrency=config.actor_infer.world_size*config.actor_infer.strategy_args.strategy_config['max_num_seqs'],
                                   protocol_coefficient=options.get('protocol_coefficient',0.2))
        from training.social_mixed.validation import Validator
        self.validator=Validator(self.collector.data,self.generate,seed=config.seed,
                                 concurrency=self.collector.concurrency)

    def request_stop(self, signum, frame):
        self.stop_requested = True
        print(f'STOP_REQUESTED signal={signum}; saving at optimizer boundary', flush=True)

    @contextmanager
    def phase(self, name):
        start=time.monotonic()
        def write(event, **fields):
            row=dict(phase=name,event=event,utc=time.time(),**fields)
            with (self.root/'phases.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
            print(json.dumps(row),flush=True)
        write('begin')
        try:
            yield
        except BaseException:
            write('error',seconds=time.monotonic()-start)
            raise
        else:
            write('end',seconds=time.monotonic()-start)

    def generate(self, requests):
        from training.b_sft.social_b_grpo import parse_completion
        original = len(requests)
        if original==0:return []
        encoded=[]
        for req in requests:
            rendered = self.tokenizer.apply_chat_template(
                req['messages'], tools=req['tools'], tokenize=True,
                add_generation_prompt=True, return_dict=True, truncation=False)
            ids = rendered['input_ids']
            if (not isinstance(ids, list) or not ids
                    or any(not isinstance(token_id, int) for token_id in ids)):
                raise TypeError('Chat template must return one unbatched list of integer input_ids')
            if len(ids)+1024>self.pipeline_config.sequence_length:
                raise ValueError(f'Prompt has {len(ids)} tokens; refusing to truncate private/public state')
            encoded.append(dict(prompt_ids=ids,seed=req['seed']))
        # Replica dispatch requires divisibility. Dummy padding is never scored or
        # trained, and uses a separate request seed.
        replicas=self.pipeline_config.actor_infer.world_size
        while len(encoded)%replicas:encoded.append(dict(encoded[-1],seed=(encoded[-1]['seed']+1)%2**32))
        from training.social_mixed.batching import balanced_order
        order=balanced_order([len(r['prompt_ids']) for r in encoded],replicas)
        encoded=[encoded[i] for i in order]
        batch=DataProto.from_dict(tensors={'index':torch.arange(len(encoded))},
                                 non_tensors={'requests':object_array(encoded)})
        refs=self.actor_infer.generate_native(batch,blocking=False)
        received=DataProto.materialize_concat(refs).non_tensor_batch['records'].tolist()
        outputs=[None]*len(received)
        for index,value in zip(order,received):outputs[index]=value
        outputs=outputs[:original]
        results=[]
        for req,out in zip(requests,outputs):
            completion=parse_completion(self.parser,out['text'],req['tools'],truncated=out['finish_reason']=='length')
            results.append(dict(out,completion=completion,request=req))
        return results

    def log_probs(self, cluster, batch, key, offload=True):
        # Pad only to the actual DP replica count; discard dummy outputs.
        original=len(batch)
        replicas=cluster.dp_size
        padding=(-original)%replicas
        work=DataProto.concat([batch]+[batch[[-1]]]*padding) if padding else batch
        from training.social_mixed.batching import balanced_order
        order=balanced_order(work.batch['attention_mask'].sum(-1).tolist(),replicas)
        work=work[order]
        work.meta_info.update(is_offload_states=offload,social_trim_padding=True)
        outputs=DataProto.materialize_concat(cluster.compute_log_probs(work,blocking=False))
        inverse=torch.argsort(torch.tensor(order))
        batch.batch[key]=outputs.batch['log_probs'][inverse][:original]

    def save(self, step, force=False):
        checkpoint=self.root/'checkpoints'/f'checkpoint-{step}'
        if (checkpoint/'COMPLETE.json').exists():
            return
        old=self.pipeline_config.save_steps
        if force:self.pipeline_config.save_steps=1
        try:
            with self.phase('checkpoint'):
                self.do_checkpoint(step)
        finally:
            self.pipeline_config.save_steps=old
            self.actor_train.offload_states(blocking=True)
        if not (checkpoint/'COMPLETE.json').is_file():
            raise RuntimeError(f'Checkpoint did not complete: {checkpoint}')
        if (checkpoint/'COMPLETE.json').exists():
            (self.root/'LATEST_CHECKPOINT').write_text(str(checkpoint.resolve())+'\n')
            from training.social_mixed.checkpoints import prune
            removed=prune(self.root,1)
            if removed:
                with (self.root/'checkpoint_retention.jsonl').open('a') as log:
                    log.write(json.dumps(dict(saved=step,removed=removed))+'\n')

    @torch.no_grad()
    def validate(self, step, consumed):
        from training.social_mixed.validation import persist
        with self.phase('validation'):
            try:
                report=self.validator.run()
                # Release inference weights before checkpointing optimizer state.
                self.actor_infer.offload_states(blocking=True)
                metrics=persist(self.root,report,step,consumed,self.tracker)
                self.state.log_history.append(metrics)
                if step>=0:
                    from training.social_mixed.checkpoints import selection_score,SELECTION_VERSION,prune
                    score=selection_score(report['metrics'],self.options['arm'])
                    previous=self.state.kv.get('best_validation')
                    if previous is None or score>previous['score']:
                        checkpoint=self.root/'checkpoints'/f'checkpoint-{step}'
                        best=dict(score=score,step=step,completed_updates=step+1,
                                  selection_version=SELECTION_VERSION,checkpoint=str(checkpoint.resolve()))
                        self.state.kv['best_validation']=best
                        self.save(step,force=True)
                        if not (checkpoint/'COMPLETE.json').is_file():
                            raise RuntimeError('Best checkpoint did not complete')
                        (self.root/'BEST_CHECKPOINT').write_text(str(checkpoint.resolve())+'\n')
                        (self.root/'BEST_VALIDATION.json').write_text(json.dumps(best,indent=2)+'\n')
                        prune(self.root,1)
            except Exception as exc:
                folder=self.root/'validation';folder.mkdir(exist_ok=True)
                (folder/f'step-{step+1}.FAILED.json').write_text(json.dumps(dict(error=repr(exc),scored=False))+'\n')
                raise
            finally:
                self.actor_infer.offload_states(blocking=True)

    @torch.no_grad()
    def run(self):
        cfg=self.pipeline_config
        consumed=int(self.state.kv.get('training_response_tokens',0))
        if self.state.step<0:
            with self.phase('initial_weight_sync'):
                self.actor_train.offload_states(blocking=True)
                self.model_update(0)
            self.validate(-1,consumed)
        elif self.state.kv.get('best_validation'):
            best=self.state.kv['best_validation']
            (self.root/'BEST_CHECKPOINT').write_text(best['checkpoint']+'\n')
            (self.root/'BEST_VALIDATION.json').write_text(json.dumps(best,indent=2)+'\n')
        for step in range(self.state.step+1,cfg.max_steps):
            if consumed>=self.options['total_tokens'] or self.stop_requested:break
            with self.phase('weight_sync'):
                self.actor_train.offload_states(blocking=True)
                self.model_update(step)
            with self.phase('rollout'):
                rows,units,games,metrics=self.collector.collect(step,self.options['arm'],self.options['tokens_per_update'])
                for name, records in (('calls',rows),('units',units),('games',games)):
                    folder=self.root/name;folder.mkdir(exist_ok=True)
                    with (folder/f'step-{step}.jsonl').open('w') as f:
                        for record in records:f.write(json.dumps(record,ensure_ascii=False)+'\n')
                self.actor_infer.offload_states(blocking=True)
            batch=make_batch(sorted(rows,key=lambda r:len(r['prompt_ids'])+len(r['response_ids'])),self.tokenizer.pad_token_id,tp_multiple=self.pipeline_config.actor_train.strategy_args.strategy_config['tensor_model_parallel_size'])
            batch.meta_info['global_step']=step
            with self.phase('reference_log_probs'):
                self.log_probs(self.reference,batch,'ref_log_probs')
            with self.phase('actor_log_probs'):
                audit=batch[torch.linspace(0,len(batch)-1,min(8,len(batch))).long().tolist()]
                self.log_probs(self.actor_train,audit,'audit_log_probs',offload=False)
            mask=audit.batch['response_mask'][:,1:].bool()
            difference=(audit.batch['audit_log_probs']-audit.batch['behavior_log_probs'])[mask].abs()
            metrics['behavior_actor_logprob_abs_mean']=difference.mean().item()
            metrics['behavior_actor_logprob_abs_max']=difference.max().item()
            # Use the actual behavior distribution in the PPO denominator;
            # sampling is unfiltered temperature=1. Save actor recomputation
            # discrepancy to diagnose backend numerical differences.
            batch.batch['old_log_probs']=batch.batch['behavior_log_probs'].clone()
            if not torch.isfinite(batch.batch['ref_log_probs']).all():
                raise FloatingPointError('Nonfinite reference log probabilities')
            with self.phase('optimizer_update'):
                trained=DataProto.materialize_concat(self.actor_train.train_social(batch,blocking=False))
                metrics.update(reduce_metrics(trained.meta_info['metrics']))
            consumed+=metrics['generated_tokens']
            metrics.update({'system/step':step,'training_response_tokens':consumed})
            self.state.step=step
            self.state.kv['training_response_tokens']=consumed
            self.state.log_history.append(metrics)
            force=consumed>=self.options['total_tokens'] or self.stop_requested or step+1==cfg.max_steps
            with (self.root/'metrics.jsonl').open('a') as f:f.write(json.dumps(metrics)+'\n')
            self.tracker.log(metrics,step=step+1)
            if ((step+1)%cfg.eval_steps==0 or consumed>=self.options['total_tokens'] or step+1==cfg.max_steps) and not self.stop_requested:
                self.model_update(step+1)
                self.validate(step,consumed)
            if force or (step+1)%cfg.save_steps==0:self.save(step,force=force)
            if self.stop_requested:break
        # A time-limit stop while validating also needs the latest optimizer state.
        if self.stop_requested and self.state.step>=0:
            self.save(self.state.step,force=True)
        if self.state.step>=0:
            latest=self.root/'checkpoints'/f'checkpoint-{self.state.step}'
            if not (latest/'COMPLETE.json').is_file():self.save(self.state.step,force=True)
            if (latest/'COMPLETE.json').is_file():
                (self.root/'LAST_CHECKPOINT').write_text(str(latest.resolve())+'\n')
        result=dict(status='paused' if self.stop_requested else 'complete',updates=self.state.step+1,
                    training_response_tokens=consumed,token_budget=self.options['total_tokens'])
        if not self.stop_requested and consumed<self.options['total_tokens']:
            result['status']='step_limit_before_token_budget'
        (self.root/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
