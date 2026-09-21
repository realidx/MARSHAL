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
from training.social_mixed.core import load_data
from training.social_mixed.stabilization import StableCollector as Collector, VERSION, learning_rate
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
                loss_weight=torch.tensor([r['loss_weight'] for r in rows],dtype=torch.float32),
                **{key:torch.tensor([r.get(key, r['advantage'] if key=='task_advantage' else r['loss_weight'] if key.endswith('_weight') else 0.) for r in rows],dtype=torch.float32) for key in
                   ('task_advantage','protocol_advantage','task_weight','protocol_weight','kl_weight','task_denominator')}))


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
        data=load_data()
        reasoning=options.get('recipe')=='reasoning'
        collector_type=Collector
        extra={}
        if reasoning:
            from training.social_mixed.reasoning_training import ReasoningCollector
            from training.social_mixed.reasoning_bank import load
            collector_type=ReasoningCollector
            data['bp_train']=load('train')
            extra['normalization']=options['normalization']
        self.collector = collector_type(data, self.generate, seed=config.seed,
                                   concurrency=config.actor_infer.world_size*config.actor_infer.strategy_args.strategy_config['max_num_seqs'],
                                   protocol_coefficient=options.get('protocol_coefficient',0.2),**extra)
        if not reasoning and options['arm'] in ('outcome','decomposed'):
            from training.social_mixed.paired_bank import load
            self.collector.data['bp_train']=load('train')
        saved_recipe=self.state.kv.get('stable_recipe')
        if saved_recipe:
            self.collector.restore(saved_recipe)
        elif self.state.step>=0:
            raise ValueError('Old recipe checkpoint: export actor and start a new stage; do not resume optimizer silently')
        from training.social_mixed.validation import Validator
        if reasoning:
            from training.social_mixed.reasoning_validation import ReasoningValidator as Validator
        self.validator=Validator(self.collector.data,self.generate,seed=config.seed,
                                 concurrency=self.collector.concurrency)
        if not reasoning and options['arm'] in ('outcome','decomposed'):
            # Fixed unassisted paired dev; same cases and criterion for both arms.
            from training.social_mixed.paired_bank import development_panel
            self.validator.tasks=development_panel()


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
            encoded.append(dict(prompt_ids=ids,seed=req['seed'],temperature=req.get('temperature',1.0)))
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
    def validate(self, step, consumed, selection_candidate=True):
        from training.social_mixed.validation import persist
        with self.phase('validation'):
            try:
                report=self.validator.run()
                report['protocol']['selection_candidate']=bool(step>=0 and selection_candidate)
                if self.options.get('recipe')=='reasoning':
                    from training.social_mixed.reasoning_validation import metrics_and_state
                    retention,state=metrics_and_state(report['bp_calls'],self.state.kv.get('reasoning_retention'))
                    report['metrics'].update(retention)
                    self.state.kv['reasoning_retention']=state
                    self.monitor_o(step,consumed,report['bp_calls'])
                # Release inference weights before checkpointing optimizer state.
                self.actor_infer.offload_states(blocking=True)
                metrics=persist(self.root,report,step,consumed,self.tracker)
                self.state.log_history.append(metrics)
                if step>=0 and selection_candidate:
                    from training.social_mixed.checkpoints import selection_score,SELECTION_VERSION,prune
                    if self.options.get('recipe')=='reasoning':
                        from training.social_mixed.reasoning_validation import selection_score as reasoning_score, VERSION as SELECTION_VERSION
                        score=reasoning_score(report['metrics'])
                        checkpoint=self.root/'checkpoints'/f'checkpoint-{step}'
                        candidates=self.state.kv.setdefault('reasoning_candidates',[])
                        candidates.append(dict(step=step,tokens=consumed,checkpoint=str(checkpoint.resolve()),score=score))
                        (self.root/'EVALUATED_CHECKPOINTS.json').write_text(json.dumps(candidates,indent=2)+'\n')
                    else:
                        score=selection_score(report['metrics'],self.options['arm'])
                    previous=self.state.kv.get('best_validation')
                    if previous is None or score>previous['score']:
                        checkpoint=self.root/'checkpoints'/f'checkpoint-{step}'
                        retained=self.options['keep_checkpoints']>1
                        best=dict(score=score,step=step,completed_updates=step+1,
                                  selection_version=SELECTION_VERSION,checkpoint=str(checkpoint.resolve()),
                                  checkpoint_retained=retained)
                        self.state.kv['best_validation']=best
                        (self.root/'BEST_VALIDATION.json').write_text(json.dumps(best,indent=2)+'\n')
                        if retained:
                            self.save(step,force=True)
                            if not (checkpoint/'COMPLETE.json').is_file():
                                raise RuntimeError('Best checkpoint did not complete')
                            (self.root/'BEST_CHECKPOINT').write_text(str(checkpoint.resolve())+'\n')
                            prune(self.root,1)
                    if self.options.get('recipe')=='reasoning':
                        self.save(step,force=True)
            except Exception as exc:
                folder=self.root/'validation';folder.mkdir(exist_ok=True)
                (folder/f'step-{step+1}.FAILED.json').write_text(json.dumps(dict(error=repr(exc),scored=False))+'\n')
                raise
            finally:
                self.actor_infer.offload_states(blocking=True)

    @torch.no_grad()
    def monitor_o(self, step, consumed, calls=None):
        from training.social_mixed.reasoning_validation import metrics_and_state
        with self.phase('static_o_monitor'):
            try:
                if calls is None:calls=self.validator.run_static_o()
                calls=[r for r in calls if r['task']['paired_view']=='O']
                metrics,state=metrics_and_state(calls,self.state.kv.get('static_o_retention'))
                self.state.kv['static_o_retention']=state
                folder=self.root/'static_o_monitor';folder.mkdir(exist_ok=True)
                report=dict(step=step,completed_updates=step+1,tokens=consumed,
                            selection_candidate=False,metrics=metrics,calls=calls)
                (folder/f'step-{step+1}.json').write_text(json.dumps(report,ensure_ascii=False)+'\n')
                self.tracker.log({'monitor/'+k:v for k,v in metrics.items()},step=step+1)
            finally:
                self.actor_infer.offload_states(blocking=True)

    @torch.no_grad()
    def run(self):
        cfg=self.pipeline_config
        consumed=int(self.state.kv.get('training_response_tokens',0))
        early_gate_reached=False
        if self.options.get('recipe')=='reasoning' and self.state.kv.get('reasoning_candidates'):
            (self.root/'EVALUATED_CHECKPOINTS.json').write_text(json.dumps(self.state.kv['reasoning_candidates'],indent=2)+'\n')
        if self.state.step<0:
            with self.phase('initial_weight_sync'):
                self.actor_train.offload_states(blocking=True)
                self.model_update(0)
            self.validate(-1,consumed)
        elif self.state.kv.get('best_validation'):
            best=self.state.kv['best_validation']
            if best.get('checkpoint_retained',True):
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
            batch.meta_info['social_lr']=learning_rate(consumed,self.options['total_tokens'])
            with self.phase('reference_log_probs'):
                self.log_probs(self.reference,batch,'ref_log_probs')
            with self.phase('actor_log_probs'):
                audit=batch[torch.linspace(0,len(batch)-1,min(8,len(batch))).long().tolist()]
                self.log_probs(self.actor_train,audit,'audit_log_probs',offload=False)
            mask=audit.batch['response_mask'][:,1:].bool()
            difference=(audit.batch['audit_log_probs']-audit.batch['behavior_log_probs'])[mask].abs()
            metrics['behavior_actor_logprob_abs_mean']=difference.mean().item()
            metrics['behavior_actor_logprob_abs_max']=difference.max().item()
            if self.options.get('recipe')=='reasoning':
                ratios=(audit.batch['audit_log_probs']-audit.batch['behavior_log_probs'])[mask].exp()
                fraction=((ratios<.8)|(ratios>1.2)).float().mean().item()
                metrics['behavior_preupdate_clip_fraction']=fraction
                if not torch.isfinite(difference).all() or not torch.isfinite(ratios).all():
                    (self.root/'PROBABILITY_ACCEPTANCE_FAILED.json').write_text(json.dumps(metrics,indent=2)+'\n')
                    raise FloatingPointError('Nonfinite actor/behavior probability comparison before optimizer update')
                exceeded=(difference.mean().item()>self.options['max_behavior_logprob_delta']
                          or fraction>self.options['max_behavior_clip_fraction'])
                metrics['behavior_probability_warning']=int(exceeded)
                if exceeded:
                    warning=dict(event='PROBABILITY_WARNING',step=step,action='continue_training',
                                 mean_limit=self.options['max_behavior_logprob_delta'],
                                 clip_fraction_limit=self.options['max_behavior_clip_fraction'],
                                 metrics=dict(metrics))
                    with (self.root/'probability_warnings.jsonl').open('a') as f:
                        f.write(json.dumps(warning)+'\n')
                    print(json.dumps(warning),flush=True)
            # Use the actual behavior distribution in the PPO denominator;
            # sampling is unfiltered temperature=1. Save actor recomputation
            # discrepancy to diagnose backend numerical differences.
            batch.batch['old_log_probs']=batch.batch['behavior_log_probs'].clone()
            if not torch.isfinite(batch.batch['ref_log_probs']).all():
                raise FloatingPointError('Nonfinite reference log probabilities')
            if not metrics.get('skip_optimizer',False):
                with self.phase('optimizer_update'):
                    trained=DataProto.materialize_concat(self.actor_train.train_social(batch,blocking=False))
                    metrics.update(reduce_metrics(trained.meta_info['metrics']))
            consumed+=metrics['generated_tokens']
            metrics.update({'system/step':step,'training_response_tokens':consumed})
            self.state.step=step
            self.state.kv['training_response_tokens']=consumed
            self.state.kv['stable_recipe']=deepcopy(self.collector.state)
            metrics['recipe/'+('reasoning_fixed_exposure' if self.options.get('recipe')=='reasoning' else 'stable_v1')]=1
            metrics['actor/applied_lr']=batch.meta_info['social_lr'] if not metrics.get('skip_optimizer') else 0.
            self.state.log_history.append(metrics)
            pause_after=self.options.get('pause_after_updates')
            early_gate_reached=pause_after is not None and step+1>=pause_after
            force=consumed>=self.options['total_tokens'] or self.stop_requested or early_gate_reached or step+1==cfg.max_steps
            evaluate=(step+1)%cfg.eval_steps==0 or consumed>=self.options['total_tokens'] or step+1==cfg.max_steps
            with (self.root/'metrics.jsonl').open('a') as f:f.write(json.dumps(metrics)+'\n')
            self.tracker.log(metrics,step=step+1)
            if evaluate and not self.stop_requested:
                self.model_update(step+1)
                self.validate(step,consumed)
            elif self.options.get('recipe')=='reasoning' and not self.stop_requested and step+1 in (4,8):
                self.model_update(step+1)
                self.validate(step,consumed,selection_candidate=False)
            elif (self.options.get('recipe')=='reasoning' and not self.stop_requested
                  and ((step+1 in (2,4,6,8)) or (step+1>8 and (step+1)%5==0))):
                self.model_update(step+1)
                self.monitor_o(step,consumed)
            if force or (step+1)%cfg.save_steps==0:self.save(step,force=force)
            if self.stop_requested:break
            if early_gate_reached:break
        # A time-limit stop while validating also needs the latest optimizer state.
        if self.stop_requested and self.state.step>=0:
            self.save(self.state.step,force=True)
        if self.state.step>=0:
            latest=self.root/'checkpoints'/f'checkpoint-{self.state.step}'
            if not (latest/'COMPLETE.json').is_file():self.save(self.state.step,force=True)
            if (latest/'COMPLETE.json').is_file():
                (self.root/'LAST_CHECKPOINT').write_text(str(latest.resolve())+'\n')
        status='paused' if self.stop_requested else 'early_gate' if early_gate_reached else 'complete'
        result=dict(status=status,updates=self.state.step+1,
                    training_response_tokens=consumed,token_budget=self.options['total_tokens'])
        if not self.stop_requested and not early_gate_reached and consumed<self.options['total_tokens']:
            result['status']='step_limit_before_token_budget'
        (self.root/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
