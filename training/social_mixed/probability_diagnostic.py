"""Small fixed-token backend comparison; no full-game rollout or checkpoint."""
import json
import os
import hashlib
from pathlib import Path
import numpy as np


def difference(left,right):
    a=np.concatenate(left);b=np.concatenate(right)
    if a.shape!=b.shape or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('Invalid diagnostic probability arrays')
    d=np.abs(a-b)
    return dict(mean=float(d.mean()),p99=float(np.quantile(d,.99)),maximum=float(d.max()))


def run(p):
    import torch
    from roll.distributed.scheduler.protocol import DataProto
    from training.social_mixed.pipeline import make_batch
    from training.social_mixed.workers import object_array
    from roll.utils.functionals import reduce_metrics
    root=p.root/'probability_diagnostic';root.mkdir(exist_ok=True)
    replay_path=os.environ.get('SOCIAL_PROBABILITY_REPLAY_CALLS')
    if replay_path:
        source=Path(replay_path).resolve()
        raw=[json.loads(line) for line in source.read_text().splitlines()]
        if len(raw)<8:raise ValueError('Replay requires at least eight saved rollout calls')
        ordered=sorted(raw,key=lambda r:len(r['prompt_ids'])+len(r['response_ids']))
        indices=torch.linspace(0,len(ordered)-1,8).long().tolist()
        rows=[dict(id=ordered[i]['task_id'],kind=ordered[i]['kind'],
                   prompt_ids=ordered[i]['prompt_ids'],response_ids=ordered[i]['response_ids'],
                   behavior_log_probs=ordered[i]['behavior_log_probs'],source_index=i)
              for i in indices]
        if any(len(r['response_ids'])!=len(r['behavior_log_probs']) for r in rows):
            raise ValueError('Saved behavior probabilities do not match response tokens')
    else:
        rows=json.loads((Path(__file__).resolve().parents[2]/'examples/social_mixed/probability_cases.json').read_text())
    report={'note':'Prefill same fixed tokens; thresholds are gross-error guards, not numerical equivalence certification.',
            'rows':[dict(id=r['id'],kind=r['kind'],prompt_tokens=len(r['prompt_ids']),response_tokens=len(r['response_ids'])) for r in rows],
            'stages':{},'comparisons':{}}
    if replay_path:
        report['replay']=dict(source=str(source),sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                              sorted_indices=indices,source_rows=len(raw))
    from training.social_mixed.workers import weighted_objective
    def save():
        (root/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    def batch(selected):
        return make_batch(selected,p.tokenizer.pad_token_id,tp_multiple=p.pipeline_config.actor_train.strategy_args.strategy_config['tensor_model_parallel_size'])
    def compute(role,selected):
        b=batch(selected);p.log_probs(getattr(p,role),b,'diagnostic')
        return [b.batch['diagnostic'][i,len(r['prompt_ids'])-1:len(r['prompt_ids'])+len(r['response_ids'])-1].cpu().float().tolist() for i,r in enumerate(selected)]
    def native(selected):
        count=len(selected);replicas=p.pipeline_config.actor_infer.world_size
        selected=selected+[selected[-1]]*((-count)%replicas)
        d=DataProto.from_dict(tensors={'index':torch.arange(len(selected))},non_tensors={'requests':object_array(selected)})
        out=DataProto.materialize_concat(p.actor_infer.diagnostic_prompt_log_probs(d,blocking=False))
        return out.non_tensor_batch['records'].tolist()[:count]
    def stage(name,fn):
        with p.phase('diagnostic/'+name):values=fn()
        report['stages'][name]=values;save();return values
    def compare(name,a,b):
        report['comparisons'][name]=difference(a,b);save()
    # Inference loads the original HF weights independently, before any sync.
    initial=stage('vllm_original_hf',lambda:native(rows))
    if replay_path:
        behavior=stage('rollout_behavior',lambda:[r['behavior_log_probs'] for r in rows])
        compare('rollout_behavior_vs_vllm_teacher_forcing',behavior,initial)
    p.actor_infer.offload_states(blocking=True)
    ref=stage('hf_reference_batch',lambda:compute('reference',rows))
    ref_single=stage('hf_reference_single',lambda:[compute('reference',[r])[0] for r in rows])
    actor=stage('megatron_initial_batch',lambda:compute('actor_train',rows))
    actor_single=stage('megatron_initial_single',lambda:[compute('actor_train',[r])[0] for r in rows])
    compare('hf_vs_original_vllm',ref,initial)
    compare('hf_vs_megatron',ref,actor)
    compare('hf_batch_vs_single',ref,ref_single)
    compare('megatron_batch_vs_single',actor,actor_single)
    if replay_path:
        compare('rollout_behavior_vs_megatron',behavior,actor)
    with p.phase('diagnostic/weight_sync'):
        p.actor_train.offload_states(blocking=True);p.model_update(0)
    synced=stage('vllm_after_sync',lambda:native(rows))
    compare('megatron_vs_synced_vllm',actor,synced)
    compare('original_vllm_vs_synced_vllm',initial,synced)
    p.actor_infer.offload_states(blocking=True)
    awake=stage('vllm_after_sleep_wake',lambda:native(rows))
    compare('vllm_before_vs_after_sleep',synced,awake)
    p.actor_infer.offload_states(blocking=True)
    # Write actionable token-level evidence, including highest exponential KL terms.
    with (root/'tokens.jsonl').open('w') as f:
        for i,r in enumerate(rows):
            for j,token in enumerate(r['response_ids']):
                values={name:arr[i][j] for name,arr in report['stages'].items()}
                delta=ref[i][j]-actor[i][j]
                f.write(json.dumps(dict(case=i,response_index=j,token_id=token,text=p.tokenizer.decode([token]),
                    log_probs=values,ref_minus_actor=delta,kl_k3=float(np.expm1(delta)-delta)))+'\n')
    # Separate gradient pressure on token log-probabilities (not parameter gradients).
    x=torch.tensor(np.concatenate(actor),dtype=torch.float64).unsqueeze(0).requires_grad_()
    old=torch.tensor(np.concatenate(synced),dtype=torch.float64).unsqueeze(0)
    reference=torch.tensor(np.concatenate(ref),dtype=torch.float64).unsqueeze(0)
    mask=torch.ones_like(x);advantages=torch.ones_like(x)
    objective,pg,kl=weighted_objective(x,old,reference,advantages,mask,torch.ones(1),.2,.01)
    pg_grad=torch.autograd.grad(pg.mean(),x,retain_graph=True)[0]
    kl_grad=torch.autograd.grad(.01*kl.mean(),x)[0]
    report['token_logprob_gradient_diagnostic']={'scope':'synthetic all-positive advantages; derivatives with respect to log-prob, not parameter gradients',
        'pg_norm':pg_grad.norm().item(),'weighted_kl_norm':kl_grad.norm().item()}
    save()
    guards=('hf_vs_megatron','megatron_vs_synced_vllm','hf_vs_original_vllm','hf_batch_vs_single','megatron_batch_vs_single','vllm_before_vs_after_sleep')
    report['gross_mismatch']=[k for k in guards if report['comparisons'][k]['mean']>.1 or report['comparisons'][k]['maximum']>5.]
    if report['gross_mismatch']:
        report['status']='mismatch_found_update_skipped';save()
        print('PROBABILITY_DIAGNOSIS: mismatch found; inspect '+str(root),flush=True)
        return
    if replay_path:
        report['status']='replay_completed_no_update';save()
        print('PROBABILITY_REPLAY: completed; inspect '+str(root),flush=True)
        return
    # A disposable synthetic gradient exercises update and weight sync only.
    # This is not a scored training experiment and saves no checkpoint.
    for i,r in enumerate(rows):
        r['advantage']=1. if i%2==0 else -1.
        r['behavior_log_probs']=synced[i]
    b=batch(rows)
    for name,values in [('old_log_probs',synced),('ref_log_probs',ref)]:
        v=torch.zeros_like(b.batch['advantages'])
        for i,r in enumerate(rows):
            n=len(r['prompt_ids'])-1;v[i,n:n+len(values[i])]=torch.tensor(values[i])
        b.batch[name]=v
    b.meta_info['global_step']=0
    with p.phase('diagnostic/disposable_update'):
        out=DataProto.materialize_concat(p.actor_train.train_social(b,blocking=False))
        report['update_metrics']=reduce_metrics(out.meta_info['metrics']);save()
    after=stage('megatron_after_update',lambda:compute('actor_train',rows))
    frozen=stage('hf_reference_after_update',lambda:compute('reference',rows))
    p.actor_train.offload_states(blocking=True);p.model_update(1)
    infer_after=stage('vllm_after_update_sync',lambda:native(rows))
    compare('actor_update_change',actor,after)
    compare('reference_drift',ref,frozen)
    compare('updated_actor_vs_vllm',after,infer_after)
    report['status']='diagnosis_completed_review_comparisons';save()
    print('PROBABILITY_DIAGNOSIS: completed; inspect '+str(root),flush=True)
