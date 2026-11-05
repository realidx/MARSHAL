"""Read-only sampled parameter/state witnesses for the two-update GPU preflight.

Parameter witnesses check loaded model tensors; Megatron TP shards are gathered
and converted to HF layout before comparison with the TP=1 sampling replicas.
They are sampled checks, not a full-model cryptographic equality proof.
"""
import hashlib
import json
from pathlib import Path


def tensor_digest(value, samples=32768):
    import torch
    value = value.detach().reshape(-1)
    n = min(value.numel(), samples)
    indices = torch.arange(n, device=value.device, dtype=torch.int64)*max(1,value.numel())//max(1,n)
    sample = value[indices].float().cpu().contiguous()
    if not torch.isfinite(sample).all():
        raise RuntimeError('Nonfinite tensor in training witness')
    return dict(numel=value.numel(), dtype=str(value.dtype), sha256=hashlib.sha256(sample.numpy().tobytes()).hexdigest())


def model_witness(model):
    names = dict(model.named_parameters())
    keys = sorted(k for k in names if k in ('model.embed_tokens.weight','model.norm.weight')
                  or k.endswith('.mlp.down_proj.weight'))
    if 'model.embed_tokens.weight' not in keys or len(keys)<3:
        raise RuntimeError('Expected unfused Qwen TP=1 parameter names for witness')
    if any(names[k].numel()==0 for k in keys):
        raise RuntimeError('HF-layout witness requires populated model tensors')
    return {k:tensor_digest(names[k]) for k in keys}


def state_digest(value):
    import torch
    if torch.is_tensor(value):
        return tensor_digest(value)
    if isinstance(value, dict):
        return {str(k):state_digest(v) for k,v in value.items()}
    if isinstance(value, (tuple,list)):
        return [state_digest(v) for v in value]
    return value


def worker_witness(strategy):
    if getattr(strategy,'strategy_name',None)=='megatron_train':
        from training.b_sft.bp_megatron import training_witness
        return training_witness(strategy)
    model = strategy.unwrap_model()
    result = dict(weights=model_witness(model))
    engine = getattr(strategy,'model',None)
    if hasattr(engine,'global_steps'):
        import random
        import numpy as np
        import torch
        optimizer = engine.optimizer
        result.update(global_steps=engine.global_steps,
            scheduler=state_digest(strategy.scheduler.state_dict()),
            master=state_digest(optimizer.single_partition_of_fp32_groups),
            optimizer=state_digest(optimizer.optimizer.state_dict()),
            rng=dict(python=hashlib.sha256(repr(random.getstate()).encode()).hexdigest(),
                     numpy=hashlib.sha256(repr(np.random.get_state()).encode()).hexdigest(),
                     torch=hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest(),
                     cuda=[hashlib.sha256(s.cpu().numpy().tobytes()).hexdigest() for s in torch.cuda.get_rng_state_all()]))
    return result


def optimizer_step_count(strategy):
    if getattr(strategy,'strategy_name',None)=='megatron_train':
        # Megatron advances its real scheduler only after optimizer.step succeeds.
        value=getattr(strategy.scheduler,'num_steps',None)
    else:
        value=getattr(strategy.model,'global_steps',None)
    if value is None or int(value)!=value:
        raise RuntimeError('Missing integral backend optimizer/scheduler update counter')
    return int(value)


def capture(pipeline, step, phase):
    actor = pipeline.actor_train.execute_all_sync('bp_training_witness')
    reference = pipeline.reference.execute_all_sync('bp_training_witness')
    inference = pipeline.actor_infer.execute_all_sync('bp_training_witness')
    if len(actor)!=2 or len(inference)!=2 or len(reference)!=2:
        raise RuntimeError('Preflight expects two actor ranks, rollout and reference replicas')
    if actor[0]['weights'] != actor[1]['weights']:
        raise RuntimeError('Actor ranks disagree after conversion to full HF weights')
    if any(r['weights'] != actor[0]['weights'] for r in inference):
        raise RuntimeError('vLLM loaded weights differ from current actor')
    root = Path(pipeline.pipeline_config.output_dir)
    previous = root/'bp_weight_witness.jsonl'
    record = dict(step=step,phase=phase,actor=actor,reference=reference,inference=inference,
                  scope='Sampled HF-layout parameters across MLP layers, embedding and final norm; Megatron TP shards are gathered for comparison')
    if previous.exists():
        first = json.loads(previous.read_text().splitlines()[0])
        if reference != first['reference']:
            raise RuntimeError('Frozen reference changed')
    with previous.open('a') as output:
        output.write(json.dumps(record)+'\n')
    return record


def save_rollout(batch, tokenizer, output_dir, step, phase):
    rows=[]
    for i, ground_truth in enumerate(batch.non_tensor_batch['ground_truth']):
        task=json.loads(ground_truth) if isinstance(ground_truth,str) else ground_truth
        ids=batch.batch['input_ids'][i][batch.batch['attention_mask'][i].bool()].cpu().tolist()
        response=batch.batch['input_ids'][i][batch.batch['response_mask'][i].bool()].cpu().tolist()
        rows.append(dict(task_id=task['id'],task=task['task'],sample_seed=int(batch.non_tensor_batch['bp_sample_seed'][i]),
                         input_ids=ids,response_ids=response,content=tokenizer.decode(response,skip_special_tokens=False),
                         finish_reason=str(batch.non_tensor_batch['bp_finish_reason'][i]),
                         reward=float(batch.batch['scores'][i]),policy_optimizer_steps=step,phase=phase))
    path=Path(output_dir)/f'bp_rollout_{phase}_{step}.jsonl'
    if path.exists():
        raise RuntimeError('Refusing to overwrite existing rollout evidence')
    path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows))
