"""CPU-only compatibility check; no model loading, package changes or GPU jobs."""
import importlib.metadata as metadata
import importlib.util
import json
import sys

def main():
    packages={'torch':'torch','transformers':'transformers','vllm':'vllm','ray':'ray','deepspeed':'deepspeed',
              'hydra-core':'hydra','dacite':'dacite','codetiming':'codetiming','tensordict':'tensordict',
              'datasets':'datasets','more-itertools':'more_itertools'}
    versions={};issues=[]
    for package,module in packages.items():
        try:versions[package]=metadata.version(package)
        except metadata.PackageNotFoundError:versions[package]='source checkout' if importlib.util.find_spec(module) else None
        if versions[package] is None:issues.append('Missing '+package)
    print(json.dumps(dict(versions=versions,issues=issues),indent=2))
    if issues:sys.exit(2)
    import base64, hashlib, os
    from pathlib import Path
    nccl = Path(os.environ['NCCL_LIBRARY'])
    assert base64.urlsafe_b64encode(hashlib.sha256(nccl.read_bytes()).digest()).decode().rstrip('=') == 'Tejvap0n5F4OPQZ8gf3ApxA8sxjjRVfaJZSaQjCpyq8'
    from training.b_sft.test_social_b_ray_logging import RayLoggingTests
    RayLoggingTests('test_constructor_and_actual_file_publication').debug()
    print('Ray log monitor construction and file publication passed.')
    from roll.pipeline.rlvr.rlvr_pipeline import RLVRPipeline
    from training.b_sft.social_b_reward_worker import SocialBRewardWorker
    from roll.distributed.strategy.vllm_strategy import VllmStrategy, create_sampling_params_for_vllm
    from roll.third_party.vllm import LLM
    from vllm import EngineArgs
    from vllm.engine.llm_engine import LLMEngine
    from vllm.worker.worker import Worker
    from roll.third_party.vllm.vllm_0_8_4.ray_distributed_executor import CustomRayDistributedExecutor
    from roll.third_party.vllm.vllm_0_8_4.worker import Worker084
    import inspect
    assert LLM is not None
    assert 'enable_sleep_mode' in inspect.signature(EngineArgs).parameters
    assert {'request_id','processed_inputs','params','arrival_time','lora_request','prompt_adapter_request'} <= set(inspect.signature(LLMEngine._add_processed_request).parameters)
    assert 'tags' in inspect.signature(Worker.wake_up).parameters
    assert hasattr(CustomRayDistributedExecutor, 'WORKER_SPECIFIC_ENV_VARS')
    assert hasattr(Worker084, 'broadcast_parameter') and hasattr(Worker084, 'load_weights')
    from hydra import initialize_config_dir, compose
    from omegaconf import OmegaConf
    from dacite import from_dict
    from roll.pipeline.rlvr.rlvr_config import RLVRConfig
    from pathlib import Path
    with initialize_config_dir(config_dir=str(Path(__file__).resolve().parents[2]/'examples/social_b'),version_base=None):
        config=compose(config_name='grpo')
        parsed=from_dict(RLVRConfig,OmegaConf.to_container(config,resolve=True))
        from training.b_sft.test_social_b_sampling import check_sampling_config
        check_sampling_config(parsed)
        assert parsed.actor_infer.strategy_args.strategy_name == 'vllm'
        assert parsed.actor_infer.strategy_args.strategy_config['enable_sleep_mode'] is False
        assert set(parsed.actor_infer.device_mapping).isdisjoint(parsed.actor_train.device_mapping)
        assert set(parsed.actor_infer.device_mapping).isdisjoint(parsed.reference.device_mapping)
        assert set(parsed.actor_train.device_mapping).isdisjoint(parsed.reference.device_mapping)
        assert parsed.num_nodes == 1 and parsed.num_gpus_per_node == 6
        assert parsed.actor_train.world_size == 4 and parsed.reference.world_size == parsed.actor_infer.world_size == 1
        assert parsed.actor_train.keep_states_on_device and parsed.reference.keep_states_on_device
        zero = parsed.actor_train.strategy_args.strategy_config['zero_optimization']
        assert zero['stage'] == 2 and not zero.get('offload_optimizer') and not zero.get('offload_param')
        assert parsed.checkpoint_config['async_upload'] is False and parsed.checkpoint_config['raise_on_error']
        assert parsed.checkpoint_config['save_final'] and parsed.evaluate_final_model
        assert parsed.actor_train.model_update_frequency == 1
        assert parsed.actor_train.training_args.per_device_train_batch_size * parsed.actor_train.training_args.gradient_accumulation_steps * parsed.actor_train.world_size == parsed.rollout_batch_size * parsed.num_return_sequences_in_group == 32
        sampling=create_sampling_params_for_vllm(dict(max_new_tokens=1024,temperature=0.7,top_p=1.0,top_k=-1,
            repetition_penalty=1.0,num_beams=1,num_return_sequences=8,eos_token_id=[151645]))
        assert sampling.n == 8 and sampling.max_tokens == 1024 and sampling.top_k == -1
        print('Configuration parsed: GRPO steps',parsed.max_steps)
    import torch
    from roll.distributed.strategy.deepspeed_strategy import create_train_scheduler
    parsed.set_max_steps(parsed.max_steps)
    train_args=parsed.actor_train.training_args
    steps=train_args.max_steps // parsed.actor_train.world_size
    if steps <= 0: raise ValueError('No optimizer steps configured')
    optimizer=torch.optim.SGD([torch.nn.Parameter(torch.zeros(1))], lr=train_args.learning_rate)
    scheduler=create_train_scheduler(train_args,optimizer,steps)
    rates=[scheduler.get_last_lr()[0]]
    for _ in range(steps):
        optimizer.step()
        scheduler.step()
        rates.append(scheduler.get_last_lr()[0])
    assert all(__import__('math').isfinite(rate) and rate >= 0 for rate in rates)
    print('Actual training scheduler CPU check:',train_args.lr_scheduler_type,
          'optimizer_steps=',steps,'warmup_steps=',train_args.get_warmup_steps(steps),'learning_rates=',rates)
    from roll.distributed.scheduler.protocol import DataProto
    from roll.utils.functionals import group_reward_norm
    group=DataProto.from_dict(tensors={'response_level_rewards':torch.tensor([0.]*8+[0.,1.]*4)})
    normalized=group_reward_norm(group,n_sample=8).batch['response_level_rewards']
    assert torch.equal(normalized[:8],torch.zeros(8))
    assert torch.isfinite(normalized).all() and normalized[8]<0 and normalized[9]>0
    print('GRPO group normalization passed: zero groups retained, mixed groups finite.')
    print('Imports and configuration passed; GPU initialization and updates are not tested by this check.')
if __name__=='__main__':main()
