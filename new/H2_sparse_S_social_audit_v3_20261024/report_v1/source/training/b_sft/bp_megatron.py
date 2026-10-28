"""Megatron TP=2 environment and sampled state checks for B/P training."""
import hashlib
import importlib
import importlib.metadata
import inspect
import json
from pathlib import Path


def validate_environment(tensor_parallel_size=2):
    modules=('megatron.core','transformer_engine.pytorch','flash_attn','mcore_adapter',
             'roll.distributed.strategy.megatron_strategy','roll.third_party.megatron.offload_states_patch')
    loaded={};errors={}
    for name in modules:
        try:
            module=importlib.import_module(name)
            loaded[name]=str(getattr(module,'__file__',None))
        except Exception as exc: errors[name]=f'{type(exc).__name__}: {exc}'
    versions={}
    for name in ('megatron-core','transformer-engine','flash-attn'):
        try: versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name]=None
    if errors:
        raise RuntimeError('Megatron dependencies are unavailable; no models were loaded: '+json.dumps(errors))
    core=versions['megatron-core'] or ''
    if not core.startswith('0.12.'):
        raise RuntimeError(f'MCA requires megatron-core>=0.12,<0.13; found {core!r}')
    from mcore_adapter import TrainingArguments
    from mcore_adapter.models.model_factory import VirtualModels
    from megatron.core.optimizer import MegatronOptimizer
    from megatron.core.optimizer_param_scheduler import OptimizerParamScheduler
    required=((VirtualModels,'all_gather_weights_as_hf_inflight'),
              (MegatronOptimizer,'step'),(MegatronOptimizer,'sharded_state_dict'),
              (OptimizerParamScheduler,'state_dict'),(OptimizerParamScheduler,'load_state_dict'))
    signatures={}
    for owner,name in required:
        signatures[owner.__name__+'.'+name]=str(inspect.signature(getattr(owner,name)))
    # Ensure all translated ROLL fields are accepted before constructing a worker.
    from roll.configs.training_args import TrainingArguments as RollArguments
    kwargs=RollArguments().to_dict();kwargs.pop('optimizer_backend',None)
    kwargs.update(tensor_model_parallel_size=tensor_parallel_size,sequence_parallel=tensor_parallel_size>1,use_distributed_optimizer=True)
    inspect.signature(TrainingArguments).bind(**kwargs)
    return dict(versions=versions,modules=loaded,interfaces=signatures)


def optimizer_witness(optimizer):
    from training.b_sft.bp_training_probe import state_digest
    if hasattr(optimizer,'chained_optimizers'):
        return [optimizer_witness(value) for value in optimizer.chained_optimizers]
    masters=getattr(optimizer,'shard_fp32_from_float16_groups',None)
    if masters is None:
        raise RuntimeError('B/P TP=2 witness requires Megatron distributed BF16 optimizer master shards')
    return dict(master=state_digest(masters),adam=state_digest(optimizer.optimizer.state_dict()))


def training_witness(strategy):
    import random
    import numpy as np
    import torch
    from megatron.core import tensor_parallel
    from roll.utils.offload_states import OffloadStateType
    from training.b_sft.bp_training_probe import tensor_digest, state_digest, optimizer_step_count
    # Both TP ranks participate. Do not compare TP-local parameter shards to HF tensors.
    strategy.load_states(include=[OffloadStateType.model_params])
    weights={}
    try:
        for name, value in strategy.model.all_gather_weights_as_hf_inflight(models=strategy.models_unwrapped):
            if name in ('model.embed_tokens.weight','model.norm.weight') or name.endswith('.mlp.down_proj.weight'):
                weights[name]=tensor_digest(value)
    finally:
        strategy.offload_states(include=[OffloadStateType.model_params])
    if 'model.embed_tokens.weight' not in weights or len(weights)<3:
        raise RuntimeError('Megatron to HF conversion did not expose expected Qwen witness parameters')
    return dict(weights=weights,backend='megatron_train',global_steps=optimizer_step_count(strategy),
        scheduler=state_digest(strategy.scheduler.state_dict()),optimizer=optimizer_witness(strategy.optimizer),
        rng=dict(python=hashlib.sha256(repr(random.getstate()).encode()).hexdigest(),
            numpy=hashlib.sha256(repr(np.random.get_state()).encode()).hexdigest(),
            torch=hashlib.sha256(torch.get_rng_state().numpy().tobytes()).hexdigest(),
            # Native Megatron checkpoints save this rank's current device only.
            # Do not create contexts or compare unsaved RNG on the other GPU.
            cuda=hashlib.sha256(torch.cuda.get_rng_state().cpu().numpy().tobytes()).hexdigest(),
            megatron=state_digest(tensor_parallel.get_cuda_rng_tracker().get_states())))


def complete_checkpoint(directory, world_size, step):
    """Validate native MCA TP shards and distributed optimizer files after upload."""
    import zipfile
    root=Path(directory)
    (root/'COMPLETE.json').unlink(missing_ok=True)
    if world_size not in (1,2):raise RuntimeError('Megatron checkpoint expects TP=1 or 2, PP=1, DP=1')
    required=[root/name for name in ('mca_config.json','latest_checkpointed_iteration.txt',
        'tokenizer.json','tokenizer_config.json','scheduler.pt',
        'pipeline/worker_state_pipeline.json','pipeline/rng_state_pipeline.pth')]
    for rank in range(world_size):
        required.extend((root/f'iter_0000001/mp_rank_{rank:02d}/model_optim_rng.pt',
                         root/f'rng_state/rng_state_{rank}.pth'))
    optimizer=root/'iter_0000001/dist_optimizer'
    required.extend((optimizer/'common.pt',optimizer/'.metadata',optimizer/'metadata.json'))
    shards=list(optimizer.glob('*.distcp'))
    if not shards:raise RuntimeError(f'Missing Megatron distributed optimizer shards: {optimizer}')
    required.extend(shards)
    for path in required:
        if not path.is_file() or path.stat().st_size==0:raise RuntimeError(f'Incomplete checkpoint: {path}')
        if path.suffix in ('.pt','.pth'):
            with zipfile.ZipFile(path) as archive:
                if not archive.namelist():raise RuntimeError(f'Empty checkpoint archive: {path}')
    if (root/'latest_checkpointed_iteration.txt').read_text().strip()!='1':
        raise RuntimeError('Unexpected MCA checkpoint iteration layout')
    result=dict(step=step,world_size=world_size,backend='megatron_train',tp=world_size,dp=1,
        validation='native model/optimizer/RNG files and ZIP directories; resume separately verified',
        files={str(p.relative_to(root)):p.stat().st_size for p in required})
    temporary=root/'COMPLETE.json.tmp';temporary.write_text(json.dumps(result,indent=2)+'\n')
    temporary.replace(root/'COMPLETE.json')
    return result
