"""Private local-Ray driver for the two-GPU B/P preflight; never joins another job."""
import argparse
import json
import os
from pathlib import Path
import tempfile
import shutil


def ray_storage(root=None):
    root=Path(root or os.environ.get('BP_RAY_TMP_ROOT','/raid/chenjiahao/ray')).resolve()
    root.mkdir(parents=True,exist_ok=True)
    usage=shutil.disk_usage(root)
    if usage.free / usage.total < 0.05:
        raise RuntimeError(f'Ray storage {root} has less than 5% free space; select another BP_RAY_TMP_ROOT')
    # Ray creates Unix sockets under session directories; keep their paths short.
    future_socket=root/'bp-xxxxxxxx'/'session_2026-09-15_00-00-00_123456_1234567'/'sockets/plasma_store'
    if len(os.fsencode(future_socket))>=104:
        raise ValueError('BP_RAY_TMP_ROOT is too long for Ray Unix socket paths; choose a shorter directory')
    temp_dir=Path(tempfile.mkdtemp(prefix='bp-',dir=root))
    spill_dir=temp_dir/'spill';spill_dir.mkdir()
    return dict(temp_dir=str(temp_dir),spill_dir=str(spill_dir),address='local',
                disk_total_bytes=usage.total,disk_free_bytes=usage.free)


def config(name, resume=None):
    from hydra import initialize_config_dir, compose
    from omegaconf import OmegaConf
    from dacite import from_dict
    from roll.pipeline.rlvr.rlvr_config import RLVRConfig
    root=Path(__file__).resolve().parents[2]
    with initialize_config_dir(config_dir=str(root/'examples/social_bp'),version_base=None):
        value=compose(config_name=name)
        if resume:
            value.resume_from_checkpoint=str(Path(resume).resolve())
        resolved=OmegaConf.to_container(value,resolve=True)
    parsed=from_dict(RLVRConfig,resolved)
    parsed.set_max_steps(parsed.max_steps)
    assert parsed.actor_train.world_size==2
    assert parsed.actor_infer.world_size==2 and parsed.reference.world_size==2
    strategy=parsed.actor_train.strategy_args.strategy_config
    backend=parsed.actor_train.strategy_args.strategy_name
    if backend=='megatron_train':
        assert strategy['tensor_model_parallel_size']==2 and strategy['pipeline_model_parallel_size']==1
        dp_size=1
    elif backend=='deepspeed_train':
        assert strategy['zero_optimization']['stage']==2
        dp_size=2
    else:
        raise ValueError('Unsupported B/P training backend: '+backend)
    assert parsed.actor_train.training_args.per_device_train_batch_size*parsed.actor_train.training_args.gradient_accumulation_steps*dp_size==128
    assert parsed.rollout_batch_size*parsed.num_return_sequences_in_group==128
    assert parsed.actor_infer.strategy_args.strategy_config['enable_sleep_mode']
    assert not parsed.actor_infer.strategy_args.strategy_config['enforce_eager']
    assert parsed.is_num_return_sequences_expand and parsed.max_running_requests==16
    return parsed,resolved


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--config',default='grpo_two_a100_preflight')
    cli.add_argument('--resume-from')
    args=cli.parse_args()
    # Logging imports create ROLL_LOG_DIR, so reserve the fresh run before imports.
    out=Path(os.environ['BP_RUN_DIR']);out.mkdir(parents=True,exist_ok=False)
    os.environ['BP_STARTUP_DIAGNOSTICS']='1'
    os.environ['BP_DIAGNOSTICS_DIR']=str(out)
    cfg,resolved=config(args.config,args.resume_from)
    assert Path(cfg.output_dir)==out
    (out/'resolved_config.json').write_text(json.dumps(resolved,indent=2)+'\n')
    from training.b_sft.social_bp_grpo import validate_export
    validate_export(os.environ['BP_EXPORT_DIR'])
    import ray
    from training.b_sft.bp_startup import startup_phase
    from roll.pipeline.rlvr.rlvr_pipeline import RLVRPipeline
    from roll.utils.constants import RAY_NAMESPACE
    # Explicitly local: inherited RAY_ADDRESS cannot attach us to somebody else's head.
    storage=ray_storage()
    (out/'ray_session.json').write_text(json.dumps(storage)+'\n')
    try:
        with startup_phase(cfg, 'ray_initialize'):
            ray.init(address='local',num_gpus=2,num_cpus=16,include_dashboard=False,
                     _node_ip_address='127.0.0.1',_temp_dir=storage['temp_dir'],
                     object_spilling_directory=storage['spill_dir'],
                     object_store_memory=1024**3,namespace=RAY_NAMESPACE,
                     runtime_env={'env_vars':{k:os.environ[k] for k in (
                         'PYTHONPATH','CUDA_VISIBLE_DEVICES','ROLL_ASSIGNED_CUDA_DEVICES',
                         'RAY_EXPERIMENTAL_NOSET_CUDA_VISIBLE_DEVICES','VLLM_USE_V1',
                         'VLLM_ATTENTION_BACKEND','TRITON_PTXAS_PATH','PYTORCH_CUDA_ALLOC_CONF',
                         'OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','TOKENIZERS_PARALLELISM',
                         'CUDA_HOME','LD_LIBRARY_PATH','LD_PRELOAD','NCCL_LIBRARY','PATH',
                         'BP_STARTUP_DIAGNOSTICS','BP_DIAGNOSTICS_DIR','CUDA_DEVICE_MAX_CONNECTIONS')}})
        with startup_phase(cfg, 'pipeline_construct'):
            pipeline=RLVRPipeline(cfg)
        pipeline.run()
        (out/'DRIVER_COMPLETE.json').write_text(json.dumps(dict(max_steps=cfg.max_steps,resumed=bool(args.resume_from)))+'\n')
    finally:
        ray.shutdown()


if __name__=='__main__':main()
